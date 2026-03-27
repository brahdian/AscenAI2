"""Google Calendar integration handlers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

GOOGLE_CALENDAR_CHECK_SCHEMA = {
    "type": "object",
    "required": ["date"],
    "properties": {
        "date": {"type": "string", "description": "Date to check in YYYY-MM-DD format"},
        "duration_minutes": {
            "type": "integer",
            "description": "Duration of desired slot in minutes",
            "default": 60,
        },
    },
}

GOOGLE_CALENDAR_BOOK_SCHEMA = {
    "type": "object",
    "required": ["summary", "start_datetime", "end_datetime"],
    "properties": {
        "summary": {"type": "string", "description": "Event title / appointment reason"},
        "start_datetime": {
            "type": "string",
            "description": "Start datetime in ISO 8601 format, e.g. 2025-04-01T10:00:00-05:00",
        },
        "end_datetime": {
            "type": "string",
            "description": "End datetime in ISO 8601 format",
        },
        "attendee_email": {"type": "string", "description": "Customer email address"},
        "description": {"type": "string", "description": "Optional event description / notes"},
    },
}


async def handle_google_calendar_check(parameters: dict, tenant_config: dict) -> dict:
    """Check free/busy on a Google Calendar."""
    access_token = tenant_config.get("access_token", "")
    calendar_id = tenant_config.get("calendar_id", "primary")

    if not access_token:
        return {"error": "Google Calendar not configured. Please add your access token."}

    date_str = parameters.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    duration = parameters.get("duration_minutes", 60)

    try:
        day_start = datetime.fromisoformat(f"{date_str}T00:00:00+00:00")
        day_end = datetime.fromisoformat(f"{date_str}T23:59:59+00:00")
    except ValueError:
        return {"error": f"Invalid date format: {date_str}. Use YYYY-MM-DD."}

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://www.googleapis.com/calendar/v3/freeBusy",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={
                "timeMin": day_start.isoformat(),
                "timeMax": day_end.isoformat(),
                "items": [{"id": calendar_id}],
            },
        )

    if resp.status_code == 401:
        return {"error": "Google Calendar token expired. Please reconnect your Google account."}
    if not resp.is_success:
        return {"error": f"Google Calendar API error: {resp.status_code}"}

    busy_times = resp.json().get("calendars", {}).get(calendar_id, {}).get("busy", [])

    # Generate candidate slots (9am-5pm, hourly)
    available_slots = []
    slot_start = datetime.fromisoformat(f"{date_str}T09:00:00+00:00")
    slot_end_day = datetime.fromisoformat(f"{date_str}T17:00:00+00:00")

    while slot_start + timedelta(minutes=duration) <= slot_end_day:
        slot_end = slot_start + timedelta(minutes=duration)
        is_free = all(
            not (slot_start < datetime.fromisoformat(b["end"]) and slot_end > datetime.fromisoformat(b["start"]))
            for b in busy_times
        )
        if is_free:
            available_slots.append({
                "start": slot_start.strftime("%H:%M"),
                "end": slot_end.strftime("%H:%M"),
                "available": True,
            })
        slot_start += timedelta(hours=1)

    return {
        "date": date_str,
        "available_slots": available_slots,
        "total_available": len(available_slots),
    }


async def handle_google_calendar_book(parameters: dict, tenant_config: dict) -> dict:
    """Create an event in Google Calendar."""
    access_token = tenant_config.get("access_token", "")
    calendar_id = tenant_config.get("calendar_id", "primary")

    if not access_token:
        return {"error": "Google Calendar not configured. Please add your access token."}

    event_body: dict = {
        "summary": parameters["summary"],
        "start": {"dateTime": parameters["start_datetime"]},
        "end": {"dateTime": parameters["end_datetime"]},
    }
    if parameters.get("description"):
        event_body["description"] = parameters["description"]
    if parameters.get("attendee_email"):
        event_body["attendees"] = [{"email": parameters["attendee_email"]}]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=event_body,
        )

    if resp.status_code == 401:
        return {"error": "Google Calendar token expired. Please reconnect your Google account."}
    if not resp.is_success:
        return {"error": f"Failed to create event: {resp.status_code} — {resp.text[:200]}"}

    event = resp.json()
    return {
        "event_id": event.get("id"),
        "status": "confirmed",
        "html_link": event.get("htmlLink"),
        "summary": event.get("summary"),
        "start": event.get("start", {}).get("dateTime"),
        "end": event.get("end", {}).get("dateTime"),
    }
