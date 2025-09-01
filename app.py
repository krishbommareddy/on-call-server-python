# app.py - Definitive Version with All Features

import json
from datetime import datetime
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DATA_FILE = 'schedule_data.json'

def load_data():
    """Loads data from the JSON file, or creates a default structure."""
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        engineers = [f"Engineer {i+1}" for i in range(50)]
        groups = []
        for i in range(0, 50, 5):
            # Each engineer is an object with a name and a default max of 2 shifts
            group = [{"name": engineers[i+j], "maxShifts": 2} for j in range(5)]
            groups.append(group)
        
        return {
            "groups": groups,
            "assignments": {},
            "groupRoundRobinIndex": 0,
            "lastRotation": datetime.now().strftime('%Y-%m')
        }

def save_data(data):
    """Saves the current data to the JSON file."""
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# --- API Endpoints ---
@app.route("/api/data", methods=['GET'])
def handle_data():
    viewing_month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    data = load_data()

    # Automatic Monthly Priority Rotation Logic
    if viewing_month != data.get('lastRotation'):
        if data['groups']:
            data['groups'].append(data['groups'].pop(0)) # Rotate groups
        for group in data['groups']:
            if group:
                group.append(group.pop(0)) # Rotate engineers within groups
        data['lastRotation'] = viewing_month
        save_data(data)

    return jsonify(data)

@app.route("/api/data", methods=['POST'])
def save_assignments():
    # Saves the entire state sent from the client
    new_data = request.get_json()
    save_data(new_data)
    return jsonify({"message": "Data saved successfully!"})

@app.route("/api/manage-engineers", methods=['POST'])
def manage_engineers():
    data = load_data()
    action = request.get_json().get('action')
    name = request.get_json().get('name')

    if not name:
        return jsonify({"error": "Engineer name is required."}), 400

    if action == 'add':
        all_engineers = [eng['name'] for group in data['groups'] for eng in group]
        if name in all_engineers:
            return jsonify({"error": "Engineer already exists."}), 409
        
        if not data['groups']: data['groups'].append([])
        # Find the group with the fewest members to add the new engineer
        smallest_group = min(data['groups'], key=len, default=[])
        smallest_group.append({"name": name, "maxShifts": 2})
        message = f"'{name}' was added."

    elif action == 'delete':
        # Remove from groups
        for group in data['groups']:
            group[:] = [eng for eng in group if eng.get('name') != name]
        # Remove from all assignments
        for day in data['assignments']:
            data['assignments'][day][:] = [eng for eng in data['assignments'][day] if eng != name]
        message = f"'{name}' was deleted."
    
    else:
        return jsonify({"error": "Invalid action."}), 400

    save_data(data)
    return jsonify({"message": message})

# --- Webpage Routes ---
@app.route("/priorities")
def priorities_page():
    data = load_data()
    return render_template('priorities.html', groups=data['groups'])

@app.route("/")
def home():
    return render_template('scheduler.html')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)