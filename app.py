# app.py - Fully Documented Stable Version

import json
from datetime import datetime
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS

# --- App Initialization ---
app = Flask(__name__)
CORS(app)

# --- Constants and Configuration ---
DATA_FILE = 'schedule_data.json'

# --- Data Handling Functions ---
def load_data():
    """
    Loads the application's state from the schedule_data.json file.
    If the file doesn't exist or is empty, it creates a default data structure.
    """
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Generate a default set of 50 engineers, divided into 10 groups of 5
        engineers = [f"Engineer {i+1}" for i in range(50)]
        groups = []
        for i in range(0, 50, 5):
            # Each engineer is an object with a name and a default max of 2 shifts
            group = [{"name": engineers[i+j], "maxShifts": 2} for j in range(5)]
            groups.append(group)
        
        # The default state of the application
        return {
            "groups": groups,
            "assignments": {},
            "groupRoundRobinIndex": 0,
            "lastRotation": datetime.now().strftime('%Y-%m') # Tracks the month for priority rotation
        }

def save_data(data):
    """Saves the provided data dictionary to the schedule_data.json file."""
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# --- API Endpoints ---
@app.route("/api/data", methods=['GET'])
def handle_data():
    """
    Handles fetching the main application data. It also automatically performs
    the monthly priority rotation if a new month is being viewed for the first time.
    """
    # The frontend sends the month it's viewing, e.g., ?month=2025-09
    viewing_month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    data = load_data()

    # --- Automatic Monthly Priority Rotation Logic ---
    if viewing_month != data.get('lastRotation'):
        # 1. Rotate Groups: Top group moves to the bottom
        if data['groups']:
            data['groups'].append(data['groups'].pop(0))
        # 2. Rotate Individuals within each group: Top person moves to the bottom
        for group in data['groups']:
            if group:
                group.append(group.pop(0))
        
        data['lastRotation'] = viewing_month
        save_data(data)

    return jsonify(data)

@app.route("/api/data", methods=['POST'])
def save_assignments():
    """Handles saving the current state of assignments and indices from the frontend."""
    new_data = request.get_json()
    save_data(new_data)
    return jsonify({"message": "Data saved successfully!"})

@app.route("/api/manage-engineers", methods=['POST'])
def manage_engineers():
    """Handles adding or deleting an engineer from the team."""
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
    """Renders the page that displays the current monthly priorities."""
    data = load_data()
    return render_template('priorities.html', groups=data['groups'])

@app.route("/")
def home():
    """Renders the main scheduler page."""
    return render_template('scheduler.html')

# --- Main Execution ---
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)