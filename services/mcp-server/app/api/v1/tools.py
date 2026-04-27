from __future__ import annotations

import time
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.integrations.base import ACTION_REGISTRY
from app.schemas.mcp import ToolAuthConfig, ToolRegistration, ToolResponse, ToolUpdate, ToolTestExecutionRequest
from app.services.tool_executor import SSRFError, _validate_tool_url
from app.services.tool_registry import ToolRegistry

from app.api.v1.internal_auth import verify_internal_token

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/tools", dependencies=[Depends(verify_internal_token)])


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
                        "currency": {"type": "string", "default": "USD"},
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
        "voice_capable": True,
        "pci_method": "hosted_page",
        "pci_compliant": True,
        "channel_support": ["voice", "chat"],
        "config_schema": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string", "description": "Moneris Store ID"},
                "api_token": {"type": "string", "description": "Moneris API Token"},
                "checkout_id": {"type": "string", "description": "Moneris Checkout ID (MCO)"},
                "environment": {"type": "string", "description": "qa or live"}
            },
            "required": ["store_id", "api_token", "checkout_id"]
        },
        "credentials": [
            {"field": "store_id", "label": "Store ID", "type": "text"},
            {"field": "api_token", "label": "API Token", "type": "password"},
            {"field": "checkout_id", "label": "Checkout ID (MCO)", "type": "text"},
            {"field": "environment", "label": "Environment (qa/live)", "type": "text"}
        ],
        "tools": [
            {
                "name": "moneris_create_payment_link",
                "description": "Generate a secure Moneris Checkout link for the customer.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "string"},
                        "description": {"type": "string"},
                        "order_id": {"type": "string"}
                    },
                    "required": ["amount"]
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
        "voice_capable": True,
        "pci_method": "hosted_page",
        "pci_compliant": True,
        "channel_support": ["voice", "chat"],
        "config_schema": {
            "type": "object",
            "properties": {
                "api_token": {"type": "string", "description": "Helcim API Token"}
            },
            "required": ["api_token"]
        },
        "credentials": [
            {"field": "api_token", "label": "API Token", "type": "password"}
        ],
        "tools": [
            {
                "name": "helcim_create_payment_link",
                "description": "Generate a secure Helcim Pay checkout link for the customer.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "number"},
                        "currency": {"type": "string", "default": "CAD"},
                        "invoice_number": {"type": "string"}
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
        ]},
    {
        "id": "twenty_crm",
        "name": "Twenty CRM",
        "description": "Self-hosted CRM. Look up customers, log calls as notes, and track relationships.",
        "category": "crm",
        "requires_config": True,
        "is_builtin": True,
        "config_schema": {
            "type": "object",
            "properties": {
                "twenty_api_key": {"type": "string", "description": "Twenty workspace API key"},
                "twenty_api_url": {"type": "string", "description": "Optional override (e.g. https://crm.example.com/rest)"},
            },
            "required": ["twenty_api_key"],
        },
        "credentials": [
            {"field": "twenty_api_key", "label": "API Key", "type": "password"},
            {"field": "twenty_api_url", "label": "API URL Override (optional)", "type": "text"},
        ],
        "tools": [
            {
                "name": "crm_lookup",
                "description": "Find a person in the CRM by phone, email, or id.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "phone": {"type": "string"},
                        "email": {"type": "string"},
                        "customer_id": {"type": "string"},
                    },
                },
            },
            {
                "name": "crm_search",
                "description": "Free-text search across CRM contacts.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 5},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "crm_update",
                "description": "Update fields on an existing CRM contact.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string"},
                        "name": {"type": "string"},
                        "email": {"type": "string"},
                        "phone": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": ["customer_id"],
                },
            },
            {
                "name": "crm_create_person",
                "description": "Create a new contact in the CRM.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string"},
                        "phone": {"type": "string"},
                        "company_id": {"type": "string"},
                    },
                },
            },
            {
                "name": "crm_create_company",
                "description": "Create a new company in the CRM.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "domain": {"type": "string"},
                        "employees": {"type": "integer"},
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "crm_create_note",
                "description": "Attach a note (call summary, follow-up, etc.) to a contact, company, or opportunity.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "person_id": {"type": "string"},
                        "company_id": {"type": "string"},
                        "opportunity_id": {"type": "string"},
                    },
                    "required": ["body"],
                },
            },
        ],
    },
]


def _tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


async def _tenant_db(
    tenant_id: str = Depends(_tenant_id),
):
    async for session in get_db(tenant_id):
        yield session




class SchemasRequest(BaseModel):
    tenant_id: str
    tool_names: list[str]


