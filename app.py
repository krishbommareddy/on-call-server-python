# app.py

import json
import logging
from datetime import datetime, date, timedelta
import copy
import random
from functools import wraps
from flask import Flask, jsonify, request, render_template, send_file
from flask_cors import CORS
import io
import math
import re

app = Flask(__name__)
CORS(app)

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')

# --- Constants ---
DATA_FILE = 'schedule_data.json'
EMAIL_REGEX = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'

# --- Decorator for Error Handling ---
def api_error_handler(f):
    """A decorator to wrap all API endpoints with a try-except block."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logging.error(f"An error occurred in endpoint '{f.__name__}': {e}", exc_info=True)
            return jsonify({"error": "An unexpected server error occurred."}), 500
    return decorated_function

# --- Data Handling Functions ---
def load_data():
    """Loads the main data file and creates a default structure if it doesn't exist."""
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            if 'settings' not in data: data['settings'] = get_default_settings()
            if 'engineers' not in data: data['engineers'] = {}
            if 'teams' not in data: data['teams'] = {}
            if 'holidays' not in data: data['holidays'] = []
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return { "settings": get_default_settings(), "teams": {}, "engineers": {}, "holidays": [] }

def get_default_settings():
    """Returns the default application settings."""
    return { "shifts_per_day": {}, "preference_ranks_to_consider": 10, "default_max_shifts": 2 }

def save_data(data):
    """Saves the provided data dictionary to the JSON file."""
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def get_engineers_by_team(all_engineers, team_name):
    """Filters a dictionary of all engineers for a specific team."""
    return [eng for eng in all_engineers.values() if eng.get('team') == team_name]

def get_on_call_days(year, month, holidays):
    """Calculates all weekends and specified holidays for a given month and year."""
    days, holiday_dates = [], set()
    if holidays and isinstance(holidays[0], dict):
        holiday_dates = {h['date'] for h in holidays}
    elif holidays:
        holiday_dates = set(holidays)
    start_date, end_date = date(year, month, 1), date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)
    d = start_date
    while d < end_date:
        date_str = d.strftime('%Y-%m-%d')
        if d.weekday() >= 5 or date_str in holiday_dates: days.append(date_str)
        d += timedelta(days=1)
    return sorted(list(set(days)))

# --- Helper Functions ---
def _calculate_monthly_priorities(data, team_name, month_str):
    """Calculates the rotated priority order of engineers for a given team and month."""
    team_data = data.get('teams', {}).get(team_name)
    if not team_data: return [] 
    all_engineers = data.get('engineers', {})
    if month_str not in team_data.get('monthlyPriorities', {}):
        sorted_months = sorted([m for m in team_data.get('monthlyPriorities', {}).keys() if m < month_str], reverse=True)
        last_month_order = team_data['monthlyPriorities'].get(sorted_months[0]) if sorted_months else None
        base_name_groups = [[name for name in group if name in all_engineers and all_engineers.get(name, {}).get('team') == team_name] for group in (last_month_order or team_data.get('baseGroups', [[]]))]
        rotated_name_groups = copy.deepcopy(base_name_groups)
        if rotated_name_groups:
            rotated_name_groups.append(rotated_name_groups.pop(0))
            for group in rotated_name_groups:
                if group: group.append(group.pop(0))
        team_data.setdefault('monthlyPriorities', {})[month_str] = rotated_name_groups
        save_data(data)
    final_name_groups = team_data['monthlyPriorities'][month_str]
    return [[all_engineers[name] for name in group if name in all_engineers] for group in final_name_groups]

def _get_day_preferences(data, month_str):
    """Gathers all preferences for each on-call day for the tooltip."""
    year, month = map(int, month_str.split('-'))
    on_call_days = get_on_call_days(year, month, data.get('holidays', []))
    day_preferences = {day: [] for day in on_call_days}
    all_priorities = {}
    for team_name in data.get('teams', {}):
        priority_groups = _calculate_monthly_priorities(data, team_name, month_str)
        flat_priority_list = [eng for group in priority_groups for eng in group]
        all_priorities[team_name] = {eng['name']: i + 1 for i, eng in enumerate(flat_priority_list)}
    for engineer in data.get('engineers', {}).values():
        prefs = engineer.get('preferences', {}).get(month_str, [])
        team = engineer.get('team')
        for i, pref_day in enumerate(prefs):
            if pref_day in day_preferences:
                priority = all_priorities.get(team, {}).get(engineer['name'], 999)
                day_preferences[pref_day].append({"name": engineer['name'], "team": team, "priority": priority, "rank": i + 1})
    for day in day_preferences: day_preferences[day].sort(key=lambda x: x['priority'])
    return day_preferences

