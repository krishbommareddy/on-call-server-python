# app.py

import json
import logging
from datetime import datetime, date, timedelta
import copy
import random
from functools import wraps
from flask import Flask, jsonify, request, render_template, send_file
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm.attributes import flag_modified # FIX: Import the helper
from flask_migrate import Migrate
import io
import math
import re
import os

# --- App Initialization, Config, and Extensions ---
app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///scheduler.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- (The rest of the file is unchanged, but provided for completeness) ---
# --- Constants ---
EMAIL_REGEX = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
# --- Decorator for Error Handling ---
def api_error_handler(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try: return f(*args, **kwargs)
        except Exception as e:
            logging.error(f"An error occurred in endpoint '{f.__name__}': {e}", exc_info=True)
            return jsonify({"error": "An unexpected server error occurred."}), 500
    return decorated_function
# --- Database Models ---
class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(8), unique=True, nullable=False)
    baseGroups = db.Column(db.JSON, default=lambda: [[]])
    monthlyPriorities = db.Column(db.JSON, default=lambda: {})
    assignments = db.Column(db.JSON, default=lambda: {})
    shifts_per_day = db.Column(db.Integer, default=1, nullable=False)
    shift_overrides = db.Column(db.JSON, default=lambda: {})
    def to_dict(self):
        return { "name": self.name, "shifts_per_day": self.shifts_per_day, "baseGroups": self.baseGroups, "monthlyPriorities": self.monthlyPriorities, "assignments": self.assignments, "shift_overrides": self.shift_overrides }
class Engineer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(12), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    maxShifts = db.Column(db.Integer, default=2, nullable=False)
    consecutive_pref = db.Column(db.String(10), default='neutral', nullable=False)
    preferences = db.Column(db.JSON, default=lambda: {})
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    team = db.relationship('Team', backref=db.backref('engineers', lazy='dynamic'))
    def to_dict(self):
        return { "name": self.name, "team": self.team.name, "email": self.email, "maxShifts": self.maxShifts, "preferences": self.preferences or {}, "consecutive_pref": self.consecutive_pref }
class Holiday(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(10), unique=True, nullable=False)
    note = db.Column(db.String(10), nullable=False, default='')
    def to_dict(self):
        return { "date": self.date, "note": self.note }
class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.JSON)
    def to_dict(self):
        return { "key": self.key, "value": self.value }
# --- Helper Functions ---
def get_settings_from_db():
    settings_db = Setting.query.all()
    settings = {s.key: s.value for s in settings_db}
    if 'preference_ranks_to_consider' not in settings:
        s = Setting(key='preference_ranks_to_consider', value=10); db.session.add(s)
        settings['preference_ranks_to_consider'] = 10
    if 'default_max_shifts' not in settings:
        s = Setting(key='default_max_shifts', value=2); db.session.add(s)
        settings['default_max_shifts'] = 2
    db.session.commit()
    return settings
def get_on_call_days_pure(year, month, holidays_list):
    holiday_dates = {h['date'] for h in holidays_list}
    days = []
    start_date, end_date = date(year, month, 1), date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)
    d = start_date
    while d < end_date:
        date_str = d.strftime('%Y-%m-%d')
        if d.weekday() >= 5 or date_str in holiday_dates: days.append(date_str)
        d += timedelta(days=1)
    return sorted(list(set(days)))
def _calculate_monthly_priorities_and_save(team, all_engineers_map, month_str):
    monthly_priorities = team.monthlyPriorities or {}
    if month_str not in monthly_priorities:
        sorted_months = sorted([m for m in monthly_priorities.keys() if m < month_str], reverse=True)
        last_month_order = monthly_priorities.get(sorted_months[0]) if sorted_months else None
        base_name_groups = [[name for name in group if name in all_engineers_map and all_engineers_map[name].team_id == team.id] for group in (last_month_order or team.baseGroups or [[]])]
        rotated_name_groups = copy.deepcopy(base_name_groups)
        if rotated_name_groups:
            rotated_name_groups.append(rotated_name_groups.pop(0))
            for group in rotated_name_groups:
                if group: group.append(group.pop(0))
        team.monthlyPriorities = {**monthly_priorities, month_str: rotated_name_groups}
        db.session.commit()
    final_name_groups = team.monthlyPriorities[month_str]
    return [[all_engineers_map[name] for name in group if name in all_engineers_map] for group in final_name_groups]
