# test_app.py

import unittest
import os
import json
from app import app, DATA_FILE, load_data

class SchedulerTestCase(unittest.TestCase):
    """Test suite for the Scheduler Flask application."""

    def setUp(self):
        """Set up a test client and a temporary test data file before each test."""
        self.app = app.test_client()
        self.app.testing = True
        # Use a distinct test data file to avoid overwriting production data
        self.test_data_file = 'test_schedule_data.json'
        # Point the app's global DATA_FILE constant to our test file
        app.config['DATA_FILE'] = self.test_data_file
        self._cleanup() # Ensure no old test file exists

    def tearDown(self):
        """Clean up the test data file after each test."""
        self._cleanup()

    def _cleanup(self):
        """Helper function to remove the test data file."""
        if os.path.exists(self.test_data_file):
            os.remove(self.test_data_file)

    def _create_test_data(self, data):
        """Helper function to write initial data to the test file."""
        with open(self.test_data_file, 'w') as f:
            json.dump(data, f)

    def test_01_add_team_and_engineer(self):
        """Test creating a team and then adding an engineer to it."""
        # 1. Test creating a team
        response = self.app.post('/api/teams',
                                 data=json.dumps({'name': 'TestTeam'}),
                                 content_type='application/json')
        self.assertEqual(response.status_code, 200)
        
        # 2. Test creating an engineer
        response = self.app.post('/api/engineers',
                                 data=json.dumps({'name': 'TestEng', 'team': 'TestTeam', 'email': 'test@test.com'}),
                                 content_type='application/json')
        self.assertEqual(response.status_code, 200)

        # 3. Verify the engineer was added
        response = self.app.get('/api/engineers')
        data = json.loads(response.data)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['name'], 'TestEng')
        self.assertEqual(data[0]['team'], 'TestTeam')

    def test_02_case_insensitive_engineer_check(self):
        """Test that adding engineers with case differences is prevented."""
        # 1. Add the first team and engineer
        self.app.post('/api/teams', data=json.dumps({'name': 'TestTeam'}), content_type='application/json')
        self.app.post('/api/engineers', data=json.dumps({'name': 'JohnDoe', 'team': 'TestTeam', 'email': 'john@test.com'}), content_type='application/json')
        
        # 2. Try to add the same name with different casing
        response = self.app.post('/api/engineers',
                                 data=json.dumps({'name': 'johndoe', 'team': 'TestTeam', 'email': 'john2@test.com'}),
                                 content_type='application/json')
        
        # 3. Assert that the server correctly rejects it with a 409 Conflict status
        self.assertEqual(response.status_code, 409)
        data = json.loads(response.data)
        self.assertIn('already exists (case-insensitive)', data['error'])

    def test_03_schedule_generation(self):
        """Test the core scheduling algorithm with a simple scenario."""
        # 1. Setup initial data with two engineers and specific preferences
        test_data = {
            "settings": { "shifts_per_day": {"CORE": 1}, "preference_ranks_to_consider": 10, "default_max_shifts": 1 },
            "teams": { "CORE": {"baseGroups": [['EngA', 'EngB']], "monthlyPriorities": {}, "assignments": {}} },
            "engineers": {
                "EngA": { "name": "EngA", "team": "CORE", "maxShifts": 1, "preferences": {"2025-10": ["2025-10-04"]}, "consecutive_pref": "neutral", "email": "a@a.com" },
                "EngB": { "name": "EngB", "team": "CORE", "maxShifts": 1, "preferences": {"2025-10": ["2025-10-11"]}, "consecutive_pref": "neutral", "email": "b@b.com" }
            },
            "holidays": []
        }
        self._create_test_data(test_data)

        # 2. Generate the schedule for October 2025
        response = self.app.post('/api/generate-schedule',
                                 data=json.dumps({'month': '2025-10'}),
                                 content_type='application/json')
        self.assertEqual(response.status_code, 200)

        # 3. Verify the assignments are correct based on the algorithm rules
        response = self.app.get('/api/data?month=2025-10&team=CORE')
        data = json.loads(response.data)
        assignments = data['assignments']
        
        # EngA is higher priority and requested Oct 4
        self.assertIn('EngA', assignments['2025-10-04'])
        # EngB is lower priority and requested Oct 11
        self.assertIn('EngB', assignments['2025-10-11'])
        # No one requested Oct 5, so it should be empty
        self.assertEqual(len(assignments['2025-10-05']), 0)

if __name__ == '__main__':
    unittest.main()