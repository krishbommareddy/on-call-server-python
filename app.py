
# main file

from flask import Flask, jsonify, request, render_template
from flask_cors import CORS # Import CORS

app = Flask(__name__)
CORS(app) # Enable CORS for your entire app

# --- In-Memory Data Store ---
# This dictionary will act as our temporary database.
# When the server restarts, this data will be reset.
schedule_data = {
    "teamMembers": [f"Team Member {i+1}" for i in range(50)],
    "assignments": {},
    "roundRobinIndex": 0
    }

# This route handles GET requests to fetch data and POST requests to save data.
@app.route("/api/data", methods=['GET', 'POST'])
def handle_data():
    global schedule_data

    # If the browser is asking for data (GET request)
    if request.method == 'GET':
        print("GET request received. Sending schedule data.")
        return jsonify(schedule_data)

    # If the browser is sending data to save (POST request)
    if request.method == 'POST':
        new_data = request.get_json() # Get the data from the request
        schedule_data = new_data # Update our in-memory store
        print("POST request received. Data updated.")
        return jsonify({"message": "Data saved successfully!"}), 200

@app.route("/")
def home():
    # This line tells Flask to find scheduler.html in the templates folder
    # and send the entire file to the browser.
    return render_template('scheduler.html')

# Add your other API routes here, for example:
# @app.route("/api/schedule")
# def get_schedule():
#     # Your logic to return the schedule as JSON
#     pass

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)