def _get_day_preferences(month_str):
    year, month = map(int, month_str.split('-'))
    holidays = [h.to_dict() for h in Holiday.query.all()]
    on_call_days = get_on_call_days_pure(year, month, holidays)
    day_preferences = {day: [] for day in on_call_days}
    all_priorities = {}
    all_engineers_map = {eng.name: eng for eng in Engineer.query.all()}
    for team in Team.query.all():
        priority_groups = _calculate_monthly_priorities_and_save(team, all_engineers_map, month_str)
        flat_priority_list = [eng for group in priority_groups for eng in group]
        all_priorities[team.name] = {eng.name: i + 1 for i, eng in enumerate(flat_priority_list)}
    for engineer in all_engineers_map.values():
        prefs = (engineer.preferences or {}).get(month_str, [])
        for i, pref_day in enumerate(prefs):
            if pref_day in day_preferences:
                priority = all_priorities.get(engineer.team.name, {}).get(engineer.name, 999)
                day_preferences[pref_day].append({"name": engineer.name, "team": engineer.team.name, "priority": priority, "rank": i + 1})
    for day in day_preferences: day_preferences[day].sort(key=lambda x: x['priority'])
    return day_preferences
def run_schedule_simulation(month_str, teams_data, engineers_data, holidays_data, temp_engineer_prefs=None):
    year, month = map(int, month_str.split('-'))
    on_call_days = get_on_call_days_pure(year, month, holidays_data)
    on_call_days_map = {day: i for i, day in enumerate(on_call_days)}
    final_assignments = {day: [] for day in on_call_days}
    all_engineers_map = {e['name']: e for e in engineers_data}
    if temp_engineer_prefs:
        eng_name = temp_engineer_prefs['engineer']
        if eng_name in all_engineers_map:
            all_engineers_map[eng_name]['preferences'][month_str] = temp_engineer_prefs['preferences']
            all_engineers_map[eng_name]['maxShifts'] = temp_engineer_prefs['maxShifts']
    for team_dict in teams_data:
        team_name = team_dict['name']
        team_engineers = [e for e in all_engineers_map.values() if e['team'] == team_name]
        if not team_engineers: continue
        monthly_priorities = team_dict.get('monthlyPriorities', {}) or {}
        if month_str not in monthly_priorities:
            sorted_months = sorted([m for m in monthly_priorities.keys() if m < month_str], reverse=True)
            last_month_order = monthly_priorities.get(sorted_months[0]) if sorted_months else None
            base_name_groups = [[name for name in group if name in all_engineers_map and all_engineers_map[name]['team'] == team_dict['name']] for group in (last_month_order or team_dict.get('baseGroups', [[]]))]
            rotated_name_groups = copy.deepcopy(base_name_groups)
            if rotated_name_groups:
                rotated_name_groups.append(rotated_name_groups.pop(0))
                for group in rotated_name_groups:
                    if group: group.append(group.pop(0))
            priority_groups_names = rotated_name_groups
        else:
            priority_groups_names = monthly_priorities[month_str]
        monthly_priority_list = [all_engineers_map[name] for group in priority_groups_names for name in group if name in all_engineers_map]
        shifts_assigned_count = {eng['name']: 0 for eng in team_engineers}
        team_assignments_this_month = {day: [] for day in on_call_days}
        max_shifts_requested = max((eng.get('maxShifts', 0) for eng in team_engineers), default=0)
        shift_overrides = team_dict.get('shift_overrides', {}) or {}
        default_shifts_needed = team_dict.get('shifts_per_day', 1)
        for _ in range(max_shifts_requested):
            for engineer in monthly_priority_list:
                if shifts_assigned_count[engineer['name']] < engineer.get('maxShifts', 0):
                    preferences = (engineer.get('preferences') or {}).get(month_str, [])
                    if not preferences: continue
                    for preferred_day in preferences:
                        shifts_needed_for_this_day = shift_overrides.get(preferred_day, default_shifts_needed)
                        is_slot_available = preferred_day in team_assignments_this_month and len(team_assignments_this_month[preferred_day]) < shifts_needed_for_this_day
                        is_already_assigned = engineer['name'] in team_assignments_this_month[preferred_day]
                        if is_slot_available and not is_already_assigned:
                            if engineer.get('consecutive_pref') == 'avoid':
                                day_index = on_call_days_map.get(preferred_day)
                                is_assigned_adjacent = False
                                if day_index > 0 and engineer['name'] in team_assignments_this_month.get(on_call_days[day_index - 1], []): is_assigned_adjacent = True
                                if not is_assigned_adjacent and day_index < len(on_call_days) - 1 and engineer['name'] in team_assignments_this_month.get(on_call_days[day_index + 1], []): is_assigned_adjacent = True
                                if is_assigned_adjacent: continue
                            team_assignments_this_month[preferred_day].append(engineer['name'])
                            shifts_assigned_count[engineer['name']] += 1
                            break
        for day, names in team_assignments_this_month.items():
            final_assignments.setdefault(day, []).extend(names)
    return final_assignments

# --- API Endpoints ---
@app.route("/api/data", methods=['GET'])
@api_error_handler
def handle_data():
    viewing_month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    teams = Team.query.order_by(Team.name).all()
    if not teams: return jsonify({"groups": [], "assignments": {}, "holidays": [], "dayPreferences": {}, "teamEngineers": [], "allEngineers": [], "selectedTeam": ''})
    team_name = request.args.get('team', teams[0].name)
    current_team = next((t for t in teams if t.name == team_name), teams[0])
    year, month = map(int, viewing_month.split('-'))
    holidays = [h.to_dict() for h in Holiday.query.all()]
    on_call_days = get_on_call_days_pure(year, month, holidays)
    all_assignments = {day: [] for day in on_call_days}
    for team in teams:
        team_assignments = team.assignments or {}
        for day, names in team_assignments.items():
            if day in all_assignments: all_assignments[day].extend(names)
    all_engineers_map = {eng.name: eng for eng in Engineer.query.all()}
    rotated_order_groups = _calculate_monthly_priorities_and_save(current_team, all_engineers_map, viewing_month)
    all_engineers_list = [e.to_dict() for e in Engineer.query.order_by(Engineer.name).all()]
    team_engineers = [e for e in all_engineers_list if e['team'] == current_team.name]
    return jsonify({ "groups": [[e.to_dict() for e in group] for group in rotated_order_groups], "assignments": all_assignments, "holidays": holidays, "dayPreferences": _get_day_preferences(viewing_month), "teamEngineers": team_engineers, "allEngineers": all_engineers_list, "selectedTeam": current_team.name })

@app.route("/api/generate-schedule", methods=['POST'])
@api_error_handler
def generate_schedule():
    month_str = request.get_json().get('month')
    teams_data = [t.to_dict() for t in Team.query.all()]
    engineers_data = [e.to_dict() for e in Engineer.query.all()]
    holidays_data = [h.to_dict() for h in Holiday.query.all()]
    new_assignments_by_day = run_schedule_simulation(month_str, teams_data, engineers_data, holidays_data)
    for team in Team.query.all():
        team_assignments = team.assignments or {}
        for day in list(team_assignments.keys()):
            if day.startswith(month_str): del team_assignments[day]
        team_engineers = {e.name for e in team.engineers}
        for day, names in new_assignments_by_day.items():
            if day.startswith(month_str):
                team_specific_names = [name for name in names if name in team_engineers]
                if team_specific_names: team_assignments[day] = team_specific_names
        team.assignments = {**team_assignments}
    db.session.commit()
    return jsonify({"message": f"Schedule for {month_str} generated successfully."})

@app.route("/api/analyze-chances", methods=['POST'])
@api_error_handler
def analyze_chances():
    payload = request.get_json()
    month_str, eng_name = payload.get('month'), payload.get('engineer')
    if not all([month_str, eng_name]): return jsonify({"error": "Missing data for analysis."}), 400
    teams_data = [t.to_dict() for t in Team.query.all()]
    engineers_data = [e.to_dict() for e in Engineer.query.all()]
    holidays_data = [h.to_dict() for h in Holiday.query.all()]
    temp_prefs = { 'engineer': eng_name, 'preferences': payload.get('preferences', []), 'maxShifts': payload.get('maxShifts', 2) }
    simulated_assignments = run_schedule_simulation(month_str, teams_data, engineers_data, holidays_data, temp_engineer_prefs=temp_prefs)
    assigned_shifts = [day for day, names in simulated_assignments.items() if eng_name in names]
    return jsonify({"assigned_shifts": sorted(assigned_shifts)})

