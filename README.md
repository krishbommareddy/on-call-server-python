# on-call-server-python
## Core Architecture
Web Application: A complete, single-page-style application accessible from any device on your network.

Python Backend: A robust Flask server that handles all logic and data storage.

Persistent Data: All team, schedule, and holiday data is saved in a schedule_data.json file on the server, so it persists even if the server restarts.

Separated Views: The application is split into two distinct interfaces: a main view for all employees and a powerful dashboard for managers.

## Manager Features (Admin Dashboard)
Accessed at http://<your-server-ip>:5000/admin, this is the central control panel.

Advanced Schedule Generation:

A "Generate Optimal Schedule" button that uses the advanced Deficit Fairness algorithm to create the schedule for a selected month.

Holiday Management:

A dedicated calendar interface to click and designate any day of the year as a statutory holiday, which will then be treated as an on-call day.

Team Management:

Add Engineer: Easily add new engineers to the team. The system automatically assigns them a fair starting "deficit" score.

Delete Engineer: Remove engineers from the team. The system also removes them from any future scheduled shifts.

Schedule Control:

Reset Schedule: A button to instantly clear all assignments for a selected month.

Reporting and Oversight:

An automatically updating "Monthly Reports" section.

A list of employees who have not submitted their preferences for the selected month.

A shift discrepancy report showing which employees were assigned fewer shifts than they requested.

"Copy List" buttons for both reports, allowing you to easily paste the names into an email or chat.

## Employee Features (Main Scheduler View)
This is the primary interface for team members, accessed at http://<your-server-ip>:5000/.

Preference Submission:

Select Your Name: A dropdown menu to identify yourself.

Request Shift Count: An input to specify the desired number of shifts (from 1 to 8) for the current month.

Ranked Preferences: An intuitive system to click on-call days in the calendar to create an ordered list of preferences.

Drag-and-Drop Reordering: An easy way to re-prioritize your preferred dates by dragging them up or down in the list.

Schedule Visibility:

A clean, responsive calendar view of the on-call schedule.

Shift Highlighting: When you select your name, all of your assigned shifts for that month are instantly highlighted with a blue ring.

Integrated Priority View: A "Team Priorities This Month" panel that shows the current, automatically rotated priority order of groups and their members.

## Core Scheduling Logic
This is the "intelligent" part of the application that powers the schedule generation.

Dynamic Weighted Round-Robin (Deficit Fairness): The core algorithm that balances:

Employee Happiness: By giving a large scoring bonus to engineers for their highly-ranked preferred days.

Team Fairness: By using a "deficit" score that increases when an engineer isn't picked and decreases when they are, ensuring everyone contributes over time.

Shift Requests: By using the employee-defined shift request as a "soft limit," which it tries to honor before filling remaining slots.

Automatic Monthly Priority Rotation: The base priority of groups (and engineers within them) automatically rotates each month to ensure the same people don't always have the highest raw priority. The priority for each month is saved and remains consistent.

## User Interface & Experience (UI/UX)
Responsive Design: The layout works beautifully on everything from a large desktop monitor to a mobile phone.

Enhanced Visibility: A modern dark theme with bright, bold, and alternating colors for calendar days, making the schedule easy to read.

Visual Cues: Features like drag handles on the preference list and larger rank numbers on the calendar make the application intuitive to use.

"Zebra Striping": Alternating background colors on the preference list improve readability.






