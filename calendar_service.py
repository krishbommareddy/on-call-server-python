from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

# You would get the user's token from their secure session
# For example: user_token = session.get('google_token')

def get_calendar_service(user_token):
    """Builds and returns an authenticated Google Calendar service object."""
    # Note: Authlib's token format is compatible with the google-api-python-client
    creds = Credentials(
        token=user_token['access_token'],
        refresh_token=user_token.get('refresh_token'),
        token_uri='https://oauth2.googleapis.com/token',
        client_id=os.getenv('GOOGLE_CLIENT_ID'),
        client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
        scopes=user_token['scope'].split()
    )
    return build('calendar', 'v3', credentials=creds)

def create_on_call_event(service, date_str, assigned_engineers):
    """Creates a new event on the user's primary calendar."""
    event_body = {
        'summary': f'On-call – {date_str}',
        'description': 'Assigned Employees:\n' + '\n'.join(assigned_engineers),
        'start': {'date': date_str},
        'end': {'date': date_str},
    }
    
    created_event = service.events().insert(calendarId='primary', body=event_body).execute()
    
    # Return the unique event ID, so you can save it and find it later for updates
    return created_event['id']

def update_on_call_event(service, event_id, new_assigned_engineers):
    """Updates an existing calendar event with a new list of engineers."""
    
    # First, get the existing event
    event = service.events().get(calendarId='primary', eventId=event_id).execute()
    
    # Modify just the part you need to change
    event['description'] = 'Assigned Employees:\n' + '\n'.join(new_assigned_engineers)

    service.events().update(calendarId='primary', eventId=event_id, body=event).execute()
    print(f"Event with ID {event_id} was updated.")