def run_schedule_simulation(data, month_str):
    """A pure function that runs the scheduling algorithm without saving results."""
    settings = data['settings']
    year, month = map(int, month_str.split('-'))
    on_call_days = get_on_call_days(year, month, data.get('holidays', []))
    on_call_days_map = {day: i for i, day in enumerate(on_call_days)}
    final_assignments = {}
    for team_name in data['teams']:
        shifts_needed_per_day = settings['shifts_per_day'].get(team_name, 1)
        monthly_priority_groups = _calculate_monthly_priorities(data, team_name, month_str)
        monthly_priority_list = [eng for group in monthly_priority_groups for eng in group]
        if not monthly_priority_list: continue
        shifts_assigned_count = {eng['name']: 0 for eng in monthly_priority_list}
        assignments = {day: [] for day in on_call_days}
        max_shifts_requested = max((eng.get('maxShifts', 0) for eng in monthly_priority_list), default=0)
        for _ in range(max_shifts_requested):
            for engineer in monthly_priority_list:
                if shifts_assigned_count[engineer['name']] < engineer.get('maxShifts', 0):
                    preferences = engineer.get('preferences', {}).get(month_str, [])
                    if not preferences: continue
                    for preferred_day in preferences:
                        is_slot_available = preferred_day in assignments and len(assignments[preferred_day]) < shifts_needed_per_day
                        is_already_assigned = engineer['name'] in assignments[preferred_day]
                        if is_slot_available and not is_already_assigned:
                            consecutive_pref = engineer.get('consecutive_pref', 'neutral')
                            if consecutive_pref == 'avoid':
                                day_index = on_call_days_map.get(preferred_day)
                                is_assigned_adjacent = False
                                if day_index > 0 and engineer['name'] in assignments.get(on_call_days[day_index - 1], []): is_assigned_adjacent = True
                                if not is_assigned_adjacent and day_index < len(on_call_days) - 1 and engineer['name'] in assignments.get(on_call_days[day_index + 1], []): is_assigned_adjacent = True
                                if is_assigned_adjacent: continue
                            assignments[preferred_day].append(engineer['name'])
                            shifts_assigned_count[engineer['name']] += 1
                            break 
        for day, names in assignments.items():
            final_assignments.setdefault(day, []).extend(names)
    return final_assignments

# --- API Endpoints ---
@app.route("/api/data", methods=['GET'])
@api_error_handler
def handle_data():
    """Provides all data needed to render the main scheduler page."""
    viewing_month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    data = load_data()
    available_teams = list(data.get('teams', {}).keys())
    team_name = request.args.get('team', available_teams[0] if available_teams else '')
    if not team_name or team_name not in data.get('teams', {}): return jsonify({"groups": [], "assignments": {}, "holidays": [], "dayPreferences": {}, "teamEngineers": [], "allEngineers": [], "selectedTeam": ''})
    
    # FIX: Initialize assignments with all on-call days to prevent KeyErrors
    year, month = map(int, viewing_month.split('-'))
    on_call_days = get_on_call_days(year, month, data.get('holidays', []))
    all_assignments = {day: [] for day in on_call_days}

    # Populate with saved assignments
    for t_data in data.get('teams', {}).values():
        for day, names in t_data.get('assignments', {}).items():
            if day in all_assignments:
                all_assignments[day].extend(names)

    rotated_order_groups = _calculate_monthly_priorities(data, team_name, viewing_month)
    all_engineers_list = sorted(data.get('engineers', {}).values(), key=lambda x: x['name'])
    team_engineers = [eng for eng in all_engineers_list if eng['team'] == team_name]
    return jsonify({ "groups": rotated_order_groups, "assignments": all_assignments, "holidays": data.get('holidays', []), "dayPreferences": _get_day_preferences(data, viewing_month), "teamEngineers": team_engineers, "allEngineers": all_engineers_list, "selectedTeam": team_name })

@app.route("/api/generate-schedule", methods=['POST'])
@api_error_handler
def generate_schedule():
    """Generates the schedule for a given month and saves the result."""
    data = load_data()
    month_str = request.get_json().get('month')
    new_assignments_by_day = run_schedule_simulation(data, month_str)
    for team_name, team_data in data['teams'].items():
        team_data['assignments'] = {d: v for d, v in team_data.get('assignments', {}).items() if not d.startswith(month_str)}
        team_assignments = {day: [] for day in new_assignments_by_day}
        team_engineers = {eng['name'] for eng in get_engineers_by_team(data['engineers'], team_name)}
        for day, names in new_assignments_by_day.items():
            team_assignments[day] = [name for name in names if name in team_engineers]
        team_data['assignments'].update(team_assignments)
    save_data(data)
    return jsonify({"message": f"Schedule for {month_str} generated successfully."})

