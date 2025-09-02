# app.py - Definitive Final Version

import json
from datetime import datetime, date, timedelta
import copy
import math
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DATA_FILE = 'schedule_data.json'

# --- Data Handling Functions ---
def load_data():
    """Loads data, creating a default structure if the file is missing."""
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        dc_engineers = [f"DC Engineer {i+1}" for i in range(22)]
        bsn_engineers = [f"BSN Engineer {i+1}" for i in range(1)]

        # Divide DC engineers into 5 groups: [5, 5, 4, 4, 4]
        dc_groups = [
            [{"name": name, "maxShifts": 2, "preferences": {}, "deficit": 0.0} for name in dc_engineers[0:5]],
            [{"name": name, "maxShifts": 2, "preferences": {}, "deficit": 0.0} for name in dc_engineers[5:10]],
            [{"name": name, "maxShifts": 2, "preferences": {}, "deficit": 0.0} for name in dc_engineers[10:14]],
            [{"name": name, "maxShifts": 2, "preferences": {}, "deficit": 0.0} for name in dc_engineers[14:18]],
            [{"name": name, "maxShifts": 2, "preferences": {}, "deficit": 0.0} for name in dc_engineers[18:22]],
        ]

        return {
            "teams": {
                "DC": {
                    "baseGroups": dc_groups,
                    "monthlyPriorities": {},
                    "assignments": {}
                },
                "BSN": {
                    # BSN doesn't need groups, but we'll use a compatible structure
                    "baseGroups": [[{"name": name, "maxShifts": 2, "preferences": {}, "deficit": 0.0} for name in bsn_engineers]],
                    "monthlyPriorities": {},
                    "assignments": {}
                }
            },
            "holidays": []
        }

def save_data(data):
    """Saves the data dictionary to the JSON file."""
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def get_all_engineers(team_data):
    """Flattens the group structure to get a simple list of engineers."""
    return [engineer for group in team_data.get('baseGroups', []) for engineer in group]

# --- NEW: Centralized function to prepare consistent API responses ---
def prepare_response_data(data, month_str, team_name):
    """
    Calculates the correct monthly priorities and formats the data consistently.
    """
    team_data = data['teams'][team_name]
    if month_str not in team_data['monthlyPriorities']:
        sorted_months = sorted([m for m in team_data['monthlyPriorities'].keys() if m < month_str], reverse=True)
        base = team_data['monthlyPriorities'].get(sorted_months[0]) if sorted_months else team_data['baseGroups']
        
        rotated_groups = copy.deepcopy(base)
        if team_name == "DC": # Only apply complex rotation to DC team
            if rotated_groups: rotated_groups.append(rotated_groups.pop(0))
            for group in rotated_groups:
                if group: group.append(group.pop(0))
        
        team_data['monthlyPriorities'][month_str] = rotated_groups
        save_data(data)

    all_engineers_data = {eng['name']: eng for eng in get_all_engineers(team_data)}
    rotated_order_groups = team_data['monthlyPriorities'].get(month_str, team_data['baseGroups'])
    
    final_rotated_groups = []
    for group in rotated_order_groups:
        new_group = [all_engineers_data[eng['name']] for eng in group if eng['name'] in all_engineers_data]
        final_rotated_groups.append(new_group)

    # Combine assignments from all teams for a complete view
    all_assignments = {}
    for t_name, t_data in data['teams'].items():
        for day, names in t_data.get('assignments', {}).items():
            if day not in all_assignments:
                all_assignments[day] = []
            all_assignments[day].extend(names)

    return {
        "groups": final_rotated_groups,
        "assignments": all_assignments,
        "holidays": data.get('holidays', [])
    }


def get_on_call_days(year, month, holidays):
    """Calculates all on-call days for a given month."""
    days = []
    start_date = date(year, month, 1)
    next_m, next_y = (month + 1, year) if month < 12 else (1, year + 1)
    end_date = date(next_y, next_m, 1)
    d = start_date
    while d < end_date:
        date_str = d.strftime('%Y-%m-%d')
        if d.weekday() >= 5 or date_str in holidays: # 5=Sat, 6=Sun
            days.append(date_str)
        d += timedelta(days=1)
    return sorted(list(set(days)))

# --- API Endpoints ---
@app.route("/api/data", methods=['GET'])
def handle_data():
    viewing_month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    team_name = request.args.get('team', 'DC')
    data = load_data()
    if team_name not in data['teams']: return jsonify({"error": "Team not found"}), 404
    return jsonify(prepare_response_data(data, viewing_month, team_name))

@app.route("/api/holidays", methods=['GET', 'POST'])
def handle_holidays():
    data = load_data()
    if request.method == 'GET':
        return jsonify(data.get('holidays', []))
    if request.method == 'POST':
        data['holidays'] = request.get_json().get('holidays', [])
        save_data(data)
        return jsonify({"message": "Holidays updated."})

@app.route("/api/preferences", methods=['POST'])
def handle_preferences():
    data = load_data()
    payload = request.get_json()
    month_str, eng_name, team_name = payload.get('month'), payload.get('engineer'), payload.get('team')
    
    team_data = data['teams'][team_name]
    for group in team_data['baseGroups']:
        for eng in group:
            if eng['name'] == eng_name:
                eng.setdefault('preferences', {})[month_str] = payload.get('preferences')
                eng['maxShifts'] = payload.get('maxShifts')
                break
    save_data(data)
    return jsonify(prepare_response_data(data, month_str, team_name))

