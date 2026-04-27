"""Built-in CRM tool handlers — Twenty CRM integration.

Tools exposed to agents:
  - crm_lookup           Find a person by email / phone / id
  - crm_search           Free-form search across people (name, company, etc.)
  - crm_update           Update fields on an existing person
  - crm_create_person    Create a new person record
  - crm_create_company   Create a new company record
  - crm_create_note      Attach a note to a person/company/opportunity

All handlers route through TwentyClient which provides:
  - workspace-scoped URL resolution (subdomain routing or shared internal URL)
  - retry on 5xx / connection errors with exponential backoff
  - idempotency-key pass-through on POST/PATCH
  - shared httpx.AsyncClient pool per worker process
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared HTTP client
# ---------------------------------------------------------------------------

_shared_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()


async def _get_http_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        async with _client_lock:
            if _shared_client is None or _shared_client.is_closed:
                _shared_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(connect=3.0, read=10.0, write=10.0, pool=5.0),
                    limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
                )
    return _shared_client


async def shutdown_http_client() -> None:
    global _shared_client
    if _shared_client and not _shared_client.is_closed:
        await _shared_client.aclose()
    _shared_client = None


# ---------------------------------------------------------------------------
# Twenty client
# ---------------------------------------------------------------------------


class TwentyError(Exception):
    """Raised for non-recoverable Twenty CRM errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class TwentyClient:
    """Thin wrapper over Twenty's REST API with retry + workspace scoping."""

    def __init__(self, api_url: str, api_key: str, idempotency_key: Optional[str] = None):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.idempotency_key = idempotency_key

    def _headers(self, mutation: bool) -> dict:
        h = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if mutation and self.idempotency_key:
            h["Idempotency-Key"] = self.idempotency_key
        return h

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> dict:
        url = f"{self.api_url}{path}"
        client = await _get_http_client()
        last_exc: Optional[Exception] = None

        for attempt in range(3):
            try:
                resp = await client.request(
                    method,
                    url,
                    headers=self._headers(mutation=method.upper() in ("POST", "PATCH", "DELETE", "PUT")),
                    params=params,
                    json=json,
                )

                if resp.status_code == 401:
                    raise TwentyError("Invalid Twenty CRM API key.", 401)
                if resp.status_code == 403:
                    raise TwentyError("Twenty CRM API key lacks permission for this operation.", 403)
                if resp.status_code == 404:
                    return {"_not_found": True}
                if 500 <= resp.status_code < 600:
                    last_exc = TwentyError(f"Twenty server error: {resp.status_code}", resp.status_code)
                    await asyncio.sleep(0.2 * (2 ** attempt))
                    continue
                if resp.status_code >= 400:
                    raise TwentyError(
                        f"Twenty error {resp.status_code}: {resp.text[:200]}",
                        resp.status_code,
                    )

                if not resp.content:
                    return {}
                try:
                    return resp.json()
                except ValueError:
                    raise TwentyError(f"Twenty returned non-JSON response: {resp.text[:200]}")

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.PoolTimeout) as exc:
                last_exc = exc
                await asyncio.sleep(0.2 * (2 ** attempt))
                continue
            except TwentyError:
                raise

        raise TwentyError(f"Twenty CRM unreachable after retries: {last_exc}")

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    async def get(self, path: str, params: Optional[dict] = None) -> dict:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, json: dict) -> dict:
        return await self._request("POST", path, json=json)

    async def patch(self, path: str, json: dict) -> dict:
        return await self._request("PATCH", path, json=json)


# ---------------------------------------------------------------------------
# Workspace / URL resolution
# ---------------------------------------------------------------------------


