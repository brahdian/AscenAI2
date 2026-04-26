"""
Console API — tenant-scoped activity and audit log viewer.

Accessible to any authenticated tenant user (owner, admin, developer).
All data is filtered to the requesting tenant — no cross-tenant access.

Endpoints:
  GET /console/audit-logs  — audit trail for this tenant
  GET /console/activity    — aggregated recent activity (sessions + events)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rbac import _ROLE_LEVELS, require_role
from app.core.security import get_current_tenant, get_tenant_db
from app.services.audit_service import audit_log, list_audit_logs
from app.utils.pii import anonymize_identifier, mask_sensitive_data

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/console")





def sanitize_csv_field(val: Any) -> str:
    """Escape potential formula injection triggers in CSV fields."""
    s = str(val) if val is not None else ""
    # If the field starts with a formula trigger, prefix with a single quote.
    if s and s[0] in ("=", "+", "-", "@"):
        return f"'{s}"
    return s




def _require_tenant(request: Request) -> str:
    """Return the authenticated tenant_id or raise 401."""
    tid = getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return tid


# ---------------------------------------------------------------------------
# Audit logs (tenant-scoped)
# ---------------------------------------------------------------------------

@router.get("/audit-logs")
async def get_tenant_audit_logs(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    category: Optional[str] = Query(None, pattern="^(auth|user|tenant|agent|billing|admin|data|api_key|general|)$"),
    action: Optional[str] = Query(None, max_length=100),
    status: Optional[str] = Query(None, pattern="^(success|failure|)$"),
    since: Optional[str] = Query(None, description="ISO 8601 datetime"),
    until: Optional[str] = Query(None, description="ISO 8601 datetime"),
    silent: bool = Query(False, description="If true, skip self-auditing (used for polling)"),
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
    user_role: str = require_role("admin"),
):



    """
    Return audit logs scoped to the requesting tenant.
    Accessible to owner, admin, and developer roles.
    """
    tenant_id = _require_tenant(request)

    try:
        since_dt = datetime.fromisoformat(since).replace(tzinfo=timezone.utc) if since else None
        until_dt = datetime.fromisoformat(until).replace(tzinfo=timezone.utc) if until else None

        
        # Range cap: Max 1 year (366 days) to prevent DoS via massive index scans
        if since_dt and until_dt and (until_dt - since_dt) > timedelta(days=366):
            raise HTTPException(status_code=400, detail="Date range cannot exceed 366 days. Please refine your filter.")
    except ValueError:

        raise HTTPException(status_code=400, detail="Invalid date format. Please use ISO 8601.")


    # Audit the Auditor: log that logs were viewed (unless silent polling)
    if not silent:
        is_super_admin = _ROLE_LEVELS.get(user_role, 0) >= _ROLE_LEVELS.get("super_admin", 4)
        await audit_log(
            db,
            action="console.logs.viewed",
            request=request,
            category="admin",
            details={
                "page": page,
                "is_support_access": is_super_admin,
                "filters": {
                    "category": category,
                    "action": action,
                    "status": status,
                    "since": since,
                    "until": until
                }
            }
        )



    # Contextual masking: only super_admin sees raw IPs in the UI
    is_super_admin = _ROLE_LEVELS.get(user_role, 0) >= _ROLE_LEVELS.get("super_admin", 4)

    return await list_audit_logs(
        db,
        tenant_id=tenant_id,
        action_prefix=action or None,
        category=category or None,
        status=status or None,
        since=since_dt,
        until=until_dt,
        page=page,
        per_page=per_page,
        mask_pii=not is_super_admin,
    )


# ---------------------------------------------------------------------------
# Audit log Export (Owner only, Full Data)
# ---------------------------------------------------------------------------

@router.get("/export")
async def get_tenant_audit_export(
    request: Request,
    action: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    reason: str = Query(..., min_length=5, description="Justification for this export"),
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
    _role: str = require_role("owner"),
):
    """
    Export audit logs as CSV. Restricted to Owner+.
    Contains full (unmasked) IP addresses for forensic reporting.
    """
    tenant_id = _require_tenant(request)
    
    # ── Forensic Export Throtte (Phase 16) ──────────────────────────────────
    # Prevents resource exhaustion. Max 1 export per minute per tenant.
    try:
        from app.core.redis_client import get_redis
        redis = await get_redis()
        if redis:
            throttle_key = f"throttle:export:{tenant_id}"
            if await redis.get(throttle_key):
                raise HTTPException(status_code=429, detail="Too many export requests. Please wait 60 seconds.")
            await redis.setex(throttle_key, 60, "1")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("export_throttle_fail_open", error=str(exc))

    try:

        since_dt = datetime.fromisoformat(since).replace(tzinfo=timezone.utc) if since else None
        until_dt = datetime.fromisoformat(until).replace(tzinfo=timezone.utc) if until else None


        # Range cap: Max 1 year (366 days)
        if since_dt and until_dt and (until_dt - since_dt) > timedelta(days=366):
            raise HTTPException(status_code=400, detail="Export range cannot exceed 366 days.")
    except ValueError:

        raise HTTPException(status_code=400, detail="Invalid date format. Please use ISO 8601.")

    # Audit the Export
    await audit_log(
        db,
        action="console.logs.exported",
        request=request,
        category="admin",
        details={
            "filters": {"category": category, "action": action, "status": status}
        }
    )

    # 1. Fetch total count first (to settle the X-Export-Truncated header)
    from sqlalchemy import func as sqlfunc

    from app.services.audit_service import _build_audit_query
    
    count_q = select(sqlfunc.count()).select_from(
        _build_audit_query(
            tenant_id=tenant_id,
            action_prefix=action or None,
            category=category or None,
            status=status or None,
            since=since_dt,
            until=until_dt,
        ).subquery()
    )
    total_res = await db.execute(count_q)
    total = total_res.scalar_one()

    MAX_EXPORT = 1000
    is_truncated = total > MAX_EXPORT

    # 2. Start Streaming Generator
    from app.services.audit_service import stream_audit_logs
    
    async def csv_generator():
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow(["Time", "Actor", "Role", "Action", "Category", "Resource", "Status", "IP", "Details"])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        # Stream row-by-row from DB
        async for item in stream_audit_logs(
            db,
            tenant_id=tenant_id,
            action_prefix=action or None,
            category=category or None,
            status=status or None,
            since=since_dt,
            until=until_dt,
            limit=MAX_EXPORT,
            mask_pii=False,
            request=request,               # Metadata context (Phase 12)
            export_reason=reason,          # Purpose binding (Phase 12)
        ):

            # Resource column logic
            res = f"{item['resource_type']}/{item['resource_id']}" if item["resource_id"] else item["resource_type"]
            
            writer.writerow([
                sanitize_csv_field(item["created_at"]),
                sanitize_csv_field(item["actor_email"] or "system"),
                sanitize_csv_field(item["actor_role"] or ""),
                sanitize_csv_field(item["action"]),
                sanitize_csv_field(item["category"]),
                sanitize_csv_field(res),
                sanitize_csv_field(item["status"]),
                sanitize_csv_field(item["ip_address"]),
                sanitize_csv_field(item["details"]),
            ])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

        # 3. Final Integrity Marker (Phase 11)
        # Allows the operator to verify that the stream finished successfully.
        writer.writerow([])
        writer.writerow(["# END OF AUDIT EXPORT #", f"Generated: {datetime.now(timezone.utc).isoformat()}"])
        yield output.getvalue()



    headers = {
        "Content-Disposition": f"attachment; filename=audit_export_{datetime.now().date()}.csv"
    }
    if is_truncated:
        headers["X-Export-Truncated"] = "true"
        
    return StreamingResponse(
        csv_generator(),
        media_type="text/csv",
        headers=headers
    )





# ---------------------------------------------------------------------------
# Activity feed — recent sessions + agent events
# ---------------------------------------------------------------------------

@router.get("/activity")
async def get_tenant_activity(
    request: Request,
    agent_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    silent: bool = Query(False, description="If true, skip self-auditing"),
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
    user_role: str = require_role("admin"),
):


    """
    Aggregated recent activity for the tenant: recent sessions, message counts,
    tool call results, and error events.  Proxied from the orchestrator.
    """
    tenant_id = _require_tenant(request)

    params: dict = {"limit": limit, "tenant_id": tenant_id}
    if agent_id:
        params["agent_id"] = agent_id

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.AI_ORCHESTRATOR_URL}/api/v1/sessions",
                params=params,
                headers={
                    "X-Tenant-ID": tenant_id,
                    "X-Internal-Key": settings.INTERNAL_API_KEY,
                },
            )
            if resp.status_code == 200:
                sessions_data = resp.json()
            else:
                sessions_data = {"sessions": [], "total": 0}
    except Exception as exc:
        logger.warning("console_sessions_fetch_failed", error=str(exc))
        sessions_data = {"sessions": [], "total": 0}

    # Audit the Activity View (unless silent polling)
    if not silent:
        is_super_admin = _ROLE_LEVELS.get(user_role, 0) >= _ROLE_LEVELS.get("super_admin", 4)
        await audit_log(
            db,
            action="console.activity.viewed",
            request=request,
            category="admin",
            details={
                "agent_id": agent_id, 
                "limit": limit,
                "is_support_access": is_super_admin
            }
        )


    # Contextual masking: only super_admin sees raw identifiers and IPs
    is_super_admin = _ROLE_LEVELS.get(user_role, 0) >= _ROLE_LEVELS.get("super_admin", 4)
    
    if not is_super_admin:
        # Mask identifiers and metadata in the session list
        if "sessions" in sessions_data:
            for s in sessions_data["sessions"]:
                if s.get("customer_identifier"):
                    s["customer_identifier"] = anonymize_identifier(s["customer_identifier"])

                if s.get("metadata"):
                    s["metadata"] = mask_sensitive_data(s["metadata"])

    
    # Fetch recent audit events as the "event feed"
    recent_events = await list_audit_logs(
        db,
        tenant_id=tenant_id,
        page=1,
        per_page=20,
        mask_pii=not is_super_admin,
    )


    return {
        "sessions": sessions_data,
        "recent_events": recent_events["items"],
    }



# ---------------------------------------------------------------------------
# Per-agent log summary
# ---------------------------------------------------------------------------

@router.get("/agents")
async def list_tenant_agents_for_console(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
    user_role: str = require_role("developer"),
):


    """Return minimal agent list (id + name) for the console filter bar."""
    # Audit the access
    is_super_admin = _ROLE_LEVELS.get(user_role, 0) >= _ROLE_LEVELS.get("super_admin", 4)
    await audit_log(
        db,
        action="console.agents.viewed",
        request=request,
        category="admin",
        details={"is_support_access": is_super_admin}
    )


    try:

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents",
                headers={
                    "X-Tenant-ID": tenant_id,
                    "X-Internal-Key": settings.INTERNAL_API_KEY,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                agents = [{"id": str(a.get("id")), "name": a.get("name", "Unnamed")}
                          for a in (data if isinstance(data, list) else (data.get("agents", []) or []))]
                return {"agents": agents}
    except Exception as exc:
        logger.warning("console_agents_fetch_failed", error=str(exc))
    return {"agents": []}