@app.route("/api/analyze-chances", methods=['POST'])
@api_error_handler
def analyze_chances():
    """A read-only endpoint to simulate the schedule with a user's tentative preferences."""
    data = copy.deepcopy(load_data())
    payload = request.get_json()
    month_str, eng_name, tentative_preferences = payload.get('month'), payload.get('engineer'), payload.get('preferences')
    if not (month_str and eng_name and tentative_preferences is not None): return jsonify({"error": "Missing data for analysis."}), 400
    if eng_name in data['engineers']:
        data['engineers'][eng_name].setdefault('preferences', {})[month_str] = tentative_preferences
    else: return jsonify({"error": "Engineer not found."}), 404
    simulated_assignments = run_schedule_simulation(data, month_str)
    assigned_shifts = [day for day, names in simulated_assignments.items() if eng_name in names]
    return jsonify({"assigned_shifts": sorted(assigned_shifts)})

@app.route("/api/preferences", methods=['POST'])
@api_error_handler
def handle_preferences():
    """Saves an engineer's preferences, including max shifts and consecutive preference."""
    data = load_data()
    payload = request.get_json()
    if not all(k in payload for k in ['engineer', 'month', 'preferences', 'maxShifts', 'consecutivePref']):
        return jsonify({"error": "Invalid preference data submitted."}), 400
    eng_name = payload.get('engineer')
    if eng_name in data['engineers']:
        eng = data['engineers'][eng_name]
        eng.setdefault('preferences', {})[payload.get('month')] = payload.get('preferences')
        eng['maxShifts'] = int(payload.get('maxShifts'))
        eng['consecutive_pref'] = payload.get('consecutivePref')
        save_data(data)
        return jsonify({"message": "Preferences saved."})
    return jsonify({"error": "Engineer not found"}), 404

@app.route("/api/holidays", methods=['GET', 'POST'])
@api_error_handler
def handle_holidays():
    """Gets or updates the list of holidays."""
    data = load_data()
    if request.method == 'GET': return jsonify(data.get('holidays', []))
    holidays_data = request.get_json().get('holidays', [])
    if isinstance(holidays_data, list):
        data['holidays'] = holidays_data
        save_data(data)
        return jsonify({"message": "Holidays updated."})
    return jsonify({"error": "Invalid data format for holidays."}), 400

@app.route("/api/manage-shift", methods=['POST'])
@api_error_handler
def manage_shift():
    """Handles a manual shift swap between two engineers."""
    data = load_data()
    payload = request.get_json()
    shift_date, original_engineer, team_name, target_engineer = payload.get('date'), payload.get('originalEngineer'), payload.get('team'), payload.get('targetEngineer')
    if not all([shift_date, original_engineer, team_name, target_engineer]): return jsonify({"error": "Missing required fields"}), 400
    team_assignments = data['teams'][team_name]['assignments']
    if shift_date not in team_assignments or original_engineer not in team_assignments.get(shift_date, []): return jsonify({"error": "Assignment not found"}), 404
    try:
        index = team_assignments[shift_date].index(original_engineer)
        team_assignments[shift_date][index] = target_engineer
    except ValueError: return jsonify({"error": "Original engineer not found"}), 404
    save_data(data)
    return jsonify({"message": "Shift swapped successfully."})

@app.route("/api/settings", methods=['GET', 'POST'])
@api_error_handler
def handle_settings():
    """Gets or updates the global application settings."""
    data = load_data()
    if request.method == 'GET': return jsonify(data.get('settings', get_default_settings()))
    new_settings = request.get_json()
    if not isinstance(new_settings.get('shifts_per_day'), dict) or \
       not isinstance(new_settings.get('preference_ranks_to_consider'), int) or \
       not isinstance(new_settings.get('default_max_shifts'), int):
        return jsonify({"error": "Invalid settings format."}), 400
    data['settings'] = new_settings
    save_data(data)
    return jsonify({"message": "Settings updated successfully."})