@app.route("/api/team", methods=['POST'])
def manage_team():
    data = load_data()
    payload = request.get_json()
    action, name, team_name = payload.get('action'), payload.get('name'), payload.get('team')
    
    team_data = data['teams'][team_name]
    all_engineers = get_all_engineers(team_data)

    if action == 'add':
        if name in [e['name'] for e in all_engineers]:
            return jsonify({"error": "Already exists."}), 409
        
        new_engineer = {"name": name, "maxShifts": 2, "preferences": {}, "deficit": 0.0}
        # Add to the smallest group
        smallest_group = min(team_data['baseGroups'], key=len, default=None)
        if smallest_group is not None:
            smallest_group.append(new_engineer)
        else: # Handle case where there are no groups
            team_data['baseGroups'].append([new_engineer])

    elif action == 'delete':
        for group in team_data['baseGroups']:
            group[:] = [e for e in group if e.get('name') != name]
        for day, assignments in team_data.get('assignments', {}).items():
            team_data['assignments'][day] = [e for e in assignments if e != name]
            
    team_data['monthlyPriorities'] = {} # Reset priorities on team change
    save_data(data)
    return jsonify(prepare_response_data(data, datetime.now().strftime('%Y-%m'), team_name))


@app.route("/api/generate-schedule", methods=['POST'])
def generate_schedule():
    data = load_data()
    month_str = request.get_json().get('month')
    year, month = int(month_str.split('-')[0]), int(month_str.split('-')[1])
    on_call_days = get_on_call_days(year, month, data.get('holidays', []))
    
    PREFERENCE_WEIGHTS = {i: 100 / (i + 1) for i in range(10)}
    FAIRNESS_INCREMENT = 1.0
    CREDIT_DECAY = 0.95

    for team_name in data['teams']:
        data['teams'][team_name]['assignments'] = {d: v for d, v in data['teams'][team_name].get('assignments', {}).items() if not d.startswith(month_str)}

    for team_name, team_data in data['teams'].items():
        shifts_needed = 5 if team_name == 'DC' else 1
        all_engineers = get_all_engineers(team_data)
        if not all_engineers: continue
        
        shifts_this_month = {eng['name']: 0 for eng in all_engineers}

        for day in on_call_days:
            candidates = []
            for eng in all_engineers:
                eng_prefs_for_month = eng.get('preferences', {}).get(month_str, [])
                pref_weight = PREFERENCE_WEIGHTS.get(eng_prefs_for_month.index(day)) if day in eng_prefs_for_month else 0.0
                score = eng.get('deficit', 0.0) + pref_weight
                candidates.append({'engineer': eng, 'score': score})

            primary_pool = [c for c in candidates if shifts_this_month[c['engineer']['name']] < c['engineer']['maxShifts']]
            fallback_pool = candidates
            
            primary_pool.sort(key=lambda x: x['score'], reverse=True)
            fallback_pool.sort(key=lambda x: x['score'], reverse=True)
            
            winners = [c['engineer'] for c in primary_pool[:shifts_needed]]
            if len(winners) < shifts_needed:
                needed = shifts_needed - len(winners)
                existing_winner_names = {w['name'] for w in winners}
                fallback_winners = [c['engineer'] for c in fallback_pool if c['engineer']['name'] not in existing_winner_names][:needed]
                winners.extend(fallback_winners)

            team_data['assignments'][day] = [w['name'] for w in winners]
            
            for eng_obj in all_engineers:
                if eng_obj in winners:
                    eng_prefs_for_month = eng_obj.get('preferences', {}).get(month_str, [])
                    pref_weight = PREFERENCE_WEIGHTS.get(eng_prefs_for_month.index(day)) if day in eng_prefs_for_month else 0.0
                    eng_obj['deficit'] -= pref_weight
                    shifts_this_month[eng_obj['name']] += 1
                else:
                    eng_obj['deficit'] += FAIRNESS_INCREMENT

        for eng in all_engineers:
            eng['deficit'] *= CREDIT_DECAY
            
    save_data(data)
    return jsonify(prepare_response_data(data, month_str, 'DC'))

@app.route("/api/reset-schedule", methods=['POST'])
def reset_schedule():
    data = load_data()
    payload = request.get_json()
    month_str, team_name = payload.get('month'), payload.get('team')
    
    if team_name in data['teams']:
        team_data = data['teams'][team_name]
        team_data['assignments'] = {d: v for d, v in team_data.get('assignments', {}).items() if not d.startswith(month_str)}
        save_data(data)
        return jsonify(prepare_response_data(data, month_str, team_name))
    return jsonify({"error": "Team not found"}), 404

@app.route("/api/admin-dashboard", methods=['GET'])
def admin_dashboard():
    month_str = request.args.get('month', datetime.now().strftime('%Y-%m'))
    team_name = request.args.get('team', 'DC')
    data = load_data()
    
    if team_name not in data['teams']:
        return jsonify({"error": "Team not found"}), 404
        
    team_data = data['teams'][team_name]
    all_engineers = get_all_engineers(team_data)
    assignments = team_data.get('assignments', {})

    no_prefs = [{"name": e['name']} for e in all_engineers if not e.get('preferences', {}).get(month_str)]
    
    discrepancies = []
    shifts_this_month = {eng['name']: 0 for eng in all_engineers}
    for day, names in assignments.items():
        if day.startswith(month_str):
            for name in names:
                if name in shifts_this_month:
                    shifts_this_month[name] += 1

    for eng in all_engineers:
        requested = eng.get('maxShifts', 2)
        actual = shifts_this_month[eng['name']]
        if actual < requested:
            discrepancies.append({"name": eng['name'], "requested": requested, "actual": actual})
            
    return jsonify({
        "noPreferences": sorted(no_prefs, key=lambda x: x['name']),
        "shiftDiscrepancies": sorted(discrepancies, key=lambda x: x['name'])
    })

# --- Webpage Routes ---
@app.route("/admin")
def admin_page(): return render_template('admin.html')
@app.route("/")
def home(): return render_template('scheduler.html')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)