# app.py - Updated with Delete Engineer and new Auto-fill logic support

import json
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
        # Create 10 groups of 5 engineers each
        total_engineers = 50
        group_size = 5
        engineers = [f"Engineer {i+1}" for i in range(total_engineers)]
        groups = [engineers[i:i + group_size] for i in range(0, total_engineers, group_size)]
        
        return {
            "groups": groups,
            "assignments": {},
            "groupRoundRobinIndex": 0,
            "engineerRoundRobinIndex": 0 # New index for prioritized auto-fill
        }

def save_data(data):
    """Saves the current data to the JSON file."""
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# --- API Endpoints ---
@app.route("/api/data", methods=['GET', 'POST'])
def handle_data():
    if request.method == 'GET':
        return jsonify(load_data())
    if request.method == 'POST':
        save_data(request.get_json())
        return jsonify({"message": "Data saved successfully!"}), 200

@app.route("/api/add-engineer", methods=['POST'])
def add_engineer():
    data = load_data()
    engineer_name = request.get_json().get('name')
    if not engineer_name: return jsonify({"error": "Name is required."}), 400
    all_engineers = [eng for group in data['groups'] for eng in group]
    if engineer_name in all_engineers: return jsonify({"error": "Engineer already exists."}), 409
    if not data['groups']: data['groups'].append([])
    smallest_group = min(data['groups'], key=len)
    smallest_group.append(engineer_name)
    save_data(data)
    return jsonify({"message": f"'{engineer_name}' added successfully."}), 201

# --- NEW: API Endpoint to Delete an Engineer ---
@app.route("/api/delete-engineer", methods=['POST'])
def delete_engineer():
    data = load_data()
    engineer_name = request.get_json().get('name')
    if not engineer_name: return jsonify({"error": "Name is required."}), 400

    # 1. Remove engineer from their group
    for group in data['groups']:
        if engineer_name in group:
            group.remove(engineer_name)
            break
    
    # 2. Remove engineer from all assignments
    for day in data['assignments']:
        if engineer_name in data['assignments'][day]:
            data['assignments'][day].remove(engineer_name)

    save_data(data)
    return jsonify({"message": f"'{engineer_name}' deleted successfully."}), 200

# --- Webpage Route ---
@app.route("/")
def home():
    return render_template('scheduler.html')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
