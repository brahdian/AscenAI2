"""Built-in appointment booking tool handlers."""
from __future__ import annotations

APPOINTMENT_BOOK_SCHEMA = {
    "type": "object",
    "required": ["service", "date", "time", "customer_name"],
    "properties": {
        "service": {"type": "string"},
        "date": {"type": "string", "description": "YYYY-MM-DD"},
        "time": {"type": "string", "description": "HH:MM"},
        "customer_name": {"type": "string"},
        "phone": {"type": "string"},
        "notes": {"type": "string"},
    },
}

APPOINTMENT_BOOK_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "appointment_id": {"type": "string"},
        "status": {"type": "string"},
        "confirmation_code": {"type": "string"},
    },
}

APPOINTMENT_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "date": {"type": "string", "description": "YYYY-MM-DD"},
        "service": {"type": "string"},
    },
}

APPOINTMENT_LIST_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "slots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "time": {"type": "string"},
                    "available": {"type": "boolean"},
                },
            },
        }
    },
}

APPOINTMENT_CANCEL_SCHEMA = {
    "type": "object",
    "required": ["appointment_id"],
    "properties": {"appointment_id": {"type": "string"}},
}


async def handle_appointment_book(parameters: dict, tenant_config: dict) -> dict:
    import uuid
    appt_id = f"APT-{uuid.uuid4().hex[:8].upper()}"
    return {
        "appointment_id": appt_id,
        "status": "confirmed",
        "confirmation_code": appt_id,
        "message": f"Appointment confirmed for {parameters.get('date')} at {parameters.get('time')}",
    }


async def handle_appointment_list(parameters: dict, tenant_config: dict) -> dict:
    date = parameters.get("date", "today")
    slots = [
        {"time": f"{h:02d}:00", "available": h % 2 == 0}
        for h in range(9, 18)
    ]
    return {"date": date, "slots": slots}


async def handle_appointment_cancel(parameters: dict, tenant_config: dict) -> dict:
    appt_id = parameters.get("appointment_id", "UNKNOWN")
    return {
        "appointment_id": appt_id,
        "status": "cancelled",
        "message": f"Appointment {appt_id} has been cancelled.",
    }
