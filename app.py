# app.py - Refactored Version

import json
from datetime import datetime, date, timedelta
import copy
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# --- Constants ---
DATA_FILE = 'schedule_data.json'
SHIFTS_PER_DAY = {"DC": 5, "BSN": 1}
PREFERENCE_WEIGHTS = {i: 100 / (i + 1) for i in range(10)}
FAIRNESS_INCREMENT = 1.0
CREDIT_DECAY = 0.95

# --- Data Handling Functions ---
def load_data():
    """Loads data, creating a default structure if the file is missing."""
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Default data structure creation remains the same...
        dc_engineers = [f"DC Engineer {i+1}" for i in range(22)]
        bsn_engineers = [f"BSN Engineer {i+1}" for i in range(1)]
        dc_groups = [
            [{"name": name, "maxShifts": 2, "preferences": {}, "deficit": 0.0} for name in dc_engineers[0:5]],
            [{"name": name, "maxShifts": 2, "preferences": {}, "deficit": 0.0} for name in dc_engineers[5:10]],
            [{"name": name, "maxShifts": 2, "preferences": {}, "deficit": 0.0} for name in dc_engineers[10:14]],
            [{"name": name, "maxShifts": 2, "preferences": {}, "deficit": 0.0} for name in dc_engineers[14:18]],
            [{"name": name, "maxShifts": 2, "preferences": {}, "deficit": 0.0} for name in dc_engineers[18:22]],
        ]
        return { "teams": { "DC": { "baseGroups": dc_groups, "monthlyPriorities": {}, "assignments": {} }, "BSN": { "baseGroups": [[{"name": name, "maxShifts": 2, "preferences": {}, "deficit": 0.0} for name in bsn_engineers]], "monthlyPriorities": {}, "assignments": {} } }, "holidays": [] }

def save_data(data):
    """Saves the data dictionary to the JSON file."""
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def get_all_engineers(team_data):
    """Flattens the group structure to get a simple list of engineers."""
    return [engineer for group in team_data.get('baseGroups', []) for engineer in group]

def get_on_call_days(year, month, holidays):
    """Calculates all on-call days for a given month."""
    days = []
    start_date = date(year, month, 1)
    end_date = date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)
    d = start_date
    while d < end_date:
        date_str = d.strftime('%Y-%m-%d')
        if d.weekday() >= 5 or date_str in holidays:
            days.append(date_str)
        d += timedelta(days=1)
    return sorted(list(set(days)))

# --- Helper Functions for API Logic ---

def _calculate_monthly_priorities(data, team_name, month_str):
    """Calculates and saves monthly priority rotations if they don't exist."""
    team_data = data['teams'][team_name]
    if month_str not in team_data['monthlyPriorities']:
        sorted_months = sorted([m for m in team_data['monthlyPriorities'].keys() if m < month_str], reverse=True)
        base = team_data['monthlyPriorities'].get(sorted_months[0]) if sorted_months else team_data['baseGroups']
        rotated_groups = copy.deepcopy(base)
        if team_name == "DC" and rotated_groups:
            rotated_groups.append(rotated_groups.pop(0))
            for group in rotated_groups:
                if group: group.append(group.pop(0))
        team_data['monthlyPriorities'][month_str] = rotated_groups
        save_data(data)
    return team_data['monthlyPriorities'][month_str]

def _get_day_preferences(data, month_str):
    """Gathers all engineer preferences for each on-call day in a month."""
    year, month = map(int, month_str.split('-'))
    on_call_days = get_on_call_days(year, month, data.get('holidays', []))
    day_preferences = {day: [] for day in on_call_days}

    for t_name, t_data in data['teams'].items():
        for engineer in get_all_engineers(t_data):
            prefs = engineer.get('preferences', {}).get(month_str, [])
            for pref_day in prefs:
                if pref_day in day_preferences:
                    day_preferences[pref_day].append({"name": engineer['name'], "team": t_name})
    return day_preferences

def _select_winners_for_day(all_engineers, shifts_this_month, day, month_str, shifts_needed):
    """Scores candidates and selects winners for a single day's shift."""
    candidates = []
    for eng in all_engineers:
        prefs = eng.get('preferences', {}).get(month_str, [])
        weight = PREFERENCE_WEIGHTS.get(prefs.index(day)) if day in prefs else 0.0
        candidates.append({'engineer': eng, 'score': eng.get('deficit', 0.0) + weight})
    
    primary_pool = [c for c in candidates if shifts_this_month[c['engineer']['name']] < c['engineer']['maxShifts']]
    primary_pool.sort(key=lambda x: x['score'], reverse=True)
    
    winners = [c['engineer'] for c in primary_pool[:shifts_needed]]
    if len(winners) < shifts_needed:
        fallback_pool = sorted(candidates, key=lambda x: x['score'], reverse=True)
        needed = shifts_needed - len(winners)
        existing_names = {w['name'] for w in winners}
        fallback_winners = [c['engineer'] for c in fallback_pool if c['engineer']['name'] not in existing_names][:needed]
        winners.extend(fallback_winners)
    return winners

