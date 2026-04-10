"""Canonical MCP action definitions — the only interface the AI layer sees.

DESIGN RULE: These schemas must never expose provider-native field names.
  ✓ amount (float, dollars)       ✗ amount_money.amount (Square, cents)
  ✓ currency (str, ISO code)      ✗ payment_intent_data (Stripe)
  ✓ attendee_emails (list[str])   ✗ invitees[].email (Calendly)

All actions are versioned.  Adding a field is backwards-compatible; removing or
renaming requires a new version string.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Action descriptor
# ---------------------------------------------------------------------------

@dataclass
class MCPAction:
    name: str
    description: str                   # LLM-facing description
    version: str                       # Semantic version, e.g. "1.0"
    providers: list[str]               # Which providers can fulfill this
    schema: dict[str, Any]            # JSON Schema for the canonical parameters
    output_schema: dict[str, Any]      # JSON Schema for the canonical response
    required_fields: list[str] = field(default_factory=list)
    idempotent: bool = False           # If True, safe to retry with same key


# ---------------------------------------------------------------------------
# ── Payment actions ──────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

CREATE_PAYMENT_LINK = MCPAction(
    name="CreatePaymentLink",
    version="1.0",
    description=(
        "Generate a shareable payment link for a product or service. "
        "Returns a URL the customer can open to complete payment."
    ),
    providers=["stripe", "square", "paypal"],
    required_fields=["amount", "currency", "description"],
    idempotent=True,
    schema={
        "type": "object",
        "required": ["amount", "currency", "description"],
        "additionalProperties": False,
        "properties": {
            "amount": {
                "type": "number",
                "description": "Amount in major currency units (e.g. 49.99 for $49.99).",
                "minimum": 0.01,
            },
            "currency": {
                "type": "string",
                "description": "ISO 4217 currency code, e.g. 'usd', 'cad', 'gbp'.",
                "minLength": 3, "maxLength": 3,
            },
            "description": {
                "type": "string",
                "description": "Human-readable product or service name shown on the checkout page.",
                "maxLength": 500,
            },
            "customer_email": {
                "type": "string",
                "description": "Pre-fill the customer's email on the checkout page (optional).",
                "format": "email",
            },
            "idempotency_key": {
                "type": "string",
                "description": "Unique key to prevent duplicate payment links on retry.",
                "maxLength": 255,
            },
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "payment_link_id": {"type": "string"},
            "url": {"type": "string", "format": "uri"},
            "amount": {"type": "number"},
            "currency": {"type": "string"},
            "provider": {"type": "string"},
        },
    },
)


GET_PAYMENT_STATUS = MCPAction(
    name="GetPaymentStatus",
    version="1.0",
    description="Check the current status of a payment by its provider-issued ID.",
    providers=["stripe"],
    required_fields=["payment_id"],
    idempotent=True,
    schema={
        "type": "object",
        "required": ["payment_id"],
        "additionalProperties": False,
        "properties": {
            "payment_id": {
                "type": "string",
                "description": "The payment ID returned when the payment was created.",
                "maxLength": 255,
            },
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "payment_id": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["pending", "completed", "failed", "cancelled", "refunded"],
            },
            "amount": {"type": "number"},
            "currency": {"type": "string"},
            "paid": {"type": "boolean"},
            "provider": {"type": "string"},
        },
    },
)


# ---------------------------------------------------------------------------
# ── Messaging actions ────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

SEND_SMS = MCPAction(
    name="SendSMS",
    version="1.0",
    description="Send an SMS text message to a phone number.",
    providers=["twilio", "telnyx"],
    required_fields=["to", "body"],
    schema={
        "type": "object",
        "required": ["to", "body"],
        "additionalProperties": False,
        "properties": {
            "to": {
                "type": "string",
                "description": "Recipient phone number in E.164 format, e.g. +16135551234.",
                "pattern": r"^\+[1-9]\d{6,14}$",
            },
            "body": {
                "type": "string",
                "description": "SMS message text (max 1600 characters).",
                "maxLength": 1600,
            },
            "from_number": {
                "type": "string",
                "description": "Override the sender phone number (optional; uses tenant default).",
            },
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "message_id": {"type": "string"},
            "status": {"type": "string"},
            "to": {"type": "string"},
            "provider": {"type": "string"},
        },
    },
)


SEND_EMAIL = MCPAction(
    name="SendEmail",
    version="1.0",
    description="Send a transactional or marketing email.",
    providers=["gmail"],
    required_fields=["to", "subject", "body"],
    schema={
        "type": "object",
        "required": ["to", "subject", "body"],
        "additionalProperties": False,
        "properties": {
            "to": {
                "type": "string",
                "description": "Recipient email address.",
                "format": "email",
            },
            "subject": {"type": "string", "maxLength": 998},
            "body": {
                "type": "string",
                "description": "Email body — plain text or HTML.",
            },
            "cc": {"type": "string", "description": "CC email address (optional)."},
            "reply_to": {"type": "string", "description": "Reply-To address (optional)."},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "sent": {"type": "boolean"},
            "message_id": {"type": "string"},
            "provider": {"type": "string"},
        },
    },
)


ADD_CONTACT_TO_LIST = MCPAction(
    name="AddContactToList",
    version="1.0",
    description="Add or update a contact in an email marketing list.",
    providers=["mailchimp"],
    required_fields=["email", "list_id"],
    schema={
        "type": "object",
        "required": ["email", "list_id"],
        "additionalProperties": False,
        "properties": {
            "email": {
                "type": "string",
                "format": "email",
                "description": "Contact's email address.",
            },
            "list_id": {
                "type": "string",
                "description": "The ID of the mailing list / audience to add the contact to.",
            },
            "first_name": {"type": "string", "maxLength": 100},
            "last_name": {"type": "string", "maxLength": 100},
            "status": {
                "type": "string",
                "enum": ["subscribed", "pending", "unsubscribed"],
                "default": "subscribed",
                "description": "Subscription status. Use 'pending' to send a double opt-in email.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags to apply to the contact (optional).",
            },
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "contact_id": {"type": "string"},
            "email": {"type": "string"},
            "status": {"type": "string"},
            "provider": {"type": "string"},
        },
    },
)


# ---------------------------------------------------------------------------
# ── Calendar actions ─────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

CHECK_CALENDAR_AVAILABILITY = MCPAction(
    name="CheckCalendarAvailability",
    version="1.0",
    description=(
        "Check available time slots on a calendar for a given date range. "
        "Returns a list of free time windows."
    ),
    providers=["google_calendar", "calendly"],
    required_fields=["date"],
    idempotent=True,
    schema={
        "type": "object",
        "required": ["date"],
        "additionalProperties": False,
        "properties": {
            "date": {
                "type": "string",
                "description": "Date to check in YYYY-MM-DD format.",
                "pattern": r"^\d{4}-\d{2}-\d{2}$",
            },
            "duration_minutes": {
                "type": "integer",
                "description": "Duration of the desired appointment slot in minutes.",
                "default": 60,
                "minimum": 15,
                "maximum": 480,
            },
            "timezone": {
                "type": "string",
                "description": "IANA timezone name, e.g. 'America/Toronto'. Defaults to UTC.",
                "default": "UTC",
            },
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "available_slots": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                    },
                },
            },
            "total_available": {"type": "integer"},
            "provider": {"type": "string"},
        },
    },
)


CREATE_CALENDAR_EVENT = MCPAction(
    name="CreateCalendarEvent",
    version="1.0",
    description="Book an appointment or create an event on a calendar.",
    providers=["google_calendar"],
    required_fields=["title", "start_datetime", "end_datetime"],
    schema={
        "type": "object",
        "required": ["title", "start_datetime", "end_datetime"],
        "additionalProperties": False,
        "properties": {
            "title": {
                "type": "string",
                "description": "Event title / appointment reason.",
                "maxLength": 1024,
            },
            "start_datetime": {
                "type": "string",
                "description": "Start time in ISO 8601 format, e.g. 2025-06-01T10:00:00-05:00.",
            },
            "end_datetime": {
                "type": "string",
                "description": "End time in ISO 8601 format.",
            },
            "attendee_emails": {
                "type": "array",
                "items": {"type": "string", "format": "email"},
                "description": "Email addresses of attendees to invite.",
                "maxItems": 20,
            },
            "description": {
                "type": "string",
                "description": "Additional notes or description for the event.",
                "maxLength": 8192,
            },
            "location": {
                "type": "string",
                "description": "Physical or virtual meeting location.",
                "maxLength": 1024,
            },
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "event_id": {"type": "string"},
            "status": {"type": "string"},
            "calendar_link": {"type": "string"},
            "start_datetime": {"type": "string"},
            "end_datetime": {"type": "string"},
            "provider": {"type": "string"},
        },
    },
)


SCHEDULE_MEETING = MCPAction(
    name="ScheduleMeeting",
    version="1.0",
    description=(
        "Schedule a meeting using a booking link service. "
        "The invitee receives a confirmation email."
    ),
    providers=["calendly"],
    required_fields=["start_datetime", "attendee_name", "attendee_email"],
    schema={
        "type": "object",
        "required": ["start_datetime", "attendee_name", "attendee_email"],
        "additionalProperties": False,
        "properties": {
            "start_datetime": {
                "type": "string",
                "description": "Selected slot start time in ISO 8601 format (from CheckCalendarAvailability).",
            },
            "attendee_name": {
                "type": "string",
                "description": "Full name of the person booking the meeting.",
                "maxLength": 255,
            },
            "attendee_email": {
                "type": "string",
                "format": "email",
                "description": "Email address of the person booking the meeting.",
            },
            "notes": {
                "type": "string",
                "description": "Optional notes or agenda for the meeting.",
                "maxLength": 2048,
            },
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "meeting_id": {"type": "string"},
            "status": {"type": "string"},
            "start_datetime": {"type": "string"},
            "end_datetime": {"type": "string"},
            "join_url": {"type": "string"},
            "provider": {"type": "string"},
        },
    },
)


# ---------------------------------------------------------------------------
# Registry of all canonical actions
# ---------------------------------------------------------------------------

ALL_ACTIONS: dict[str, MCPAction] = {
    a.name: a for a in [
        CREATE_PAYMENT_LINK,
        GET_PAYMENT_STATUS,
        SEND_SMS,
        SEND_EMAIL,
        ADD_CONTACT_TO_LIST,
        CHECK_CALENDAR_AVAILABILITY,
        CREATE_CALENDAR_EVENT,
        SCHEDULE_MEETING,
    ]
}


def get_action(name: str) -> Optional[MCPAction]:
    return ALL_ACTIONS.get(name)


def list_actions_for_provider(provider: str) -> list[MCPAction]:
    return [a for a in ALL_ACTIONS.values() if provider in a.providers]
