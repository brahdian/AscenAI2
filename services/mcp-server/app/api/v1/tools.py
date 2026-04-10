from __future__ import annotations

import time
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.integrations.base import ACTION_REGISTRY
from app.schemas.mcp import ToolAuthConfig, ToolRegistration, ToolResponse, ToolUpdate
from app.services.tool_executor import SSRFError, _validate_tool_url
from app.services.tool_registry import ToolRegistry

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/tools")


# ---------------------------------------------------------------------------
# Integration catalog — External services requiring configuration
# ---------------------------------------------------------------------------

INTEGRATION_CATALOG: list[dict[str, Any]] = [
    {
        "id": "google_calendar",
        "name": "Google Calendar",
        "description": "Manage calendar events and availability via Google Calendar API.",
        "category": "calendar",
        "requires_config": True,
        "is_builtin": True,
        "config_schema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string", "description": "OAuth2 Access Token"},
                "refresh_token": {"type": "string", "description": "OAuth2 Refresh Token (optional)"},
                "client_id": {"type": "string"},
                "client_secret": {"type": "string"},
            },
            "required": ["access_token"]
        },
        "credentials": [
            {"field": "client_id", "label": "Client ID", "type": "text"},
            {"field": "client_secret", "label": "Client Secret", "type": "password"},
            {"field": "refresh_token", "label": "Refresh Token", "type": "password"},
            {"field": "access_token", "label": "Access Token", "type": "password"}
        ],
        "tools": [
            {
                "name": "calendar_check_availability",
                "description": "Check free/busy slots for a given time range.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "time_min": {"type": "string", "format": "date-time"},
                        "time_max": {"type": "string", "format": "date-time"},
                        "calendar_id": {"type": "string", "default": "primary"}
                    },
                    "required": ["time_min", "time_max"]
                }
            },
            {
                "name": "calendar_book_appointment",
                "description": "Book a new event on the calendar.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "start_time": {"type": "string", "format": "date-time"},
                        "end_time": {"type": "string", "format": "date-time"},
                        "attendees": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["summary", "start_time", "end_time"]
                }
            }
        ]
    },
    {
        "id": "calendly",
        "name": "Calendly",
        "description": "Sync and manage scheduling via Calendly.",
        "category": "calendar",
        "requires_config": True,
        "is_builtin": True,
        "config_schema": {
            "type": "object",
            "properties": {
                "api_key": {"type": "string", "description": "Calendly Personal Access Token"}
            },
            "required": ["api_key"]
        },
        "credentials": [
            {"field": "api_key", "label": "API Key", "type": "password"}
        ],
        "tools": [
            {
                "name": "calendly_list_event_types",
                "description": "List available event types for scheduling.",
                "input_schema": {"type": "object", "properties": {}}
            }
        ]
    },
    {
        "id": "stripe",
        "name": "Stripe",
        "description": "Process payments and manage subscriptions.",
        "category": "payments",
        "requires_config": True,
        "is_builtin": True,
        "voice_capable": True,
        "pci_method": "hosted_page",
        "pci_compliant": True,
        "channel_support": ["voice", "chat"],
        "config_schema": {
            "type": "object",
            "properties": {
                "api_key": {"type": "string", "description": "Stripe Secret Key"}
            },
            "required": ["api_key"]
        },
        "credentials": [
            {"field": "api_key", "label": "Secret Key", "type": "password"}
        ],
        "tools": [
            {
                "name": "stripe_get_customer",
                "description": "Retrieve customer details by email.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string"}
                    },
                    "required": ["email"]
                }
            }
        ]
    },
    {
        "id": "twilio",
        "name": "Twilio",
        "description": "Send and receive SMS messages via Twilio.",
        "category": "messaging",
        "requires_config": True,
        "is_builtin": True,
        "config_schema": {
            "type": "object",
            "properties": {
                "account_sid": {"type": "string"},
                "auth_token": {"type": "string"},
                "from_number": {"type": "string"}
            },
            "required": ["account_sid", "auth_token", "from_number"]
        },
        "credentials": [
            {"field": "account_sid", "label": "Account SID", "type": "text"},
            {"field": "auth_token", "label": "Auth Token", "type": "password"},
            {"field": "from_number", "label": "From Number", "type": "text"}
        ],
        "tools": [
            {
                "name": "twilio_send_sms",
                "description": "Send an SMS message to a phone number.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "body": {"type": "string"}
                    },
                    "required": ["to", "body"]
                }
            }
        ]
    },
    {
        "id": "gmail",
        "name": "Gmail / SMTP",
        "description": "Send confirmation or notification emails.",
        "category": "messaging",
        "requires_config": True,
        "is_builtin": True,
        "config_schema": {
            "type": "object",
            "properties": {
                "smtp_server": {"type": "string", "default": "smtp.gmail.com"},
                "smtp_port": {"type": "integer", "default": 587},
                "username": {"type": "string"},
                "password": {"type": "string", "description": "App Password"}
            },
            "required": ["username", "password"]
        },
        "credentials": [
            {"field": "smtp_server", "label": "SMTP Server", "type": "text"},
            {"field": "smtp_port", "label": "SMTP Port", "type": "text"},
            {"field": "username", "label": "Username", "type": "text"},
            {"field": "password", "label": "Password", "type": "password"}
        ],
        "tools": [
            {
                "name": "gmail_send_email",
                "description": "Send an email via SMTP.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "subject": {"type": "string"},
                        "body": {"type": "string"}
                    },
                    "required": ["to", "subject", "body"]
                }
            }
        ]
    },
    {
        "id": "google_sheets",
        "name": "Google Sheets",
        "description": "Read and write data to Google Sheets.",
        "category": "data",
        "requires_config": True,
        "is_builtin": True,
        "config_schema": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string"},
                "credentials_json": {"type": "string", "description": "Service Account JSON content"}
            },
            "required": ["spreadsheet_id"]
        },
        "credentials": [
            {"field": "spreadsheet_id", "label": "Spreadsheet ID", "type": "text"},
            {"field": "credentials_json", "label": "Service Account JSON", "type": "password"}
        ],
        "tools": [
            {
                "name": "google_sheets_read",
                "description": "Read rows from a spreadsheet range.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "range": {"type": "string", "default": "Sheet1!A1:Z100"}
                    }
                }
            },
            {
                "name": "google_sheets_append",
                "description": "Append a row to the end of a sheet.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "values": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["values"]
                }
            }
        ]
    },
    {
        "id": "webhook",
        "name": "Custom Webhook",
        "description": "POST data to any custom HTTP endpoint with optional authentication.",
        "category": "custom",
        "requires_config": True,
        "is_builtin": True,
        "allow_multiple": True,
        "config_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "format": "uri"},
                "method": {"type": "string", "enum": ["POST", "GET", "PUT", "PATCH"], "default": "POST"},
                "auth_type": {"type": "string", "enum": ["none", "api_key", "bearer", "basic"], "default": "none"},
                "headers": {"type": "object", "additionalProperties": {"type": "string"}}
            },
            "required": ["url"]
        },
        "credentials": [
            {"field": "url", "label": "Endpoint URL", "type": "text"},
            {"field": "auth_type", "label": "Auth Type", "type": "select", "options": ["none", "api_key", "bearer", "basic"]},
            {"field": "api_key", "label": "API Key / Token", "type": "password", "condition": {"auth_type": ["api_key", "bearer"]}},
            {"field": "username", "label": "Username", "type": "text", "condition": {"auth_type": ["basic"]}},
            {"field": "password", "label": "Password", "type": "password", "condition": {"auth_type": ["basic"]}}
        ],
        "tools": [
            {
                "name": "custom_webhook",
                "description": "Trigger a custom HTTP request.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "payload": {"type": "object", "description": "Data to send in the request body"}
                    }
                }
            }
        ]
    },
    {
        "id": "mailchimp",
        "name": "Mailchimp",
        "description": "Manage email marketing campaigns and subscribers.",
        "category": "messaging",
        "requires_config": True,
        "is_builtin": True,
        "config_schema": {
            "type": "object",
            "properties": {
                "api_key": {"type": "string", "description": "Mailchimp API Key"},
                "server_prefix": {"type": "string", "description": "e.g., us19"}
            },
            "required": ["api_key", "server_prefix"]
        },
        "credentials": [
            {"field": "api_key", "label": "API Key", "type": "password"},
            {"field": "server_prefix", "label": "Server Prefix", "type": "text"}
        ],
        "tools": [
            {
                "name": "mailchimp_add_subscriber",
                "description": "Add a new subscriber to a specific Mailchimp audience list.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "list_id": {"type": "string"},
                        "email": {"type": "string"},
                        "status": {"type": "string", "default": "subscribed"}
                    },
                    "required": ["list_id", "email"]
                }
            }
        ]
    },
    {
        "id": "square",
        "name": "Square",
        "description": "Process payments, create checkout links, and manage Square orders.",
        "category": "payments",
        "requires_config": True,
        "is_builtin": True,
        "voice_capable": True,
        "pci_method": "hosted_page",
        "pci_compliant": True,
        "channel_support": ["voice", "chat"],
        "config_schema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string", "description": "Square Access Token"},
                "location_id": {"type": "string", "description": "Square Location ID"},
                "environment": {"type": "string", "description": "sandbox or production"}
            },
            "required": ["access_token", "location_id"]
        },
        "credentials": [
            {"field": "access_token", "label": "Access Token", "type": "password"},
            {"field": "location_id", "label": "Location ID", "type": "text"},
            {"field": "environment", "label": "Environment (sandbox/production)", "type": "text"}
        ],
        "tools": [
            {
                "name": "square_create_payment_link",
                "description": "Generate a Square payment link for a product or custom amount.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "number"},
                        "currency": {"type": "string", "default": "CAD"},
                        "description": {"type": "string"}
                    },
                    "required": ["amount"]
                }
            }
        ]
    },
    {
        "id": "moneris",
        "name": "Moneris",
        "description": "Process Canadian e-commerce payments securely via Moneris Gateway.",
        "category": "payments",
        "requires_config": True,
        "is_builtin": True,
        "voice_capable": False,
        "pci_method": "direct",
        "pci_compliant": False,
        "channel_support": ["chat"],
        "config_schema": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string", "description": "Moneris Store ID"},
                "api_token": {"type": "string", "description": "Moneris API Token"},
                "environment": {"type": "string", "description": "qa or live"}
            },
            "required": ["store_id", "api_token"]
        },
        "credentials": [
            {"field": "store_id", "label": "Store ID", "type": "text"},
            {"field": "api_token", "label": "API Token", "type": "password"},
            {"field": "environment", "label": "Environment (qa/live)", "type": "text"}
        ],
        "tools": [
            {
                "name": "moneris_process_purchase",
                "description": "Process a direct purchase transaction via Moneris.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "string"},
                        "order_id": {"type": "string"},
                        "pan": {"type": "string", "description": "Credit Card Number"},
                        "expdate": {"type": "string", "description": "YYMM"}
                    },
                    "required": ["amount", "order_id", "pan", "expdate"]
                }
            }
        ]
    },
    {
        "id": "helcim",
        "name": "Helcim",
        "description": "Process Canadian e-commerce payments securely via Helcim.",
        "category": "payments",
        "requires_config": True,
        "is_builtin": True,
        "voice_capable": False,
        "pci_method": "direct",
        "pci_compliant": False,
        "channel_support": ["chat"],
        "config_schema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "Helcim Account ID"},
                "api_token": {"type": "string", "description": "Helcim API Token"}
            },
            "required": ["account_id", "api_token"]
        },
        "credentials": [
            {"field": "account_id", "label": "Account ID", "type": "text"},
            {"field": "api_token", "label": "API Token", "type": "password"}
        ],
        "tools": [
            {
                "name": "helcim_process_payment",
                "description": "Process a direct purchase transaction via Helcim.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "string"},
                        "card_token": {"type": "string"}
                    },
                    "required": ["amount"]
                }
            }
        ]
    },
    {
        "id": "paypal",
        "name": "PayPal",
        "description": "Process payments globally via PayPal orders.",
        "category": "payments",
        "requires_config": True,
        "is_builtin": True,
        "voice_capable": True,
        "pci_method": "hosted_page",
        "pci_compliant": True,
        "channel_support": ["voice", "chat"],
        "config_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string", "description": "PayPal Client ID"},
                "secret": {"type": "string", "description": "PayPal Secret"}
            },
            "required": ["client_id", "secret"]
        },
        "credentials": [
            {"field": "client_id", "label": "Client ID", "type": "text"},
            {"field": "secret", "label": "Secret", "type": "password"}
        ],
        "tools": [
            {
                "name": "paypal_create_order",
                "description": "Create a new PayPal order for checkout.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "string"},
                        "currency": {"type": "string", "default": "USD"}
                    },
                    "required": ["amount"]
                }
            }
        ]}
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