# --- API Endpoints ---

@app.route("/api/data", methods=['GET'])
def handle_data():
    """Prepares and returns all necessary data for the main scheduler view."""
    viewing_month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    team_name = request.args.get('team', 'DC')
    data = load_data()
    if team_name not in data['teams']: return jsonify({"error": "Team not found"}), 404
    
    team_data = data['teams'][team_name]
    rotated_order_groups = _calculate_monthly_priorities(data, team_name, viewing_month)
    all_engineers_map = {eng['name']: eng for eng in get_all_engineers(team_data)}
    final_rotated_groups = [[all_engineers_map[eng['name']] for eng in group if eng['name'] in all_engineers_map] for group in rotated_order_groups]

    all_assignments = {}
    for t_data in data['teams'].values():
        for day, names in t_data.get('assignments', {}).items():
            all_assignments.setdefault(day, []).extend(names)
            
    return jsonify({
        "groups": final_rotated_groups,
        "assignments": all_assignments,
        "holidays": data.get('holidays', []),
        "dayPreferences": _get_day_preferences(data, viewing_month)
    })

@app.route("/api/generate-schedule", methods=['POST'])
def generate_schedule():
    """Generates and saves the schedule for a given month for all teams."""
    data = load_data()
    month_str = request.get_json().get('month')
    year, month = map(int, month_str.split('-'))
    on_call_days = get_on_call_days(year, month, data.get('holidays', []))

    # Clear existing assignments for the month for all teams
    for team_data in data['teams'].values():
        team_data['assignments'] = {d: v for d, v in team_data.get('assignments', {}).items() if not d.startswith(month_str)}

    for team_name, team_data in data['teams'].items():
        shifts_needed = SHIFTS_PER_DAY.get(team_name, 1)
        all_engineers = get_all_engineers(team_data)
        if not all_engineers: continue
        
        shifts_this_month = {eng['name']: 0 for eng in all_engineers}

        for day in on_call_days:
            winners = _select_winners_for_day(all_engineers, shifts_this_month, day, month_str, shifts_needed)
            team_data['assignments'][day] = [w['name'] for w in winners]
            
            # Update deficits and shift counts
            for eng in all_engineers:
                if eng in winners:
                    prefs = eng.get('preferences', {}).get(month_str, [])
                    eng['deficit'] -= PREFERENCE_WEIGHTS.get(prefs.index(day)) if day in prefs else 0.0
                    shifts_this_month[eng['name']] += 1
                else:
                    eng['deficit'] += FAIRNESS_INCREMENT
        
        # Apply credit decay at the end of the month
        for eng in all_engineers:
            eng['deficit'] = round(eng.get('deficit', 0.0) * CREDIT_DECAY, 4)
            
    save_data(data)
    return jsonify({"message": f"Schedule for {month_str} generated successfully."})

# Other endpoints (holidays, preferences, team, manage-shift, reset, admin-dashboard) remain
# largely the same but could also be refactored if they grew in complexity.
# For now, their current state is clear and concise.
@app.route("/api/holidays", methods=['GET', 'POST'])
def handle_holidays():
    data = load_data()
    if request.method == 'GET': return jsonify(data.get('holidays', []))
    data['holidays'] = request.get_json().get('holidays', [])
    save_data(data)
    return jsonify({"message": "Holidays updated."})

@app.route("/api/preferences", methods=['POST'])
def handle_preferences():
    data = load_data()
    payload = request.get_json()
    month_str, eng_name, team_name = payload.get('month'), payload.get('engineer'), payload.get('team')
    for group in data['teams'][team_name]['baseGroups']:
        for eng in group:
            if eng['name'] == eng_name:
                eng.setdefault('preferences', {})[month_str] = payload.get('preferences')
                eng['maxShifts'] = payload.get('maxShifts')
                save_data(data)
                return jsonify({"message": "Preferences saved."})
    return jsonify({"error": "Engineer not found"}), 404

