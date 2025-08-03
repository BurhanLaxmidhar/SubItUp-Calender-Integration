import requests
import json
from urllib.parse import unquote
from datetime import datetime, timedelta
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

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
    return monday.strftime('%m-%d-%Y'), sunday.strftime('%m-%d-%Y')


# Get both current and next week ranges
start_date_1, end_date_1 = get_week_date_range(0)
start_date_2, end_date_2 = get_week_date_range(1)

# SubItUp API config
url = "https://apiintegrations.subitup.com/api/Employee/GetEmployeeScheduleData"
headers = {
    "accept": "*/*",
    "content-type": "application/json; charset=UTF-8",
    "origin": "https://account.subitup.com",
    "referer": "https://account.subitup.com/",
    "user-agent": "Mozilla/5.0",
}
common_payload = {
    "employeekey": "aJ7HSy%2bCF54%3d",
    "token": "FwJpIiDkhqndCl2r9Z2Oas7bv%2fASsB9lkP4%2bVELV2A%2bYY38p7eJl2A%3d%3d",
    "deptKey": 0,
    "secret": "biRAy%2f2Tat4FN1x4719HCtFOHOCujdgr23nc%2fapG9VJ7wagnie2I4Q%3d%3d",
    "applicationName": "AccountApp"
}

shifts = []
for start_date, end_date in [(start_date_1, end_date_1), (start_date_2, end_date_2)]:
    payload = {**common_payload, "startdate": start_date, "enddate": end_date}
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code != 200:
        print(" Failed to fetch schedule for", start_date, "to", end_date)
        continue
    shifts += response.json()

print(f"\n Pulled {len(shifts)} total shifts from SubItUp...\n")

calendar = get_calendar_service()

added_count = 0
skipped_count = 0

for shift in shifts:
    if shift.get("status") != "set":
        continue
    if "want to work this shift" in shift.get("HelpfulInfo", "").lower():
        continue

    summary = unquote(shift.get("ShiftName", "Work Shift"))
    description = shift.get("Title", "")
    notes = shift.get("ShiftNotes", "")
    if notes:
        description += "\n" + notes

    start_time = shift["milstart"].replace(" ", "T")
    end_time = shift["milend"].replace(" ", "T")
    shift_id = shift["shiftid"]
    unique_tag = f"[SubItUp:{shift_id}]"

    # Check for existing events in this timeframe
    existing_events = calendar.events().list(
        calendarId='671e68ce537a6d197cd0ec0c2c53574551073375cbf304bbdb4406771ba0bf81@group.calendar.google.com',
        timeMin=start_time + "-04:00",
        timeMax=end_time + "-04:00",
        singleEvents=True
    ).execute()

    already_exists = any(
        unique_tag in event.get("description", "") or (
            event.get("summary", "") == f"SubItUp: {summary}" and
            event.get("start", {}).get("dateTime", "") == start_time
        ) for event in existing_events.get("items", [])
    )

    if already_exists:
        print(f" Skipping duplicate: {summary} ({start_time})")
        skipped_count += 1
        continue

    event = {
        'summary': f'SubItUp: {summary}',
        'location': 'SubItUp Shift',
        'description': description.strip() + f"\n{unique_tag}",
        'start': {
            'dateTime': start_time,
            'timeZone': 'America/New_York',
        },
        'end': {
            'dateTime': end_time,
            'timeZone': 'America/New_York',
        },
    }

    calendar.events().insert(
        calendarId='671e68ce537a6d197cd0ec0c2c53574551073375cbf304bbdb4406771ba0bf81@group.calendar.google.com',
        body=event
    ).execute()
    print(f" Added: {summary} | {start_time} -> {end_time}")
    added_count += 1

print(f"\n Sync complete. {added_count} added, {skipped_count} skipped.")
