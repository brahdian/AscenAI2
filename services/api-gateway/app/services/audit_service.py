"""
AuditService — write and query audit log entries.

Usage (inside a route or service):
    from app.services.audit_service import audit_log

    await audit_log(
        db=db,
        request=request,
        action="agent.deleted",
        category="agent",
        resource_type="agent",
        resource_id=str(agent_id),
        details={"agent_name": agent.name},
    )
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog

logger = structlog.get_logger(__name__)


async def audit_log(
    db: AsyncSession,
    action: str,
    *,
    request: Optional[Request] = None,
    tenant_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    actor_email: Optional[str] = None,
    actor_role: Optional[str] = None,
    category: str = "general",
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    status: str = "success",
    details: Optional[dict[str, Any]] = None,
) -> None:
    """
    Persist an audit log entry.  Never raises — failures are logged but do not
    interrupt the calling request.  Audit logging must be non-blocking.
    """
    try:
        # Extract context from request if provided
        ip_address: Optional[str] = None
        user_agent: Optional[str] = None
        _tenant_id = tenant_id
        _actor_user_id = actor_user_id
        _actor_role = actor_role

        if request is not None:
            ip_address = _get_client_ip(request)
            user_agent = (request.headers.get("User-Agent") or "")[:500]
            if not _tenant_id:
                _tenant_id = getattr(request.state, "tenant_id", None)
            if not _actor_user_id:
                _actor_user_id = getattr(request.state, "user_id", None)
            if not _actor_role:
                _actor_role = getattr(request.state, "role", None)

        entry = AuditLog(
            tenant_id=_tenant_id if _tenant_id else None,
            actor_user_id=_actor_user_id if _actor_user_id else None,
            actor_email=actor_email,
            actor_role=_actor_role,
            action=action,
            category=category,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            status=status,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(entry)
        # Use flush (not commit) so the caller's transaction includes the log entry.
        # If the caller rolls back, the audit entry is also rolled back — which is
        # acceptable; we don't want ghost audit entries for operations that failed.
        await db.flush()
    except Exception as exc:
        # NEVER let audit logging break a request.
        logger.error("audit_log_write_failed", action=action, error=str(exc))


def _get_client_ip(request: Request) -> str:
    """Return the real client IP, respecting X-Forwarded-For from a trusted proxy."""
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        # X-Forwarded-For: client, proxy1, proxy2 — take the first (leftmost) IP
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def list_audit_logs(
    db: AsyncSession,
    *,
    tenant_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    action_prefix: Optional[str] = None,
    category: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    status: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    page: int = 1,
    per_page: int = 50,
) -> dict[str, Any]:
    """Query audit logs with filters. Returns paginated results."""
    query = select(AuditLog)

    if tenant_id:
        query = query.where(AuditLog.tenant_id == uuid.UUID(tenant_id))
    if actor_user_id:
        query = query.where(AuditLog.actor_user_id == uuid.UUID(actor_user_id))
    if action_prefix:
        query = query.where(AuditLog.action.like(f"{action_prefix}%"))
    if category:
        query = query.where(AuditLog.category == category)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if resource_id:
        query = query.where(AuditLog.resource_id == resource_id)
    if status:
        query = query.where(AuditLog.status == status)
    if since:
        query = query.where(AuditLog.created_at >= since)
    if until:
        query = query.where(AuditLog.created_at <= until)

    # Count total for pagination
    from sqlalchemy import func as sqlfunc
    count_q = select(sqlfunc.count()).select_from(query.subquery())
    total_res = await db.execute(count_q)
    total = total_res.scalar_one()

    # Paginate newest first
    offset = (page - 1) * per_page
    query = query.order_by(desc(AuditLog.created_at)).offset(offset).limit(per_page)
    result = await db.execute(query)
    rows = result.scalars().all()

    return {
        "items": [_serialize(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


def _serialize(log: AuditLog) -> dict[str, Any]:
    return {
        "id": str(log.id),
        "tenant_id": str(log.tenant_id) if log.tenant_id else None,
        "actor_user_id": str(log.actor_user_id) if log.actor_user_id else None,
        "actor_email": log.actor_email,
        "actor_role": log.actor_role,
        "action": log.action,
        "category": log.category,
        "resource_type": log.resource_type,
        "resource_id": log.resource_id,
        "status": log.status,
        "details": log.details,
        "ip_address": log.ip_address,
        "user_agent": log.user_agent,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }
