from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.mcp import ToolRegistration, ToolResponse, ToolUpdate
from app.services.tool_registry import ToolRegistry

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/tools")


# ---------------------------------------------------------------------------
# Integration catalog — static list of all supported integrations
# ---------------------------------------------------------------------------

INTEGRATION_CATALOG = [
    {
        "key": "appointment_book",
        "name": "Book Appointment",
        "description": "Book an appointment for a customer (built-in)",
        "category": "booking",
        "is_builtin": True,
        "credentials": [],
    },
    {
        "key": "appointment_list",
        "name": "List Available Slots",
        "description": "List available appointment time slots (built-in)",
        "category": "booking",
        "is_builtin": True,
        "credentials": [],
    },
    {
        "key": "appointment_cancel",
        "name": "Cancel Appointment",
        "description": "Cancel an existing appointment (built-in)",
        "category": "booking",
        "is_builtin": True,
        "credentials": [],
    },
    {
        "key": "crm_lookup",
        "name": "CRM Lookup",
        "description": "Look up a customer profile in the CRM (built-in)",
        "category": "crm",
        "is_builtin": True,
        "credentials": [],
    },
    {
        "key": "crm_update",
        "name": "CRM Update",
        "description": "Update a customer record in the CRM (built-in)",
        "category": "crm",
        "is_builtin": True,
        "credentials": [],
    },
    {
        "key": "google_calendar_check",
        "name": "Google Calendar — Check Availability",
        "description": "Check available slots in a Google Calendar",
        "category": "calendar",
        "is_builtin": False,
        "credentials": [
            {"field": "access_token", "label": "Google OAuth Access Token", "type": "password"},
            {"field": "calendar_id", "label": "Calendar ID (e.g. primary)", "type": "text"},
        ],
    },
    {
        "key": "google_calendar_book",
        "name": "Google Calendar — Book Event",
        "description": "Create an event in Google Calendar",
        "category": "calendar",
        "is_builtin": False,
        "credentials": [
            {"field": "access_token", "label": "Google OAuth Access Token", "type": "password"},
            {"field": "calendar_id", "label": "Calendar ID (e.g. primary)", "type": "text"},
        ],
    },
    {
        "key": "calendly_availability",
        "name": "Calendly — Get Availability",
        "description": "Get available scheduling slots from Calendly",
        "category": "calendar",
        "is_builtin": False,
        "credentials": [
            {"field": "api_token", "label": "Calendly Personal Access Token", "type": "password"},
            {"field": "event_type_uuid", "label": "Event Type UUID", "type": "text"},
        ],
    },
    {
        "key": "calendly_book",
        "name": "Calendly — Book Appointment",
        "description": "Schedule an appointment via Calendly",
        "category": "calendar",
        "is_builtin": False,
        "credentials": [
            {"field": "api_token", "label": "Calendly Personal Access Token", "type": "password"},
            {"field": "event_type_uuid", "label": "Event Type UUID", "type": "text"},
        ],
    },
    {
        "key": "stripe_payment_link",
        "name": "Stripe — Create Payment Link",
        "description": "Generate a Stripe payment link for a product or amount",
        "category": "payments",
        "is_builtin": False,
        "credentials": [
            {"field": "secret_key", "label": "Stripe Secret Key", "type": "password"},
        ],
    },
    {
        "key": "stripe_check_payment",
        "name": "Stripe — Check Payment Status",
        "description": "Check the status of a Stripe payment or invoice",
        "category": "payments",
        "is_builtin": False,
        "credentials": [
            {"field": "secret_key", "label": "Stripe Secret Key", "type": "password"},
        ],
    },
    {
        "key": "twilio_send_sms",
        "name": "Twilio — Send SMS",
        "description": "Send an SMS message via Twilio",
        "category": "messaging",
        "is_builtin": False,
        "credentials": [
            {"field": "account_sid", "label": "Twilio Account SID", "type": "text"},
            {"field": "auth_token", "label": "Twilio Auth Token", "type": "password"},
            {"field": "from_number", "label": "From Phone Number (E.164)", "type": "text"},
        ],
    },
    {
        "key": "gmail_send_email",
        "name": "Gmail / SMTP — Send Email",
        "description": "Send a confirmation or notification email",
        "category": "messaging",
        "is_builtin": False,
        "credentials": [
            {"field": "smtp_host", "label": "SMTP Host", "type": "text"},
            {"field": "smtp_port", "label": "SMTP Port (e.g. 587)", "type": "text"},
            {"field": "smtp_user", "label": "SMTP Username / Email", "type": "text"},
            {"field": "smtp_password", "label": "SMTP Password or App Password", "type": "password"},
            {"field": "from_email", "label": "From Email Address", "type": "text"},
        ],
    },
    {
        "key": "google_sheets_read",
        "name": "Google Sheets — Read Rows",
        "description": "Read rows from a Google Sheet",
        "category": "data",
        "is_builtin": False,
        "credentials": [
            {"field": "access_token", "label": "Google OAuth Access Token", "type": "password"},
            {"field": "spreadsheet_id", "label": "Spreadsheet ID", "type": "text"},
        ],
    },
    {
        "key": "google_sheets_append",
        "name": "Google Sheets — Append Row",
        "description": "Append a row to a Google Sheet",
        "category": "data",
        "is_builtin": False,
        "credentials": [
            {"field": "access_token", "label": "Google OAuth Access Token", "type": "password"},
            {"field": "spreadsheet_id", "label": "Spreadsheet ID", "type": "text"},
        ],
    },
    {
        "key": "custom_webhook",
        "name": "Custom Webhook",
        "description": "POST data to any custom HTTP endpoint",
        "category": "custom",
        "is_builtin": False,
        "credentials": [
            {"field": "url", "label": "Webhook URL", "type": "text"},
            {"field": "secret", "label": "Bearer Token / Secret (optional)", "type": "password"},
        ],
    },
]