async def _resolve_api_url(tenant_config: dict, db) -> Optional[str]:
    """Resolve the Twenty REST base URL for the active workspace.

    Resolution order:
      1. tenant_config.twenty_api_url (explicit per-tenant override)
      2. settings.TWENTY_INTERNAL_API_URL (shared internal Docker URL — most prod deployments)
      3. Subdomain-routed URL (only if TWENTY_USE_SUBDOMAIN_ROUTING=true and workspace_id resolves)
    """
    explicit = tenant_config.get("twenty_api_url")
    if explicit:
        return explicit.rstrip("/")

    if settings.TWENTY_INTERNAL_API_URL and not settings.TWENTY_USE_SUBDOMAIN_ROUTING:
        return settings.TWENTY_INTERNAL_API_URL.rstrip("/")

    workspace_id = tenant_config.get("crm_workspace_id")
    if not (settings.TWENTY_USE_SUBDOMAIN_ROUTING and workspace_id and db):
        return settings.TWENTY_INTERNAL_API_URL.rstrip("/") if settings.TWENTY_INTERNAL_API_URL else None

    from sqlalchemy import text
    try:
        res = await db.execute(
            text("SELECT subdomain FROM tenant_crm_workspaces WHERE workspace_id = :wid"),
            {"wid": workspace_id},
        )
        subdomain = res.scalar()
        if subdomain:
            return f"http://{subdomain}.{settings.TWENTY_PUBLIC_DOMAIN}/rest"
    except Exception as e:
        logger.error("crm_workspace_resolution_failed", error=str(e))

    return settings.TWENTY_INTERNAL_API_URL.rstrip("/") if settings.TWENTY_INTERNAL_API_URL else None


async def _build_client(tenant_config: dict) -> tuple[Optional[TwentyClient], Optional[dict]]:
    """Returns (client, error_dict). On failure returns (None, error_dict)."""
    skip = str(tenant_config.get("dev_mode_skip_crm", "false")).lower() == "true"
    if skip:
        return None, {"_skip": True}

    api_key = tenant_config.get("twenty_api_key", "")
    if not api_key:
        return None, {
            "error": "Twenty CRM API key is missing from tenant configuration.",
            "status": "unconfigured",
        }

    api_url = await _resolve_api_url(tenant_config, tenant_config.get("db"))
    if not api_url:
        return None, {
            "error": "Twenty CRM URL could not be resolved. Set TWENTY_INTERNAL_API_URL or per-tenant twenty_api_url.",
            "status": "unconfigured",
        }

    return TwentyClient(
        api_url=api_url,
        api_key=api_key,
        idempotency_key=tenant_config.get("idempotency_key"),
    ), None


# ---------------------------------------------------------------------------
# Twenty schema mapping helpers
# ---------------------------------------------------------------------------


def _build_name(name: Optional[str]) -> Optional[dict]:
    """Twenty stores name as {firstName, lastName}.
    For multi-word names we put the first token as firstName and the rest as lastName,
    which preserves middle names as part of lastName instead of dropping them.
    """
    if not name:
        return None
    name = name.strip()
    if not name:
        return None
    parts = name.split(" ", 1)
    if len(parts) == 1:
        return {"firstName": parts[0], "lastName": ""}
    return {"firstName": parts[0], "lastName": parts[1]}


def _build_emails(email: Optional[str]) -> Optional[dict]:
    if not email:
        return None
    return {"primaryEmail": email, "additionalEmails": []}


def _build_phones(phone: Optional[str]) -> Optional[dict]:
    """Twenty's Phones composite field. We send only primaryPhoneNumber;
    country code and calling code are optional and Twenty parses E.164 if missing.
    """
    if not phone:
        return None
    return {
        "primaryPhoneNumber": phone,
        "primaryPhoneCountryCode": "",
        "primaryPhoneCallingCode": "",
        "additionalPhones": [],
    }


