"""Thin wrapper around the Google Calendar API for inserting one event."""

from datetime import datetime, timedelta

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _load_credentials(token_path):
    if not token_path.exists():
        raise RuntimeError(
            f"No {token_path.name} found at {token_path}. Run google_auth_setup.py once first."
        )
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def build_service(token_path):
    creds = _load_credentials(token_path)
    return build("calendar", "v3", credentials=creds)


def insert_event(service, calendar_id, event, timezone):
    """event is the dict produced by extractor.extract_event (with found=True)."""
    start_dt = datetime.strptime(f"{event['date']} {event['time']}", "%Y-%m-%d %H:%M")
    start_dt = start_dt.replace(tzinfo=timezone)
    end_dt = start_dt + timedelta(minutes=event["duration_minutes"])
    tz_name = str(timezone)

    body = {
        "summary": event["topic_ru"],
        "location": event.get("location_ru") or "",
        "description": f"С кем: {event['with_whom_ru']}" if event.get("with_whom_ru") else "",
        "start": {"dateTime": start_dt.isoformat(), "timeZone": tz_name},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": tz_name},
    }

    created = service.events().insert(calendarId=calendar_id, body=body).execute()
    return created.get("htmlLink")