@app.route("/api/preferences", methods=['POST'])
@api_error_handler
def handle_preferences():
    payload = request.get_json();
    if not all(k in payload for k in ['engineer', 'month', 'preferences', 'maxShifts', 'consecutivePref']): return jsonify({"error": "Invalid preference data."}), 400
    eng = Engineer.query.filter_by(name=payload.get('engineer')).first()
    if eng:
        eng.preferences = {**(eng.preferences or {}), payload.get('month'): payload.get('preferences')}
        eng.maxShifts = int(payload.get('maxShifts'))
        eng.consecutive_pref = payload.get('consecutivePref')
        db.session.commit()
        return jsonify({"message": "Preferences saved."})
    return jsonify({"error": "Engineer not found"}), 404

@app.route("/api/holidays", methods=['GET', 'POST'])
@api_error_handler
def handle_holidays():
    if request.method == 'GET': return jsonify([h.to_dict() for h in Holiday.query.all()])
    holidays_data = request.get_json().get('holidays', [])
    if not isinstance(holidays_data, list): return jsonify({"error": "Invalid data format."}), 400
    Holiday.query.delete()
    for h_data in holidays_data: db.session.add(Holiday(date=h_data['date'], note=h_data.get('note', '')))
    db.session.commit()
    return jsonify({"message": "Holidays updated."})

@app.route("/api/settings", methods=['GET', 'POST'])
@api_error_handler
def handle_settings():
    if request.method == 'GET':
        settings = get_settings_from_db()
        settings['shifts_per_day'] = {t.name: t.shifts_per_day for t in Team.query.all()}
        return jsonify(settings)
    payload = request.get_json()
    Setting.query.filter_by(key='preference_ranks_to_consider').first().value = payload.get('preference_ranks_to_consider')
    Setting.query.filter_by(key='default_max_shifts').first().value = payload.get('default_max_shifts')
    for team_name, shifts in payload.get('shifts_per_day', {}).items():
        team = Team.query.filter_by(name=team_name).first()
        if team: team.shifts_per_day = shifts
    db.session.commit()
    return jsonify({"message": "Settings updated successfully."})

@app.route("/api/engineers", methods=['GET', 'POST'])
@api_error_handler
def handle_engineers():
    if request.method == 'GET': return jsonify([e.to_dict() for e in Engineer.query.order_by(Engineer.name).all()])
    payload = request.get_json()
    name, team_name, email = payload.get('name'), payload.get('team'), payload.get('email')
    if not all([name, team_name, email]): return jsonify({"error": "Name, team, and email are mandatory fields."}), 400
    if not re.match(EMAIL_REGEX, email): return jsonify({"error": "Invalid email format."}), 400
    if len(name) > 12: return jsonify({"error": "Engineer name cannot exceed 12 characters."}), 400
    if Engineer.query.filter(db.func.lower(Engineer.name) == name.lower()).first(): return jsonify({"error": "Engineer with that name already exists (case-insensitive)."}), 409
    team = Team.query.filter_by(name=team_name).first()
    if not team: return jsonify({"error": f"Team '{team_name}' does not exist."}), 400
    settings = get_settings_from_db()
    new_engineer = Engineer(name=name, team_id=team.id, email=email, maxShifts=settings['default_max_shifts'])
    db.session.add(new_engineer)
    base_groups = team.baseGroups or [[]]
    if not base_groups or not base_groups[0]: base_groups = [[]]
    smallest_group = min(base_groups, key=len)
    smallest_group.append(name)
    team.baseGroups, team.monthlyPriorities = copy.deepcopy(base_groups), {}
    db.session.commit()
    return jsonify({"message": f"Engineer {name} added to {team_name}."})

@app.route("/api/teams", methods=['GET', 'POST'])
@api_error_handler
def handle_teams():
    if request.method == 'GET': return jsonify([t.name for t in Team.query.order_by(Team.name).all()])
    payload = request.get_json()
    team_name = payload.get('name')
    if not team_name: return jsonify({"error": "Team name is required."}), 400
    if len(team_name) > 8: return jsonify({"error": "Team name cannot exceed 8 characters."}), 400
    if Team.query.filter(db.func.lower(Team.name) == team_name.lower()).first(): return jsonify({"error": f"Team '{team_name}' already exists (case-insensitive)."}), 409
    new_team = Team(name=team_name, shifts_per_day=1)
    db.session.add(new_team)
    db.session.commit()
    return jsonify({"message": f"Team '{team_name}' created successfully."})