@app.route("/api/engineers", methods=['GET', 'POST'])
@api_error_handler
def handle_engineers():
    """Gets the list of all engineers, or adds a new one with validation."""
    data = load_data()
    if request.method == 'GET': return jsonify(sorted(data.get('engineers', {}).values(), key=lambda x: x['name']))
    payload = request.get_json()
    name, team, email = payload.get('name'), payload.get('team'), payload.get('email')
    if not all([name, team, email]): return jsonify({"error": "Name, team, and email are mandatory fields."}), 400
    if not re.match(EMAIL_REGEX, email): return jsonify({"error": "Invalid email format."}), 400
    if len(name) > 12: return jsonify({"error": "Engineer name cannot exceed 12 characters."}), 400
    if team not in data['teams']: return jsonify({"error": f"Team '{team}' does not exist."}), 400
    existing_names_lower = {n.lower() for n in data['engineers'].keys()}
    if name.lower() in existing_names_lower: return jsonify({"error": "Engineer with that name already exists (case-insensitive)."}), 409
    data['engineers'][name] = { "name": name, "team": team, "email": email, "maxShifts": data['settings']['default_max_shifts'], "preferences": {}, "consecutive_pref": "neutral" }
    team_groups = data['teams'][team]['baseGroups']
    if not team_groups: team_groups.append([])
    smallest_group = min(team_groups, key=len)
    smallest_group.append(name)
    data['teams'][team]['monthlyPriorities'] = {}
    save_data(data)
    return jsonify({"message": f"Engineer {name} added to {team}."})

@app.route("/api/engineers/<string:name>", methods=['DELETE'])
@api_error_handler
def delete_engineer(name):
    """Deletes an engineer from the system."""
    data = load_data()
    if name not in data.get('engineers', {}): return jsonify({"error": "Engineer not found"}), 404
    team = data['engineers'][name].get('team')
    del data['engineers'][name]
    if team and team in data['teams']:
        data['teams'][team]['baseGroups'] = [[eng_name for eng_name in g if eng_name != name] for g in data['teams'][team]['baseGroups']]
        data['teams'][team]['monthlyPriorities'] = {}
    for t_data in data['teams'].values():
        for day in list(t_data.get('assignments', {})):
            t_data['assignments'][day] = [n for n in t_data['assignments'][day] if n != name]
    save_data(data)
    return jsonify({"message": f"Engineer {name} deleted."})

@app.route("/api/teams", methods=['GET', 'POST'])
@api_error_handler
def handle_teams():
    """Gets a list of all team names, or creates a new team."""
    data = load_data()
    if request.method == 'GET':
        return jsonify(sorted(list(data.get('teams', {}).keys())))
    payload = request.get_json()
    team_name = payload.get('name')
    if not team_name: return jsonify({"error": "Team name is required."}), 400
    if len(team_name) > 8: return jsonify({"error": "Team name cannot exceed 8 characters."}), 400
    existing_teams_lower = {t.lower() for t in data['teams'].keys()}
    if team_name.lower() in existing_teams_lower:
        return jsonify({"error": f"Team '{team_name}' already exists (case-insensitive)."}), 409
    data['teams'][team_name] = {"baseGroups": [[]], "monthlyPriorities": {}, "assignments": {}}
    data['settings']['shifts_per_day'][team_name] = 1
    save_data(data)
    return jsonify({"message": f"Team '{team_name}' created successfully."})

@app.route("/api/teams/<string:team_name>", methods=['DELETE'])
@api_error_handler
def delete_team(team_name):
    """Deletes a team and all engineers associated with it."""
    data = load_data()
    if team_name not in data.get('teams', {}): return jsonify({"error": "Team not found."}), 404
    engineers_to_delete = [name for name, eng in data['engineers'].items() if eng['team'] == team_name]
    for name in engineers_to_delete: del data['engineers'][name]
    del data['teams'][team_name]
    if team_name in data['settings']['shifts_per_day']: del data['settings']['shifts_per_day'][team_name]
    save_data(data)
    return jsonify({"message": f"Team {team_name} and all its engineers have been deleted."})

@app.route("/api/rebalance-teams", methods=['POST'])
@api_error_handler
def rebalance_teams():
    """Re-distributes all engineers on a team into new, balanced groups."""
    data = load_data()
    payload = request.get_json()
    team_name, group_size, seed = payload.get('team'), int(payload.get('groupSize', 5)), payload.get('seed')
    if not team_name or team_name not in data['teams']: return jsonify({"error": "Valid team is required."}), 400
    team_engineers = [name for name, eng in data['engineers'].items() if eng['team'] == team_name]
    if seed: random.seed(seed)
    random.shuffle(team_engineers)
    num_groups = math.ceil(len(team_engineers) / group_size) if group_size > 0 else 1
    if num_groups == 0 or not team_engineers: new_groups = [[]]
    else:
        new_groups = [[] for _ in range(num_groups)]
        for i, engineer_name in enumerate(team_engineers): new_groups[i % num_groups].append(engineer_name)
    data['teams'][team_name]['baseGroups'] = new_groups
    data['teams'][team_name]['monthlyPriorities'] = {}
    save_data(data)
    return jsonify({"message": f"Team {team_name} has been re-balanced into {num_groups} groups."})