def _flatten_person(record: dict) -> dict:
    """Convert a Twenty person record into the agent-facing customer schema."""
    if not record:
        return {}

    name_field = record.get("name")
    if isinstance(name_field, dict):
        full_name = f"{name_field.get('firstName', '')} {name_field.get('lastName', '')}".strip()
    else:
        full_name = (name_field or "").strip()

    emails = record.get("emails")
    if isinstance(emails, dict):
        email = emails.get("primaryEmail", "") or ""
    else:
        email = record.get("email", "") or ""

    phones = record.get("phones")
    if isinstance(phones, dict):
        phone = phones.get("primaryPhoneNumber", "") or ""
    else:
        phone = record.get("phone", "") or ""

    return {
        "id": record.get("id"),
        "name": full_name,
        "email": email,
        "phone": phone,
        "notes": record.get("notes", ""),
        "company_id": record.get("companyId"),
        "created_at": record.get("createdAt"),
        "updated_at": record.get("updatedAt"),
    }


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

CRM_LOOKUP_SCHEMA = {
    "type": "object",
    "properties": {
        "phone": {"type": "string"},
        "email": {"type": "string"},
        "customer_id": {"type": "string"},
    },
}

CRM_LOOKUP_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "customer": {"type": "object"},
    },
}

CRM_SEARCH_SCHEMA = {
    "type": "object",
    "required": ["query"],
    "properties": {
        "query": {"type": "string", "description": "Free-text search term (matches on name, email, phone)"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 5},
    },
}

CRM_UPDATE_SCHEMA = {
    "type": "object",
    "required": ["customer_id"],
    "properties": {
        "customer_id": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "phone": {"type": "string"},
        "notes": {"type": "string"},
    },
}

CRM_CREATE_PERSON_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "email": {"type": "string"},
        "phone": {"type": "string"},
        "company_id": {"type": "string", "description": "Optional Twenty company UUID to link to"},
    },
}

CRM_CREATE_COMPANY_SCHEMA = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "name": {"type": "string"},
        "domain": {"type": "string"},
        "employees": {"type": "integer"},
    },
}

CRM_CREATE_NOTE_SCHEMA = {
    "type": "object",
    "required": ["body"],
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string"},
        "person_id": {"type": "string"},
        "company_id": {"type": "string"},
        "opportunity_id": {"type": "string"},
    },
}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def handle_crm_lookup(parameters: dict, tenant_config: dict) -> dict:
    """Find a person in Twenty by id, email, or phone."""
    identifier = (
        parameters.get("customer_id")
        or parameters.get("email")
        or parameters.get("phone")
    )
    if not identifier:
        return {"found": False, "customer": None, "error": "Provide customer_id, email, or phone."}

    client, err = await _build_client(tenant_config)
    if err:
        if err.get("_skip"):
            return {
                "found": True,
                "customer": {
                    "id": "dev-123",
                    "name": "Dev User",
                    "email": parameters.get("email", "dev@example.com"),
                    "phone": parameters.get("phone", "555-0000"),
                    "notes": "Dev mode dummy record",
                },
            }
        return {"found": False, **err}

    try:
        if parameters.get("customer_id"):
            data = await client.get(f"/people/{parameters['customer_id']}")
            if data.get("_not_found"):
                return {"found": False, "customer": None}
            record = data.get("data", {}).get("person") or data.get("data") or data
        else:
            if parameters.get("email"):
                params = {"filter": f"emails.primaryEmail[eq]:{parameters['email']}"}
            else:
                params = {"filter": f"phones.primaryPhoneNumber[eq]:{parameters['phone']}"}
            params["limit"] = "1"
            data = await client.get("/people", params=params)
            items = (data.get("data", {}) or {}).get("people") or data.get("data") or []
            record = items[0] if items else None

        if not record:
            return {"found": False, "customer": None}
        return {"found": True, "customer": _flatten_person(record)}

    except TwentyError as exc:
        logger.error("crm_lookup_failed", error=str(exc), status=exc.status_code)
        return {"found": False, "error": str(exc)}