# ---------------------------------------------------------------------------
# Tool config verification (pre-save credential test)
# ---------------------------------------------------------------------------

class VerifyRequest(BaseModel):
    """Inline tool config to verify — no DB write, no side effects."""
    provider: str                        # e.g. "stripe", "twilio", "google_calendar"
    config: dict                         # Decrypted credentials to test
    endpoint_url: Optional[str] = None  # For HTTP tools — SSRF-checked before test


class VerifyResponse(BaseModel):
    ok: bool
    latency_ms: int
    error: Optional[str] = None
    details: dict = {}


@router.post("/verify", response_model=VerifyResponse)
async def verify_tool_config(
    body: VerifyRequest,
    request: Request,
) -> VerifyResponse:
    """Verify tool credentials before saving.

    Calls the provider's lightest read-only API endpoint to confirm the
    supplied credentials are valid.  No data is stored.

    For HTTP tools with an endpoint_url, the SSRF guard is enforced first.
    For known providers (stripe, twilio, google_calendar, etc.) the adapter's
    verify_config() is called which makes a cheap provider API call.
    """
    start = time.monotonic()

    # ── SSRF guard for HTTP tools ──────────────────────────────────────
    if body.endpoint_url:
        try:
            _validate_tool_url(body.endpoint_url)
        except SSRFError as exc:
            return VerifyResponse(ok=False, latency_ms=0, error=f"Invalid endpoint URL: {exc}")

        # For generic HTTP tools: make a lightweight OPTIONS/GET to check reachability
        import httpx
        try:
            # Build auth headers from the supplied auth_config
            auth_headers: dict = {}
            if body.config.get("type") == "api_key":
                header_name = body.config.get("header", "X-API-Key")
                auth_headers[header_name] = body.config.get("value", "")
            elif body.config.get("type") == "bearer":
                auth_headers["Authorization"] = f"Bearer {body.config.get('value', '')}"
            elif body.config.get("type") == "basic":
                import base64
                creds = base64.b64encode(
                    f"{body.config.get('username','')}:{body.config.get('password','')}".encode()
                ).decode()
                auth_headers["Authorization"] = f"Basic {creds}"

            t0 = time.monotonic()
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.request("HEAD", body.endpoint_url, headers=auth_headers)
            latency = int((time.monotonic() - t0) * 1000)

            auth_ok = resp.status_code not in (401, 403)
            return VerifyResponse(
                ok=resp.status_code < 500,
                latency_ms=latency,
                error=None if resp.status_code < 400 else f"HTTP {resp.status_code}",
                details={"http_status": resp.status_code, "auth_ok": auth_ok},
            )
        except httpx.ConnectError as exc:
            return VerifyResponse(ok=False, latency_ms=int((time.monotonic() - start) * 1000),
                                  error=f"Connection failed: {exc}")
        except httpx.TimeoutException:
            return VerifyResponse(ok=False, latency_ms=10000, error="Connection timed out after 10s")
        except Exception as exc:
            return VerifyResponse(ok=False, latency_ms=int((time.monotonic() - start) * 1000),
                                  error=str(exc))

    # ── Provider-aware verification via adapter ────────────────────────
    adapter = ACTION_REGISTRY.get_adapter(body.provider)
    if adapter is None:
        return VerifyResponse(
            ok=False,
            latency_ms=0,
            error=f"Unknown provider '{body.provider}'. Supported: {', '.join(ACTION_REGISTRY.list_providers())}",
        )

    result = await adapter.verify_config(body.config)
    return VerifyResponse(
        ok=result.ok,
        latency_ms=result.latency_ms,
        error=result.error,
        details=result.details,
    )


@router.post("", response_model=ToolResponse, status_code=201)
async def register_tool(
    body: ToolRegistration,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Register a new tool for the tenant."""
    tenant_id = _tenant_id(request)
    # SSRF guard: validate endpoint_url before writing to the database
    if body.endpoint_url:
        try:
            _validate_tool_url(body.endpoint_url)
        except SSRFError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid endpoint_url: {exc}")
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
    if body.endpoint_url:
        try:
            _validate_tool_url(body.endpoint_url)
        except SSRFError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid endpoint_url: {exc}")
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