def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


class SchemasRequest(BaseModel):
    tenant_id: str
    tool_names: list[str]


@router.post("/schemas")
async def get_tool_schemas(
    body: SchemasRequest,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """
    Return OpenAI function-calling schemas for the requested tools.
    The orchestrator calls this so Gemini knows which functions it can invoke.
    """
    registry = ToolRegistry(db)
    schemas: list[dict[str, Any]] = []

    for tool_name in body.tool_names:
        tool = await registry.get_tool(body.tenant_id, tool_name)
        if not tool:
            continue

        # Convert DB tool definition → OpenAI function-calling format
        parameters = tool.input_schema or {}
        # Ensure it has the required "type" key
        if "type" not in parameters:
            parameters = {"type": "object", "properties": {}}

        schemas.append({
            "name": tool.name,
            "description": tool.description,
            "parameters": parameters,
        })

    return schemas


@router.get("/catalog")
async def get_catalog() -> list[dict[str, Any]]:
    """Return the static catalog of all available integrations."""
    return INTEGRATION_CATALOG


@router.post("", response_model=ToolResponse, status_code=201)
async def register_tool(
    body: ToolRegistration,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Register a new tool for the tenant."""
    tenant_id = _tenant_id(request)
    registry = ToolRegistry(db)
    try:
        tool = await registry.register_tool(tenant_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await db.commit()
    await db.refresh(tool)
    return tool


@router.get("", response_model=list[ToolResponse])
async def list_tools(
    request: Request,
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all active tools for the tenant."""
    tenant_id = _tenant_id(request)
    registry = ToolRegistry(db)
    return await registry.list_tools(tenant_id, category=category)


@router.get("/{tool_name}", response_model=ToolResponse)
async def get_tool(
    tool_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific tool by name."""
    tenant_id = _tenant_id(request)
    registry = ToolRegistry(db)
    tool = await registry.get_tool(tenant_id, tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found.")
    return tool


@router.patch("/{tool_name}", response_model=ToolResponse)
async def update_tool(
    tool_name: str,
    body: ToolUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update a tool's configuration."""
    tenant_id = _tenant_id(request)
    registry = ToolRegistry(db)
    try:
        tool = await registry.update_tool(tenant_id, tool_name, body)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await db.commit()
    await db.refresh(tool)
    return tool


@router.delete("/{tool_name}", status_code=204)
async def delete_tool(
    tool_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Delete (deactivate) a tool."""
    tenant_id = _tenant_id(request)
    registry = ToolRegistry(db)
    try:
        await registry.delete_tool(tenant_id, tool_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await db.commit()