@app.route("/api/team", methods=['POST'])
def manage_team():
    data = load_data()
    payload = request.get_json()
    action, name, team_name = payload.get('action'), payload.get('name'), payload.get('team')
    team_data = data['teams'][team_name]
    if action == 'add':
        if name in [e['name'] for e in get_all_engineers(team_data)]: return jsonify({"error": "Already exists."}), 409
        new_engineer = {"name": name, "maxShifts": 2, "preferences": {}, "deficit": 0.0}
        smallest_group = min(team_data.get('baseGroups', [[]]), key=len)
        smallest_group.append(new_engineer)
    elif action == 'delete':
        team_data['baseGroups'] = [[e for e in g if e['name'] != name] for g in team_data['baseGroups']]
        for day in list(team_data.get('assignments', {})):
            team_data['assignments'][day] = [n for n in team_data['assignments'][day] if n != name]
    team_data['monthlyPriorities'] = {}
    save_data(data)
    return jsonify({"message": f"Engineer {name} {action}ed."})

@app.route("/api/manage-shift", methods=['POST'])
def manage_shift():
    data = load_data()
    payload = request.get_json()
    shift_date, original_engineer, team_name, target_engineer = payload.get('date'), payload.get('originalEngineer'), payload.get('team'), payload.get('targetEngineer')
    if not all([shift_date, original_engineer, team_name, target_engineer]): return jsonify({"error": "Missing required fields for swap"}), 400
    team_assignments = data['teams'][team_name]['assignments']
    if shift_date not in team_assignments or original_engineer not in team_assignments.get(shift_date, []): return jsonify({"error": "Assignment not found"}), 404
    try:
        index = team_assignments[shift_date].index(original_engineer)
        team_assignments[shift_date][index] = target_engineer
    except ValueError: return jsonify({"error": "Original engineer not found"}), 404
    save_data(data)
    return jsonify({"message": "Shift swapped successfully."})

@app.route("/api/reset-schedule", methods=['POST'])
def reset_schedule():
    data = load_data()
    month_str = request.get_json().get('month')
    if not month_str: return jsonify({"error": "Month is required"}), 400
    for team_data in data['teams'].values():
        team_data['assignments'] = { d: v for d, v in team_data.get('assignments', {}).items() if not d.startswith(month_str) }
    save_data(data)
    return jsonify({"message": "Schedule reset."})

# app.py - (Only the changed function is shown)

@app.route("/api/admin-dashboard", methods=['GET'])
def admin_dashboard():
    month_str = request.args.get('month', datetime.now().strftime('%Y-%m'))
    team_name = request.args.get('team', 'DC') # Used for team-specific reports
    data = load_data()
    
    # --- Team-Specific Reports (Discrepancy, No Prefs) ---
    if team_name not in data['teams']: return jsonify({"error": "Team not found"}), 404
    team_data = data['teams'][team_name]
    all_engineers_for_team = get_all_engineers(team_data)
    no_prefs = [{"name": e['name']} for e in all_engineers_for_team if not e.get('preferences', {}).get(month_str)]
    
    discrepancies, shifts_this_month = [], {e['name']: 0 for e in all_engineers_for_team}
    for day, names in team_data.get('assignments', {}).items():
        if day.startswith(month_str):
            for name in names:
                if name in shifts_this_month: shifts_this_month[name] += 1
    
    for eng in all_engineers_for_team:
        if shifts_this_month.get(eng['name'], 0) < eng.get('maxShifts', 2): 
            discrepancies.append({"name": eng['name'], "requested": eng.get('maxShifts', 2), "actual": shifts_this_month.get(eng['name'], 0)})

    # --- All-Team Preference Report ---
    all_team_preferences = {}
    for t_name, t_data in data['teams'].items():
        engineers = get_all_engineers(t_data)
        if not engineers: continue
        
        prefs = [{"name": e['name'], "maxShifts": e.get('maxShifts', 2), "preferences": e.get('preferences', {}).get(month_str, [])} for e in engineers]
        all_team_preferences[t_name] = sorted(prefs, key=lambda x: x['name'])

    # --- Common Data ---
    holidays = data.get('holidays', [])
    year, month = map(int, month_str.split('-'))
    on_call_days_for_month = get_on_call_days(year, month, holidays)
            
    return jsonify({
        "noPreferences": sorted(no_prefs, key=lambda x: x['name']),
        "shiftDiscrepancies": sorted(discrepancies, key=lambda x: x['name']),
        "allTeamPreferences": all_team_preferences, # MODIFIED: Now contains all teams
        "onCallDays": on_call_days_for_month
    })

@app.route("/admin")
def admin_page(): return render_template('admin.html')
@app.route("/")
def home(): return render_template('scheduler.html')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)