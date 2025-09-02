# app.py - Definitive Final Version

import json
from datetime import datetime, date, timedelta
import copy
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DATA_FILE = 'schedule_data.json'

# --- Data Handling Functions ---
def load_data():
    """Loads data, creating a default structure if the file is missing."""
    try:
        with open(DATA_FILE, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        engineers = [f"Engineer {i+1}" for i in range(50)]
        base_groups = [
            [{"name": engineers[i+j], "maxShifts": 2, "preferences": {}, "deficit": 0.0} for j in range(5)]
            for i in range(0, 50, 5)
        ]
        return { "baseGroups": base_groups, "monthlyPriorities": {}, "assignments": {}, "holidays": [] }

def save_data(data):
    """Saves the data dictionary to the JSON file."""
    with open(DATA_FILE, 'w') as f: json.dump(data, f, indent=4)

# --- NEW: Centralized function to prepare consistent API responses ---
def prepare_response_data(data, month_str):
    """
    Calculates the correct monthly priorities and formats the data consistently
    for all API responses to the frontend. This is the key bug fix.
    """
    if month_str not in data['monthlyPriorities']:
        sorted_months = sorted([m for m in data['monthlyPriorities'].keys() if m < month_str], reverse=True)
        base = data['monthlyPriorities'].get(sorted_months[0]) if sorted_months else data['baseGroups']
        
        rotated_groups = copy.deepcopy(base)
        if rotated_groups: rotated_groups.append(rotated_groups.pop(0))
        for group in rotated_groups:
            if group: group.append(group.pop(0))
        
        data['monthlyPriorities'][month_str] = rotated_groups
        save_data(data)

    all_engineers_data = {eng['name']: eng for g in data['baseGroups'] for eng in g}
    rotated_order_groups = data['monthlyPriorities'].get(month_str, data['baseGroups'])
    
    final_rotated_groups = []
    for group in rotated_order_groups:
        new_group = [all_engineers_data[eng['name']] for eng in group if eng['name'] in all_engineers_data]
        final_rotated_groups.append(new_group)
    
    return {
        "groups": final_rotated_groups,
        "assignments": data.get('assignments', {}),
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
    data = load_data()
    return jsonify(prepare_response_data(data, viewing_month))

@app.route("/api/holidays", methods=['GET', 'POST'])
def handle_holidays():
    data = load_data()
    if request.method == 'GET': return jsonify(data.get('holidays', []))
    if request.method == 'POST':
        data['holidays'] = request.get_json().get('holidays', [])
        save_data(data)
        return jsonify({"message": "Holidays updated."})

@app.route("/api/preferences", methods=['POST'])
def handle_preferences():
    data = load_data()
    payload = request.get_json()
    month_str, eng_name, prefs = payload.get('month'), payload.get('engineer'), payload.get('preferences')
    for group in data['baseGroups']:
        for eng in group:
            if eng['name'] == eng_name:
                eng.setdefault('preferences', {})[month_str] = prefs
                eng['maxShifts'] = payload.get('maxShifts', eng['maxShifts'])
                break
    save_data(data)
    return jsonify(prepare_response_data(data, month_str))

@app.route("/api/team", methods=['POST'])
def manage_team():
    data = load_data()
    action, name = request.get_json().get('action'), request.get_json().get('name')
    all_engineers = [eng for group in data['baseGroups'] for eng in group]
    if action == 'add':
        if name in [e['name'] for e in all_engineers]: return jsonify({"error": "Already exists."}), 409
        avg_deficit = sum(e.get('deficit', 0.0) for e in all_engineers) / len(all_engineers) if all_engineers else 0.0
        smallest_group = min(data['baseGroups'], key=len, default=[])
        smallest_group.append({"name": name, "maxShifts": 2, "preferences": {}, "deficit": avg_deficit})
    elif action == 'delete':
        for group in data['baseGroups']: group[:] = [e for e in group if e.get('name') != name]
        for day in data['assignments']: data['assignments'][day][:] = [e for e in data['assignments'][day] if e != name]
    data['monthlyPriorities'] = {}
    save_data(data)
    return jsonify(prepare_response_data(data, datetime.now().strftime('%Y-%m')))

@app.route("/api/generate-schedule", methods=['POST'])
def generate_schedule():
    data = load_data()
    month_str = request.get_json().get('month')
    year, month = int(month_str.split('-')[0]), int(month_str.split('-')[1])
    current_priorities = data['monthlyPriorities'].get(month_str, data['baseGroups'])
    all_engineers = [eng for group in data['baseGroups'] for eng in group]
    on_call_days = get_on_call_days(year, month, data.get('holidays', []))
    PREFERENCE_WEIGHTS = {i: 100 / (i + 1) for i in range(10)}
    FAIRNESS_INCREMENT = 1.0
    CREDIT_DECAY = 0.95
    data['assignments'] = {d: v for d, v in data['assignments'].items() if not d.startswith(month_str)}
    shifts_this_month = {eng['name']: 0 for eng in all_engineers}
    for day in on_call_days:
        candidates = []
        for eng in all_engineers:
            eng_prefs_for_month = eng.get('preferences', {}).get(month_str, [])
            pref_weight = PREFERENCE_WEIGHTS.get(eng_prefs_for_month.index(day)) if day in eng_prefs_for_month else 0.0
            score = eng.get('deficit', 0.0) + pref_weight
            candidates.append({'engineer': eng, 'score': score})
        primary_pool = [c for c in candidates if shifts_this_month[c['engineer']['name']] < c['engineer']['maxShifts']]
        fallback_pool = [c for c in candidates if shifts_this_month[c['engineer']['name']] >= c['engineer']['maxShifts']]
        primary_pool.sort(key=lambda x: x['score'], reverse=True)
        fallback_pool.sort(key=lambda x: x['score'], reverse=True)
        winners = [c['engineer'] for c in primary_pool[:5]]
        if len(winners) < 5:
            needed = 5 - len(winners)
            winners.extend([c['engineer'] for c in fallback_pool[:needed]])
        data['assignments'][day] = [w['name'] for w in winners]
        for eng_obj in all_engineers:
            if eng_obj in winners:
                eng_prefs_for_month = eng_obj.get('preferences', {}).get(month_str, [])
                pref_weight = PREFERENCE_WEIGHTS.get(eng_prefs_for_month.index(day)) if day in eng_prefs_for_month else 0.0
                eng_obj['deficit'] -= pref_weight
                shifts_this_month[eng_obj['name']] += 1
            else:
                eng_obj['deficit'] += FAIRNESS_INCREMENT
    for eng in all_engineers: eng['deficit'] *= CREDIT_DECAY
    save_data(data)
    return jsonify(prepare_response_data(data, month_str))

@app.route("/api/reset-schedule", methods=['POST'])
def reset_schedule():
    data = load_data()
    month_str = request.get_json().get('month')
    data['assignments'] = {d: v for d, v in data['assignments'].items() if not d.startswith(month_str)}
    save_data(data)
    return jsonify(prepare_response_data(data, month_str))

@app.route("/api/admin-dashboard", methods=['GET'])
def admin_dashboard():
    month_str = request.args.get('month', datetime.now().strftime('%Y-%m'))
    data = load_data()
    eng_to_group_map = {eng['name']: f"Group {i+1}" for i, g in enumerate(data['baseGroups']) for eng in g}
    all_engineers = [eng for group in data['baseGroups'] for eng in group]
    no_prefs = [{"name": e['name'], "group": eng_to_group_map.get(e['name'])} for e in all_engineers if not e.get('preferences', {}).get(month_str)]
    discrepancies = []
    shifts_this_month = {eng['name']: 0 for eng in all_engineers}
    for day, names in data.get('assignments', {}).items():
        if day.startswith(month_str):
            for name in names:
                if name in shifts_this_month: shifts_this_month[name] += 1
    for eng in all_engineers:
        requested = eng.get('maxShifts', 2)
        actual = shifts_this_month[eng['name']]
        if actual < requested:
            discrepancies.append({"name": eng['name'], "group": eng_to_group_map.get(eng['name']), "requested": requested, "actual": actual})
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