async def handle_crm_search(parameters: dict, tenant_config: dict) -> dict:
    """Free-text search across people. Twenty's REST API supports `?filter=name.firstName[ilike]:...`
    but no full-text endpoint, so we OR together a few common fields.
    """
    query = (parameters.get("query") or "").strip()
    if not query:
        return {"results": [], "error": "query is required"}

    limit = max(1, min(int(parameters.get("limit", 5)), 25))

    client, err = await _build_client(tenant_config)
    if err:
        if err.get("_skip"):
            return {"results": [], "status": "skipped_dev_mode"}
        return {"results": [], **err}

    pattern = f"%{query}%"
    # Run three queries in parallel — name, email, phone — then dedupe by id.
    queries = [
        {"filter": f"name.firstName[ilike]:{pattern}", "limit": str(limit)},
        {"filter": f"name.lastName[ilike]:{pattern}", "limit": str(limit)},
        {"filter": f"emails.primaryEmail[ilike]:{pattern}", "limit": str(limit)},
    ]

    try:
        results = await asyncio.gather(
            *[client.get("/people", params=q) for q in queries],
            return_exceptions=True,
        )
    except Exception as exc:
        logger.error("crm_search_failed", error=str(exc))
        return {"results": [], "error": str(exc)}

    seen: set[str] = set()
    flat: list[dict] = []
    for r in results:
        if isinstance(r, Exception):
            continue
        items = (r.get("data", {}) or {}).get("people") or r.get("data") or []
        for rec in items:
            rid = rec.get("id")
            if rid and rid not in seen:
                seen.add(rid)
                flat.append(_flatten_person(rec))
                if len(flat) >= limit:
                    break
        if len(flat) >= limit:
            break

    return {"results": flat, "count": len(flat)}


async def handle_crm_update(parameters: dict, tenant_config: dict) -> dict:
    """Update an existing person. Only supplied fields are sent."""
    customer_id = parameters.get("customer_id")
    if not customer_id:
        return {"success": False, "error": "customer_id is required."}

    client, err = await _build_client(tenant_config)
    if err:
        if err.get("_skip"):
            return {"success": True, "status": "skipped_dev_mode"}
        return {"success": False, **err}

    payload: dict[str, Any] = {}
    if (n := _build_name(parameters.get("name"))) is not None:
        payload["name"] = n
    if (e := _build_emails(parameters.get("email"))) is not None:
        payload["emails"] = e
    if (p := _build_phones(parameters.get("phone"))) is not None:
        payload["phones"] = p
    if "notes" in parameters:
        # Twenty's `notes` on a person is a free-text column on some workspaces; on others
        # notes are first-class entities. We attempt the field first and on 400 fall back
        # to creating a Note via crm_create_note.
        payload["notes"] = parameters["notes"]

    if not payload:
        return {"success": False, "error": "No updatable fields provided."}

    try:
        data = await client.patch(f"/people/{customer_id}", json=payload)
        if data.get("_not_found"):
            return {"success": False, "error": f"Customer {customer_id} not found."}
        return {"success": True, "status": "updated"}
    except TwentyError as exc:
        # If notes column doesn't exist on this workspace, retry without it and
        # log the note as a separate Note entity.
        if exc.status_code == 400 and "notes" in payload:
            note_text = payload.pop("notes")
            try:
                if payload:
                    await client.patch(f"/people/{customer_id}", json=payload)
                await handle_crm_create_note(
                    {"body": note_text, "person_id": customer_id},
                    tenant_config,
                )
                return {"success": True, "status": "updated_with_separate_note"}
            except TwentyError as inner:
                return {"success": False, "error": str(inner)}
        logger.error("crm_update_failed", error=str(exc), status=exc.status_code)
        return {"success": False, "error": str(exc)}


