"""
Console API — tenant-scoped activity and audit log viewer.

Accessible to any authenticated tenant user (owner, admin, developer).
All data is filtered to the requesting tenant — no cross-tenant access.

Endpoints:
  GET /console/audit-logs  — audit trail for this tenant
  GET /console/activity    — aggregated recent activity (sessions + events)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_tenant_db, get_current_tenant
from app.services.audit_service import list_audit_logs

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/console")


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
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """
    Return audit logs scoped to the requesting tenant.
    Accessible to tenant_owner, tenant_admin, and developer roles.
    """
    tenant_id = _require_tenant(request)

    since_dt = datetime.fromisoformat(since) if since else None
    until_dt = datetime.fromisoformat(until) if until else None

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
    )


# ---------------------------------------------------------------------------
# Activity feed — recent sessions + agent events
# ---------------------------------------------------------------------------

@router.get("/activity")
async def get_tenant_activity(
    request: Request,
    agent_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
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

    # Fetch recent audit events as the "event feed"
    recent_events = await list_audit_logs(
        db,
        tenant_id=tenant_id,
        page=1,
        per_page=20,
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
):
    """Return minimal agent list (id + name) for the console filter bar."""
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
