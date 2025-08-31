# app.py - Updated with Max Shifts, Priority Rotation, and Priority Page

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
        # Data structure is now a list of lists of objects
        engineers = [f"Engineer {i+1}" for i in range(50)]
        groups = []
        for i in range(0, 50, 5):
            group = []
            for j in range(5):
                # Each engineer is an object with a name and max shifts
                group.append({"name": engineers[i+j], "maxShifts": 2})
            groups.append(group)
        
        return {
            "groups": groups,
            "assignments": {},
            "engineerRoundRobinIndex": 0,
            # Tracks the last month rotation was performed for
            "lastRotation": datetime.now().strftime('%Y-%m')
        }

def save_data(data):
    """Saves the current data to the JSON file."""
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# --- API Endpoints ---
@app.route("/api/data", methods=['GET'])
def handle_data():
    # The frontend now sends the month it's viewing, e.g., ?month=2025-09
    viewing_month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    data = load_data()

    # --- Automatic Monthly Priority Rotation Logic ---
    if viewing_month != data.get('lastRotation'):
        # 1. Rotate Groups: Top group moves to the bottom
        if data['groups']:
            top_group = data['groups'].pop(0)
            data['groups'].append(top_group)
        
        # 2. Rotate Individuals within each group: Top person moves to the bottom
        for group in data['groups']:
            if group:
                top_person = group.pop(0)
                group.append(top_person)
        
        data['lastRotation'] = viewing_month
        save_data(data)

    return jsonify(data)

@app.route("/api/data", methods=['POST'])
def save_assignments():
    # This endpoint now only saves assignments and the index
    new_data = request.get_json()
    data = load_data()
    data['assignments'] = new_data.get('assignments', data['assignments'])
    data['engineerRoundRobinIndex'] = new_data.get('engineerRoundRobinIndex', data['engineerRoundRobinIndex'])
    save_data(data)
    return jsonify({"message": "Data saved successfully!"})


@app.route("/api/manage-engineers", methods=['POST'])
def manage_engineers():
    # Combined endpoint for adding/deleting engineers to ensure data integrity
    data = load_data()
    action = request.get_json().get('action')
    name = request.get_json().get('name')

    if action == 'add':
        all_engineers = [eng['name'] for group in data['groups'] for eng in group]
        if name in all_engineers: return jsonify({"error": "Engineer already exists."}), 409
        if not data['groups']: data['groups'].append([])
        smallest_group = min(data['groups'], key=len)
        smallest_group.append({"name": name, "maxShifts": 2}) # Add as an object
        message = f"'{name}' added."

    elif action == 'delete':
        # Remove from groups
        for group in data['groups']:
            group[:] = [eng for eng in group if eng.get('name') != name]
        # Remove from assignments
        for day in data['assignments']:
            data['assignments'][day][:] = [eng for eng in data['assignments'][day] if eng != name]
        message = f"'{name}' deleted."

    save_data(data)
    return jsonify({"message": message})


# --- NEW: Route for the Priorities Page ---
@app.route("/priorities")
def priorities_page():
    data = load_data()
    # Pass the current group data to the template
    return render_template('priorities.html', groups=data['groups'])


@app.route("/")
def home():
    return render_template('scheduler.html')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)