"""Calendly integration handlers."""
from __future__ import annotations

import httpx

CALENDLY_AVAILABILITY_SCHEMA = {
    "type": "object",
    "required": ["start_date", "end_date"],
    "properties": {
        "start_date": {"type": "string", "description": "Start date YYYY-MM-DD"},
        "end_date": {"type": "string", "description": "End date YYYY-MM-DD"},
    },
}

CALENDLY_BOOK_SCHEMA = {
    "type": "object",
    "required": ["start_time", "name", "email"],
    "properties": {
        "start_time": {
            "type": "string",
            "description": "Slot start time in ISO 8601 format from availability check",
        },
        "name": {"type": "string", "description": "Invitee full name"},
        "email": {"type": "string", "description": "Invitee email address"},
        "notes": {"type": "string", "description": "Optional notes for the meeting"},
    },
}

_BASE = "https://api.calendly.com"


async def handle_calendly_availability(parameters: dict, tenant_config: dict) -> dict:
    """Get available event slots from Calendly."""
    api_token = tenant_config.get("api_token", "")
    event_type_uuid = tenant_config.get("event_type_uuid", "")

    if not api_token or not event_type_uuid:
        return {"error": "Calendly not configured. Add your API token and event type UUID."}

    start_date = parameters.get("start_date")
    end_date = parameters.get("end_date")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_BASE}/event_type_available_times",
            headers={"Authorization": f"Bearer {api_token}"},
            params={
                "event_type": f"https://api.calendly.com/event_types/{event_type_uuid}",
                "start_time": f"{start_date}T00:00:00Z",
                "end_time": f"{end_date}T23:59:59Z",
            },
        )

    if resp.status_code == 401:
        return {"error": "Calendly token invalid. Please update your personal access token."}
    if not resp.is_success:
        return {"error": f"Calendly API error: {resp.status_code}"}

    collection = resp.json().get("collection", [])
    slots = [
        {
            "start_time": item["start_time"],
            "scheduling_url": item.get("scheduling_url", ""),
        }
        for item in collection
    ]
    return {"available_slots": slots, "total": len(slots)}


async def handle_calendly_book(parameters: dict, tenant_config: dict) -> dict:
    """Schedule an event via Calendly invitee creation."""
    api_token = tenant_config.get("api_token", "")
    event_type_uuid = tenant_config.get("event_type_uuid", "")

    if not api_token or not event_type_uuid:
        return {"error": "Calendly not configured. Add your API token and event type UUID."}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{_BASE}/scheduled_events",
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            },
            json={
                "event_type": f"https://api.calendly.com/event_types/{event_type_uuid}",
                "start_time": parameters["start_time"],
                "invitees": [
                    {
                        "name": parameters["name"],
                        "email": parameters["email"],
                        "questions_and_answers": (
                            [{"question": "Notes", "answer": parameters["notes"]}]
                            if parameters.get("notes")
                            else []
                        ),
                    }
                ],
            },
        )

    if resp.status_code == 401:
        return {"error": "Calendly token invalid. Please update your personal access token."}
    if not resp.is_success:
        data = resp.json()
        return {"error": data.get("message", f"Calendly error {resp.status_code}")}

    event = resp.json().get("resource", {})
    return {
        "status": "scheduled",
        "event_uuid": event.get("uri", "").split("/")[-1],
        "start_time": event.get("start_time"),
        "end_time": event.get("end_time"),
        "meeting_url": event.get("location", {}).get("join_url", ""),
    }