@app.route("/api/bulk-actions", methods=['POST'])
@api_error_handler
def bulk_actions():
    """Performs a bulk action, e.g., updating max shifts for all engineers."""
    data = load_data()
    payload = request.get_json()
    action, value = payload.get('action'), payload.get('value')
    if action == 'apply_default_max_shifts':
        new_max_shifts = int(value)
        if new_max_shifts >= 0:
            for eng_data in data.get('engineers', {}).values(): eng_data['maxShifts'] = new_max_shifts
            save_data(data)
            return jsonify({"message": f"All engineers updated to {new_max_shifts} max shifts."})
        return jsonify({"error": "Invalid value for max shifts."}), 400
    return jsonify({"error": "Unknown bulk action."}), 400

@app.route("/api/admin-dashboard", methods=['GET'])
@api_error_handler
def admin_dashboard():
    """Endpoint for the admin dashboard. Provides summary reports."""
    data = load_data()
    month_str = request.args.get('month', datetime.now().strftime('%Y-%m'))
    available_teams = list(data.get('teams', {}).keys())
    team_name = request.args.get('team', available_teams[0] if available_teams else '')
    if not team_name: return jsonify({"noPreferences": [], "shiftDiscrepancies": [], "allTeamPreferences": {}, "onCallDays": []})
    all_engineers_map = data.get('engineers', {})
    team_engineers = get_engineers_by_team(all_engineers_map, team_name)
    no_prefs = [{"name": e['name']} for e in team_engineers if not e.get('preferences', {}).get(month_str)]
    discrepancies, shifts_this_month = [], {e['name']: 0 for e in team_engineers}
    team_assignments = data.get('teams', {}).get(team_name, {}).get('assignments', {})
    for day, names in team_assignments.items():
        if day.startswith(month_str):
            for name in names:
                if name in shifts_this_month: shifts_this_month[name] += 1
    for eng in team_engineers:
        requested, actual = eng.get('maxShifts', 2), shifts_this_month.get(eng['name'], 0)
        if actual != requested:
            discrepancies.append({"name": eng['name'], "requested": requested, "actual": actual})
    all_team_preferences = {}
    for t_name in data.get('teams', {}):
        engineers_in_team = get_engineers_by_team(all_engineers_map, t_name)
        if not engineers_in_team: continue
        prefs = [{"name": e['name'], "maxShifts": e.get('maxShifts', 2), "preferences": e.get('preferences', {}).get(month_str, [])} for e in engineers_in_team]
        all_team_preferences[t_name] = sorted(prefs, key=lambda x: x['name'])
    holidays = data.get('holidays', [])
    year, month = map(int, month_str.split('-'))
    on_call_days_for_month = get_on_call_days(year, month, holidays)
    return jsonify({ "noPreferences": sorted(no_prefs, key=lambda x: x['name']), "shiftDiscrepancies": sorted(discrepancies, key=lambda x: x['name']), "allTeamPreferences": all_team_preferences, "onCallDays": on_call_days_for_month })

@app.route("/api/reset-schedule", methods=['POST'])
@api_error_handler
def reset_schedule():
    """Resets all assignments for a given month."""
    data = load_data()
    month_str = request.get_json().get('month')
    if not month_str: return jsonify({"error": "Month is required"}), 400
    for team_data in data['teams'].values():
        team_data['assignments'] = { d: v for d, v in team_data.get('assignments', {}).items() if not d.startswith(month_str) }
    save_data(data)
    return jsonify({"message": "Schedule reset."})

@app.route('/api/backup', methods=['GET'])
@api_error_handler
def backup_data():
    """Provides the current data file as a downloadable backup."""
    data = load_data()
    mem_file = io.BytesIO()
    mem_file.write(json.dumps(data, indent=4).encode('utf-8'))
    mem_file.seek(0)
    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    filename = f"scheduler_backup_{timestamp}.json"
    return send_file(mem_file, as_attachment=True, download_name=filename, mimetype='application/json')

# --- HTML Rendering ---
@app.route("/admin")
def admin_page(): return render_template('admin.html')
@app.route("/")
def home(): return render_template('scheduler.html')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)