async def handle_crm_create_person(parameters: dict, tenant_config: dict) -> dict:
    """Create a new person record."""
    client, err = await _build_client(tenant_config)
    if err:
        if err.get("_skip"):
            return {"success": True, "id": "dev-new-person", "status": "skipped_dev_mode"}
        return {"success": False, **err}

    payload: dict[str, Any] = {}
    if (n := _build_name(parameters.get("name"))) is not None:
        payload["name"] = n
    if (e := _build_emails(parameters.get("email"))) is not None:
        payload["emails"] = e
    if (p := _build_phones(parameters.get("phone"))) is not None:
        payload["phones"] = p
    if parameters.get("company_id"):
        payload["companyId"] = parameters["company_id"]

    if not payload:
        return {"success": False, "error": "Provide at least one of name, email, or phone."}

    try:
        data = await client.post("/people", json=payload)
        record = (data.get("data") or {}).get("createPerson") or data.get("data") or data
        return {"success": True, "id": record.get("id"), "customer": _flatten_person(record)}
    except TwentyError as exc:
        logger.error("crm_create_person_failed", error=str(exc))
        return {"success": False, "error": str(exc)}


async def handle_crm_create_company(parameters: dict, tenant_config: dict) -> dict:
    """Create a new company record."""
    name = (parameters.get("name") or "").strip()
    if not name:
        return {"success": False, "error": "name is required."}

    client, err = await _build_client(tenant_config)
    if err:
        if err.get("_skip"):
            return {"success": True, "id": "dev-new-company", "status": "skipped_dev_mode"}
        return {"success": False, **err}

    payload: dict[str, Any] = {"name": name}
    if parameters.get("domain"):
        payload["domainName"] = {"primaryLinkUrl": parameters["domain"]}
    if parameters.get("employees") is not None:
        payload["employees"] = int(parameters["employees"])

    try:
        data = await client.post("/companies", json=payload)
        record = (data.get("data") or {}).get("createCompany") or data.get("data") or data
        return {"success": True, "id": record.get("id"), "company": record}
    except TwentyError as exc:
        logger.error("crm_create_company_failed", error=str(exc))
        return {"success": False, "error": str(exc)}


async def handle_crm_create_note(parameters: dict, tenant_config: dict) -> dict:
    """Create a Note and attach it to a person/company/opportunity if provided.

    Twenty models notes as first-class entities with `noteTargets` linking them to records.
    We create the note, then a note target if a parent id is supplied. The link is
    best-effort: if the target call fails we still return success on the note itself.
    """
    body = parameters.get("body")
    if not body:
        return {"success": False, "error": "body is required."}

    client, err = await _build_client(tenant_config)
    if err:
        if err.get("_skip"):
            return {"success": True, "id": "dev-new-note", "status": "skipped_dev_mode"}
        return {"success": False, **err}

    note_payload = {
        "title": parameters.get("title") or "Call note",
        "body": body,
    }

    try:
        note_data = await client.post("/notes", json=note_payload)
        note = (note_data.get("data") or {}).get("createNote") or note_data.get("data") or note_data
        note_id = note.get("id")
        if not note_id:
            return {"success": False, "error": "Twenty did not return note id."}
    except TwentyError as exc:
        logger.error("crm_create_note_failed", error=str(exc))
        return {"success": False, "error": str(exc)}

    target_payload: Optional[dict] = None
    if parameters.get("person_id"):
        target_payload = {"noteId": note_id, "personId": parameters["person_id"]}
    elif parameters.get("company_id"):
        target_payload = {"noteId": note_id, "companyId": parameters["company_id"]}
    elif parameters.get("opportunity_id"):
        target_payload = {"noteId": note_id, "opportunityId": parameters["opportunity_id"]}

    linked = False
    if target_payload:
        try:
            await client.post("/noteTargets", json=target_payload)
            linked = True
        except TwentyError as exc:
            # The note exists; the link failed. Caller can retry linking.
            logger.warning("crm_note_target_link_failed", note_id=note_id, error=str(exc))

    return {"success": True, "id": note_id, "linked": linked}
