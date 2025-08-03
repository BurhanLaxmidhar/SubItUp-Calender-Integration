import requests
import json
from urllib.parse import unquote
from datetime import datetime, timedelta
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Read config
with open("config.json") as f:
    config = json.load(f)

EMPLOYEE_KEY = config["employeeKey"]
TOKEN = config["token"]
SECRET = config["secret"]
DEPT_KEY = config["deptKey"]
CALENDAR_ID = config["calendarId"]
TIMEZONE = "America/New_York"

# Google Calendar API scope
SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_calendar_service():
    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
    creds = flow.run_local_server(port=0)
    return build('calendar', 'v3', credentials=creds)

def get_week_date_range(offset_weeks=0):
    today = datetime.today()
    days_to_monday = today.weekday()
    monday = today - timedelta(days=days_to_monday) + timedelta(weeks=offset_weeks)
    sunday = monday + timedelta(days=6)
    return monday.strftime('%m-%d-%Y'), sunday.strftime('%m-%d-%Y'), monday, sunday

def fetch_shifts(start_date, end_date):
    url = "https://apiintegrations.subitup.com/api/Employee/GetEmployeeScheduleData"
    headers = {
        "accept": "*/*",
        "content-type": "application/json; charset=UTF-8",
        "origin": "https://account.subitup.com",
        "referer": "https://account.subitup.com/",
        "user-agent": "Mozilla/5.0",
    }
    data = {
        "employeekey": EMPLOYEE_KEY,
        "startdate": start_date,
        "enddate": end_date,
        "token": TOKEN,
        "deptKey": DEPT_KEY,
        "secret": SECRET,
        "applicationName": "AccountApp"
    }
    response = requests.post(url, headers=headers, json=data)
    if response.status_code != 200:
        print(f" Failed to fetch schedule ({start_date} to {end_date}): {response.status_code}")
        return []
    return response.json()

def get_shift_ids(shifts):
    return set(shift["shiftid"] for shift in shifts if shift.get("status") == "set")

def main():
    print(" Syncing SubItUp shifts for current and next week...")

    # 1. Fetch shifts for both weeks
    start_date1, end_date1, monday1, sunday1 = get_week_date_range(0)
    start_date2, end_date2, monday2, sunday2 = get_week_date_range(1)

    shifts1 = fetch_shifts(start_date1, end_date1)
    shifts2 = fetch_shifts(start_date2, end_date2)
    shifts = [*shifts1, *shifts2]

    print(f"  Pulled {len(shifts)} total shifts from SubItUp.")

    # 2. Build unique tag set for current valid shifts
    valid_shifts = [
        shift for shift in shifts
        if shift.get("status") == "set" and "want to work this shift" not in shift.get("HelpfulInfo", "").lower()
    ]
    shiftids_in_subitup = set(shift["shiftid"] for shift in valid_shifts)
    shiftid_to_shift = {shift["shiftid"]: shift for shift in valid_shifts}

    # 3. Setup calendar API
    calendar = get_calendar_service()
    added_count, skipped_count, deleted_count = 0, 0, 0

    # 4. Fetch all events for both week windows and check tags
    all_events = []
    for (monday, sunday) in [(monday1, sunday1), (monday2, sunday2)]:
        time_min = monday.strftime('%Y-%m-%dT00:00:00-04:00')
        time_max = (sunday + timedelta(days=1)).strftime('%Y-%m-%dT00:00:00-04:00')
        events = calendar.events().list(
            calendarId=CALENDAR_ID,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True
        ).execute().get("items", [])
        all_events.extend(events)

    # 5. Delete calendar events that aren't in SubItUp anymore
    for event in all_events:
        desc = event.get("description", "")
        shiftid = None
        if "[SubItUp:" in desc:
            start = desc.find("[SubItUp:") + 9
            end = desc.find("]", start)
            if end != -1:
                shiftid = desc[start:end]
        if shiftid and shiftid not in shiftids_in_subitup:
            calendar.events().delete(calendarId=CALENDAR_ID, eventId=event["id"]).execute()
            print(f"🗑️ Removed deleted shift: {event.get('summary')} ({shiftid})")
            deleted_count += 1

    # 6. Add/skip events for current shifts
    for shiftid, shift in shiftid_to_shift.items():
        summary = unquote(shift.get("ShiftName", "Work Shift"))
        description = shift.get("Title", "")
        notes = shift.get("ShiftNotes", "")
        if notes:
            description += "\n" + notes

        start_time = shift["milstart"].replace(" ", "T")
        end_time = shift["milend"].replace(" ", "T")
        unique_tag = f"[SubItUp:{shiftid}]"

        # Check for existing event with the tag
        event_exists = any(
            unique_tag in e.get("description", "") for e in all_events
        )
        if event_exists:
            print(f" Skipping duplicate: {summary} ({start_time})")
            skipped_count += 1
            continue

        event = {
            'summary': f'SubItUp: {summary}',
            'location': 'SubItUp Shift',
            'description': description.strip() + f"\n{unique_tag}",
            'start': {
                'dateTime': start_time,
                'timeZone': TIMEZONE,
            },
            'end': {
                'dateTime': end_time,
                'timeZone': TIMEZONE,
            },
        }

        calendar.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        print(f" Added: {summary} | {start_time} -> {end_time}")
        added_count += 1

    print(f"\n✔️ Sync complete. {added_count} added, {skipped_count} skipped, {deleted_count} removed.")

if __name__ == "__main__":
    main()
