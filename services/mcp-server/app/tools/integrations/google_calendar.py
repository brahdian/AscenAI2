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

    # Support both 'date' (legacy) and 'time_min'/'time_max' (organic)
    time_min_str = parameters.get("time_min")
    time_max_str = parameters.get("time_max")
    
    if not time_min_str:
        date_str = parameters.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        try:
            day_start = datetime.fromisoformat(f"{date_str}T00:00:00+00:00")
            day_end = datetime.fromisoformat(f"{date_str}T23:59:59+00:00")
        except ValueError:
            return {"error": f"Invalid date format: {date_str}. Use YYYY-MM-DD."}
    else:
        try:
            day_start = datetime.fromisoformat(time_min_str.replace("Z", "+00:00"))
            if time_max_str:
                day_end = datetime.fromisoformat(time_max_str.replace("Z", "+00:00"))
            else:
                day_end = day_start + timedelta(days=1)
        except ValueError:
            return {"error": "Invalid time_min/time_max format. Use ISO 8601."}

    duration = parameters.get("duration_minutes", 60)

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
        return {"error": "Google Calendar token expired. Please reconnect your account."}
    if not resp.is_success:
        return {"error": f"Google Calendar API error: {resp.status_code}"}

    busy_times = resp.json().get("calendars", {}).get(calendar_id, {}).get("busy", [])

    # Generate candidate slots (if range is short, otherwise just return busy times)
    available_slots = []
    current_time = day_start
    # Only generate slots if range is less than 3 days to avoid timeout
    if (day_end - day_start).days < 3:
        while current_time + timedelta(minutes=duration) <= day_end:
            slot_end = current_time + timedelta(minutes=duration)
            is_free = True
            for b in busy_times:
                b_start = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
                b_end = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
                if current_time < b_end and slot_end > b_start:
                    is_free = False
                    break
            
            if is_free:
                available_slots.append({
                    "start": current_time.isoformat(),
                    "end": slot_end.isoformat(),
                    "available": True,
                })
            current_time += timedelta(minutes=max(duration, 30)) # Step by 30-60 mins

    return {
        "time_min": day_start.isoformat(),
        "time_max": day_end.isoformat(),
        "busy_times": busy_times,
        "available_slots": available_slots if available_slots else "Range too large or no slots found",
        "total_available": len(available_slots),
    }


async def handle_google_calendar_book(parameters: dict, tenant_config: dict) -> dict:
    """Create an event in Google Calendar."""
    access_token = tenant_config.get("access_token", "")
    calendar_id = tenant_config.get("calendar_id", "primary")

    if not access_token:
        return {"error": "Google Calendar not configured. Please add your access token."}

    # Map our organic 'start_time'/'end_time' to handler's expected logic
    start_time = parameters.get("start_time") or parameters.get("start_datetime")
    end_time = parameters.get("end_time") or parameters.get("end_datetime")
    
    if not start_time or not end_time:
        return {"error": "Missing start_time or end_time."}

    event_body: dict = {
        "summary": parameters.get("summary", "AI Appointment"),
        "start": {"dateTime": start_time},
        "end": {"dateTime": end_time},
    }
    if parameters.get("description"):
        event_body["description"] = parameters["description"]
    
    attendees = parameters.get("attendees")
    if attendees:
        if isinstance(attendees, list):
            event_body["attendees"] = [{"email": e} for e in attendees]
        elif isinstance(attendees, str):
            event_body["attendees"] = [{"email": attendees}]
    elif parameters.get("attendee_email"):
        event_body["attendees"] = [{"email": parameters["attendee_email"]}]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=event_body,
        )

    if resp.status_code == 401:
        return {"error": "Google Calendar token expired."}
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