@app.route("/api/teams/<string:team_name>", methods=['DELETE'])
@api_error_handler
def delete_team(team_name):
    team = Team.query.filter_by(name=team_name).first()
    if not team: return jsonify({"error": "Team not found."}), 404
    Engineer.query.filter_by(team_id=team.id).delete()
    db.session.delete(team)
    db.session.commit()
    return jsonify({"message": f"Team {team_name} and all its engineers have been deleted."})

@app.route("/api/rebalance-teams", methods=['POST'])
@api_error_handler
def rebalance_teams():
    payload = request.get_json()
    team_name, group_size, seed = payload.get('team'), int(payload.get('groupSize', 5)), payload.get('seed')
    team = Team.query.filter_by(name=team_name).first()
    if not team: return jsonify({"error": "Valid team is required."}), 400
    team_engineers = [e.name for e in team.engineers]
    if seed: random.seed(seed)
    random.shuffle(team_engineers)
    num_groups = math.ceil(len(team_engineers) / group_size) if group_size > 0 else 1
    if num_groups == 0 or not team_engineers: new_groups = [[]]
    else:
        new_groups = [[] for _ in range(num_groups)]
        for i, engineer_name in enumerate(team_engineers): new_groups[i % num_groups].append(engineer_name)
    team.baseGroups = new_groups
    team.monthlyPriorities = {}
    db.session.commit()
    return jsonify({"message": f"Team {team_name} has been re-balanced into {num_groups} groups."})

@app.route("/api/shift-overrides", methods=['GET', 'POST'])
@api_error_handler
def handle_shift_overrides():
    team_name = request.args.get('team')
    team = Team.query.filter_by(name=team_name).first()
    if not team: return jsonify({"error": "Team not found"}), 404
    if request.method == 'GET': return jsonify(team.shift_overrides or {})
    overrides = request.get_json()
    current_overrides = team.shift_overrides or {}
    for day, count in overrides.items():
        if count is not None and count != '':
            current_overrides[day] = int(count)
        elif day in current_overrides:
            del current_overrides[day]
    team.shift_overrides = {**current_overrides}
    db.session.commit()
    return jsonify({"message": "Shift overrides updated successfully."})

@app.route("/api/on-call-days", methods=['GET'])
@api_error_handler
def get_on_call_days_api():
    year = int(request.args.get('year'))
    month = int(request.args.get('month'))
    holidays = [h.to_dict() for h in Holiday.query.all()]
    return jsonify(get_on_call_days_pure(year, month, holidays))

@app.route('/api/backup', methods=['GET'])
@api_error_handler
def backup_data():
    settings = get_settings_from_db()
    data = { "teams": {t.name: t.to_dict() for t in Team.query.all()}, "engineers": {e.name: e.to_dict() for e in Engineer.query.all()}, "holidays": [h.to_dict() for h in Holiday.query.all()], "settings": settings }
    mem_file = io.BytesIO(json.dumps(data, indent=4).encode('utf-8'))
    mem_file.seek(0)
    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    filename = f"scheduler_backup_{timestamp}.json"
    return send_file(mem_file, as_attachment=True, download_name=filename, mimetype='application/json')

@app.route("/api/reset-schedule", methods=['POST'])
@api_error_handler
def reset_schedule():
    month_str = request.get_json().get('month')
    if not month_str: return jsonify({"error": "Month is required"}), 400
    for team in Team.query.all():
        current_assignments = team.assignments or {}
        assignments_to_keep = {day: names for day, names in current_assignments.items() if not day.startswith(month_str)}
        team.assignments = assignments_to_keep
    db.session.commit()
    return jsonify({"message": "Schedule reset."})

@app.route("/api/engineers/<string:name>", methods=['DELETE'])
@api_error_handler
def delete_engineer(name):
    eng = Engineer.query.filter_by(name=name).first()
    if not eng: return jsonify({"error": "Engineer not found"}), 404
    team = eng.team
    db.session.delete(eng)
    db.session.commit()
    new_base_groups = [[n for n in g if n != name] for g in (team.baseGroups or [[]])]
    team.baseGroups = new_base_groups
    team.monthlyPriorities = {}
    db.session.commit()
    return jsonify({"message": f"Engineer {name} deleted."})

@app.route("/api/bulk-actions", methods=['POST'])
@api_error_handler
def bulk_actions():
    payload = request.get_json()
    action, value = payload.get('action'), payload.get('value')
    if action == 'apply_default_max_shifts':
        new_max_shifts = int(value)
        if new_max_shifts >= 0:
            Engineer.query.update({Engineer.maxShifts: new_max_shifts})
            db.session.commit()
            return jsonify({"message": f"All engineers updated to {new_max_shifts} max shifts."})
        return jsonify({"error": "Invalid value for max shifts."}), 400
    return jsonify({"error": "Unknown bulk action."}), 400

