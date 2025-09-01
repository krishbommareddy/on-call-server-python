# app.py - Final Definitive Version with All Features

import json
import random
from datetime import datetime, date, timedelta
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DATA_FILE = 'schedule_data.json'

# --- Data Handling Functions ---

def load_data():
    """
    Loads data from the JSON file.
    If the file doesn't exist, it creates a new data structure with the advanced
    engineer object model (including preferences and a deficit/credit score).
    """
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        engineers = [f"Engineer {i+1}" for i in range(50)]
        groups = []
        for i in range(0, 50, 5):
            group = [{
                "name": engineers[i+j], 
                "maxShifts": 2,
                "preferences": [], # Would be filled by a future UI
                "deficit": 0.0     # The fairness score (credit)
            } for j in range(5)]
            groups.append(group)
        
        return {
            "groups": groups,
            "assignments": {},
            "holidays": [],
            "lastRotation": datetime.now().strftime('%Y-%m')
        }

def save_data(data):
    """Saves the provided data dictionary to the JSON file."""
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# --- Helper Functions ---

def get_on_call_days(year, month, holidays):
    """Calculates all Saturdays, Sundays, and holidays for a given month."""
    days = []
    start_date = date(year, month, 1)
    next_month, next_year = (month + 1, year) if month < 12 else (1, year + 1)
    end_date = date(next_year, next_month, 1)
    
    current_date = start_date
    while current_date < end_date:
        date_str = current_date.strftime('%Y-%m-%d')
        if current_date.weekday() >= 5 or date_str in holidays: # 5=Saturday, 6=Sunday
            days.append(date_str)
        current_date += timedelta(days=1)
    return sorted(list(set(days)))

# --- API Endpoints ---

@app.route("/api/data", methods=['GET'])
def handle_data():
    """Handles fetching data and triggers monthly priority rotation."""
    viewing_month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    data = load_data()

    if viewing_month != data.get('lastRotation'):
        if data['groups']: data['groups'].append(data['groups'].pop(0))
        for group in data['groups']:
            if group: group.append(group.pop(0))
        data['lastRotation'] = viewing_month
        save_data(data)
    return jsonify(data)

@app.route("/api/data", methods=['POST'])
def save_assignments():
    """Saves manual changes to assignments from the client."""
    client_data = request.get_json()
    server_data = load_data()
    server_data['assignments'] = client_data.get('assignments', server_data['assignments'])
    save_data(server_data)
    return jsonify({"message": "Manual assignments saved."})

@app.route("/api/manage-engineers", methods=['POST'])
def manage_engineers():
    """Handles adding or deleting an engineer, compatible with the deficit system."""
    data = load_data()
    action = request.get_json().get('action')
    name = request.get_json().get('name')

    if not name: return jsonify({"error": "Engineer name is required."}), 400

    all_engineers = [eng for group in data['groups'] for eng in group]
    
    if action == 'add':
        if name in [eng['name'] for eng in all_engineers]:
            return jsonify({"error": "Engineer already exists."}), 409
        
        # Calculate the average deficit to give to the new engineer for fairness
        total_deficit = sum(eng.get('deficit', 0.0) for eng in all_engineers)
        average_deficit = total_deficit / len(all_engineers) if all_engineers else 0.0

        new_engineer = {"name": name, "maxShifts": 2, "preferences": [], "deficit": average_deficit}
        
        smallest_group = min(data['groups'], key=len, default=None)
        if smallest_group is None:
            smallest_group = []
            data['groups'].append(smallest_group)
        smallest_group.append(new_engineer)
        message = f"'{name}' was added."

    elif action == 'delete':
        for group in data['groups']:
            group[:] = [eng for eng in group if eng.get('name') != name]
        for day in data['assignments']:
            data['assignments'][day][:] = [eng for eng in data['assignments'][day] if eng != name]
        message = f"'{name}' was deleted."
    
    else:
        return jsonify({"error": "Invalid action."}), 400

    save_data(data)
    return jsonify({"message": message})

@app.route("/api/holidays", methods=['GET', 'POST'])
def handle_holidays():
    """Handles fetching and saving statutory holidays."""
    data = load_data()
    if request.method == 'GET': return jsonify(data.get('holidays', []))
    if request.method == 'POST':
        data['holidays'] = request.get_json().get('holidays', [])
        save_data(data)
        return jsonify({"message": "Holidays updated successfully."})

@app.route("/api/generate-schedule", methods=['POST'])
def generate_schedule():
    """Generates the optimal schedule using the Deficit Fairness algorithm."""
    data = load_data()
    month_str = request.get_json().get('month')
    year, month = int(month_str.split('-')[0]), int(month_str.split('-')[1])
    
    all_engineers = [eng for group in data['groups'] for eng in group]
    on_call_days = get_on_call_days(year, month, data.get('holidays', []))

    # --- SIMULATE PREFERENCES ---
    for eng in all_engineers:
        if len(on_call_days) >= 5:
            eng['preferences'] = random.sample(on_call_days, k=5)
        else:
            eng['preferences'] = on_call_days
    
    PREFERENCE_WEIGHTS = {0: 5.0, 1: 4.0, 2: 3.0, 3: 2.0, 4: 1.0}
    FAIRNESS_INCREMENT = 1.0
    CREDIT_DECAY = 0.90

    data['assignments'] = {day: val for day, val in data['assignments'].items() if not day.startswith(month_str)}
    shifts_this_month = {eng['name']: 0 for eng in all_engineers}

    for day in on_call_days:
        candidates = []
        for eng in all_engineers:
            pref_weight = 0.0
            if day in eng.get('preferences', []):
                rank = eng['preferences'].index(day)
                pref_weight = PREFERENCE_WEIGHTS.get(rank, 0.0)
            score = eng.get('deficit', 0.0) + pref_weight
            candidates.append({'engineer': eng, 'score': score})

        eligible = [c for c in candidates if shifts_this_month[c['engineer']['name']] < c['engineer']['maxShifts']]
        eligible.sort(key=lambda x: x['score'], reverse=True)
        winners = [c['engineer'] for c in eligible[:5]]
        
        if len(winners) < 5: # Fallback if not enough eligible people
             # In a real scenario, you might have more complex logic here
             pass

        data['assignments'][day] = [w['name'] for w in winners]

        for eng_obj in all_engineers:
            if eng_obj in winners:
                pref_weight = 0.0
                if day in eng_obj.get('preferences', []):
                    rank = eng_obj['preferences'].index(day)
                    pref_weight = PREFERENCE_WEIGHTS.get(rank, 0.0)
                eng_obj['deficit'] -= pref_weight
                shifts_this_month[eng_obj['name']] += 1
            else:
                eng_obj['deficit'] += FAIRNESS_INCREMENT

    for eng in all_engineers:
        eng['deficit'] *= CREDIT_DECAY

    save_data(data)
    return jsonify(data)

# --- Webpage Routes ---
@app.route("/admin")
def admin_page(): return render_template('admin.html')
@app.route("/priorities")
def priorities_page(): return render_template('priorities.html', groups=load_data()['groups'])
@app.route("/")
def home(): return render_template('scheduler.html')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)