@router.post("/schemas")
async def get_tool_schemas(
    body: SchemasRequest,
    request: Request,
    db: AsyncSession = Depends(_tenant_db),
    tenant_id: str = Depends(_tenant_id),
) -> list[dict[str, Any]]:
    """
    Return OpenAI function-calling schemas for the requested tools.
    The orchestrator calls this so Gemini knows which functions it can invoke.
    """
    registry = ToolRegistry(db)
    schemas: list[dict[str, Any]] = []

    for tool_name in body.tool_names:
        tool = await registry.get_tool(tenant_id, tool_name)
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
    db: AsyncSession = Depends(_tenant_db),
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


@router.post("/upsert-builtin", response_model=ToolResponse, status_code=200)
async def upsert_builtin_tool(
    body: ToolRegistration,
    request: Request,
    db: AsyncSession = Depends(_tenant_db),
):
    """Create or update a built-in tool registration.

    Called internally by ai-orchestrator's WorkflowRegistry when a workflow is
    activated/deactivated. Uses the tenant identity resolved by middleware and
    requires the internal API key.

    - If no tool with ``body.name`` exists for the tenant → creates it.
    - If one already exists → updates description, schemas, metadata, and
      is_active without changing the tool's UUID.
    """

    tenant_id = _tenant_id(request)
    registry = ToolRegistry(db)

    existing = await registry.get_tool(tenant_id, body.name)
    if existing is None:
        # Create
        if body.endpoint_url:
            try:
                _validate_tool_url(body.endpoint_url)
            except SSRFError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid endpoint_url: {exc}")
        try:
            tool = await registry.register_tool(tenant_id, body)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    else:
        # Update in-place (description, schemas, metadata, active flag)
        update = ToolUpdate(
            description=body.description,
            input_schema=body.input_schema,
            output_schema=body.output_schema,
            is_active=body.tool_metadata.get("is_active", True),
            tool_metadata=body.tool_metadata,
        )
        try:
            tool = await registry.update_tool(tenant_id, body.name, update)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    await db.commit()
    await db.refresh(tool)
    return tool


@router.get("", response_model=list[ToolResponse])
async def list_tools(
    request: Request,
    category: str | None = None,
    db: AsyncSession = Depends(_tenant_db),
):
    """List all active tools for the tenant."""
    tenant_id = _tenant_id(request)
    registry = ToolRegistry(db)
    return await registry.list_tools(tenant_id, category=category)


@router.get("/{tool_name}", response_model=ToolResponse)
async def get_tool(
    tool_name: str,
    request: Request,
    db: AsyncSession = Depends(_tenant_db),
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
    db: AsyncSession = Depends(_tenant_db),
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
    db: AsyncSession = Depends(_tenant_db),
):
    """Permanently delete a tool configuration."""
    tenant_id = _tenant_id(request)
    registry = ToolRegistry(db)
    try:
        await registry.hard_delete_tool(tenant_id, tool_name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()


@router.post("/test-execute")
async def test_execute_tool(
    body: ToolTestExecutionRequest,
    request: Request,
    db: AsyncSession = Depends(_tenant_db),
) -> dict[str, Any]:
    """Test execute a tool with the provided configuration and parameters."""
    tenant_id = _tenant_id(request)
    
    # Need to simulate execution without saving to the DB
    # We will build a dummy tool model instance from the registration payload
    from app.models.tool import Tool
    import uuid
    from app.services.tool_executor import ToolExecutor
    from app.schemas.mcp import MCPToolCall
    
    redis = getattr(request.app.state, "redis", None)
    executor = ToolExecutor(db=db, redis=redis)
    
    # Build a transient tool object
    tool = Tool(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant_id),
        name=body.tool_config.name,
        description=body.tool_config.description,
        category=body.tool_config.category,
        input_schema=body.tool_config.input_schema,
        output_schema=body.tool_config.output_schema,
        endpoint_url=body.tool_config.endpoint_url,
        auth_config=body.tool_config.auth_config,
        rate_limit_per_minute=body.tool_config.rate_limit_per_minute,
        timeout_seconds=body.tool_config.timeout_seconds,
        is_active=True,
        is_builtin=body.tool_config.is_builtin,
        tool_metadata=body.tool_config.tool_metadata,
    )
    
    # We shouldn't invoke the standard executor flow because it checks DB and writes history.
    # Instead, we directly use the test_execute method we're about to add to ToolExecutor.
    tool_call = MCPToolCall(
        tool_name=tool.name,
        parameters=body.parameters,
        session_id="test_execution",
        trace_id="test_trace"
    )
    
    try:
        result = await executor.test_execute(tenant_id, tool, tool_call)
    except Exception as e:
        logger.error("tool_test_execution_failed", error=str(e), exc_info=e)
        raise HTTPException(status_code=400, detail=str(e))
        
    return result.model_dump()