@app.route("/api/manage-shift", methods=['POST'])
@api_error_handler
def manage_shift():
    """Handles a manual shift swap between two engineers."""
    payload = request.get_json()
    shift_date, original_engineer_name, team_name, target_engineer_name = payload.get('date'), payload.get('originalEngineer'), payload.get('team'), payload.get('targetEngineer')
    if not all([shift_date, original_engineer_name, team_name, target_engineer_name]): return jsonify({"error": "Missing required fields"}), 400
    
    team = Team.query.filter_by(name=team_name).first()
    if not team: return jsonify({"error": "Team not found"}), 404
    
    team_assignments = team.assignments or {}
    if shift_date not in team_assignments or original_engineer_name not in team_assignments.get(shift_date, []):
        return jsonify({"error": "Assignment not found"}), 404
    
    try:
        index = team_assignments[shift_date].index(original_engineer_name)
        team_assignments[shift_date][index] = target_engineer_name
        flag_modified(team, "assignments") # Explicitly flag the JSON field for change
        db.session.commit()
        return jsonify({"message": "Shift swapped successfully."})
    except ValueError:
        return jsonify({"error": "Original engineer not found in that shift"}), 404

@app.route("/api/admin-dashboard", methods=['GET'])
@api_error_handler
def admin_dashboard():
    month_str = request.args.get('month', datetime.now().strftime('%Y-%m'))
    teams = Team.query.order_by(Team.name).all()
    if not teams: return jsonify({"noPreferences": [], "shiftDiscrepancies": [], "preferenceReports": [], "understaffedShifts": []})
    team_name = request.args.get('team', teams[0].name)
    current_team = next((t for t in teams if t.name == team_name), teams[0])
    year, month = map(int, month_str.split('-'))
    team_engineers = current_team.engineers.all()
    no_prefs = [{"name": e.name} for e in team_engineers if not (e.preferences or {}).get(month_str)]
    discrepancies, understaffed_shifts = [], []
    shifts_this_month = {e.name: 0 for e in team_engineers}
    team_assignments = current_team.assignments or {}
    holidays = [h.to_dict() for h in Holiday.query.all()]
    on_call_days_for_month = get_on_call_days_pure(year, month, holidays)
    for day in on_call_days_for_month:
        assigned_count = len(team_assignments.get(day, []))
        required_count = (current_team.shift_overrides or {}).get(day, current_team.shifts_per_day)
        if assigned_count < required_count:
            understaffed_shifts.append({"date": day, "assigned": assigned_count, "required": required_count})
        for name in team_assignments.get(day, []):
            if name in shifts_this_month: shifts_this_month[name] += 1
    for eng in team_engineers:
        requested, actual = eng.maxShifts, shifts_this_month.get(eng.name, 0)
        if actual != requested:
            discrepancies.append({"name": eng.name, "requested": requested, "actual": actual})
    preference_reports = []
    start_date = date(year, month, 1)
    for i in range(3):
        target_year = start_date.year + (start_date.month + i - 1) // 12
        target_month_num = (start_date.month + i - 1) % 12 + 1
        target_date = date(target_year, target_month_num, 1)
        target_month_str = target_date.strftime('%Y-%m')
        report = {"month": target_month_str, "onCallDays": get_on_call_days_pure(target_date.year, target_date.month, holidays), "teamPreferences": {}}
        for team in teams:
            team_prefs = []
            for e in team.engineers.order_by(Engineer.name).all():
                eng_dict = e.to_dict()
                eng_dict['preferences'] = (eng_dict.get('preferences') or {}).get(target_month_str, [])
                team_prefs.append(eng_dict)
            report["teamPreferences"][team.name] = team_prefs
        preference_reports.append(report)
    return jsonify({ "noPreferences": sorted(no_prefs, key=lambda x: x['name']), "shiftDiscrepancies": sorted(discrepancies, key=lambda x: x['name']), "understaffedShifts": sorted(understaffed_shifts, key=lambda x: x['date']), "preferenceReports": preference_reports })
    
# --- HTML Rendering ---
@app.route("/admin")
def admin_page(): return render_template('admin.html')
@app.route("/")
def home(): return render_template('scheduler.html')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)