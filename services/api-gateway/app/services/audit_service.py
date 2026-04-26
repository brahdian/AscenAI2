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
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from fastapi import Request
from prometheus_client import Counter
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.utils.pii import (
    anonymize_email,
    anonymize_ip,
    mask_pii,
)

logger = structlog.get_logger(__name__)

# Prometheus metrics for audit observability (SOC2 monitoring)
AUDIT_FAILURE_COUNTER = Counter(
    "audit_logs_failed_total",
    "Total number of audit logs that failed to persist (DB errors, etc.)"
)

# SRE Protection: Maximum audit logs per tenant per day to prevent storage flooding.
MAX_DAILY_AUDIT_LOGS_PER_TENANT = 100000


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
    is_support_access: Optional[bool] = None,
) -> None:
    """
    Persist an audit log entry.  Never raises — failures are logged but do not
    interrupt the calling request.  Audit logging must be non-blocking.
    """
    if tenant_id:
        # Soft Quota check (Phase 10)
        # Simply prevents excessive flooding in a 24h window
        # In a real production system, this would use Redis for performance.
        try:
            from sqlalchemy import func as sqlfunc
            cutoff = datetime.now(timezone.utc) - timedelta(days=1)
            count_q = select(sqlfunc.count()).where(
                AuditLog.tenant_id == uuid.UUID(str(tenant_id)),
                AuditLog.created_at >= cutoff
            )
            count_res = await db.execute(count_q)
            if count_res.scalar_one() >= MAX_DAILY_AUDIT_LOGS_PER_TENANT:
                logger.warning("audit_log_quota_exceeded", tenant_id=tenant_id, action=action)
                return
        except Exception as q_exc:
            logger.warning("audit_quota_check_failed", error=str(q_exc))

    try:

        # Extract context from request if provided
        ip_address: Optional[str] = None
        user_agent: Optional[str] = None
        _tenant_id = tenant_id
        _actor_user_id = actor_user_id
        _actor_role = actor_role

        if request is not None:
            from app.core.security import get_client_ip
            ip_address = get_client_ip(request)
            user_agent = (request.headers.get("User-Agent") or "")[:500]

            if not _tenant_id:
                _tenant_id = getattr(request.state, "tenant_id", None)
            if not _actor_user_id:
                _actor_user_id = getattr(request.state, "user_id", None)
            if not _actor_role:
                _actor_role = getattr(request.state, "role", None)
            if not actor_email:
                actor_email = getattr(request.state, "actor_email", None)
            if is_support_access is None:
                is_support_access = getattr(request.state, "is_support_access", False)

        # Forensic Normalization: Ensure emails are always lowercased for consistent indexing.
        if actor_email:
            actor_email = actor_email.lower()



        # Pillar 1 & 2: Zenity PII Masking
        # Mask sensitive data in details before storage using Zenith-grade deep masking.
        masked_details = mask_pii(details, deep=True) if details else None
        
        # Safety: truncate massive details to 10KB to prevent DB bloat
        if masked_details:
            import json
            details_str = json.dumps(masked_details)
            if len(details_str) > 10000:
                masked_details = {
                    "__truncated": True,
                    "__warning": "Details exceeded 10KB limit and were truncated.",
                    "data": details_str[:10000] + "... [TRUNCATED]"
                }

        # Pillar 1 Hardening: Capture is_support_access logic
        is_support_access = False
        if request is not None:
            is_support_access = getattr(request.state, "is_support_access", False)

        entry = AuditLog(
            tenant_id=uuid.UUID(str(_tenant_id)) if _tenant_id else None,
            actor_user_id=uuid.UUID(str(_actor_user_id)) if _actor_user_id else None,
            actor_email=actor_email,
            actor_role=_actor_role,
            is_support_access=is_support_access,
            action=action,
            category=category,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            status=status,
            details=masked_details,
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
        AUDIT_FAILURE_COUNTER.inc()



def _build_audit_query(
    tenant_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    action_prefix: Optional[str] = None,
    category: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    status: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
):
    """Internal helper to build the audit search query."""
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
        
    return query


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
    mask_pii: bool = True,
) -> dict[str, Any]:
    """Query audit logs with filters. Returns paginated results."""
    query = _build_audit_query(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action_prefix=action_prefix,
        category=category,
        resource_type=resource_type,
        resource_id=resource_id,
        status=status,
        since=since,
        until=until
    )


    # Count total for pagination
    from sqlalchemy import func as sqlfunc
    count_q = select(sqlfunc.count()).select_from(query.subquery())
    total_res = await db.execute(count_q)
    total = total_res.scalar_one()

    # Paginate newest first (Deterministic sort)
    offset = (page - 1) * per_page
    query = query.order_by(desc(AuditLog.created_at), desc(AuditLog.id)).offset(offset).limit(per_page)

    result = await db.execute(query)
    rows = result.scalars().all()

    return {
        "items": [_serialize(row, do_mask_pii=mask_pii) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }



def _serialize(log: AuditLog, do_mask_pii: bool = True) -> dict[str, Any]:
    ip = log.ip_address
    if do_mask_pii and ip:
        ip = anonymize_ip(ip)

    email = log.actor_email
    if do_mask_pii and email:
        email = anonymize_email(email)

    res_id = log.resource_id
    if do_mask_pii and res_id:
        # Mask if it looks like an email
        if "@" in res_id:
            res_id = anonymize_email(res_id)
        # Mask if it looks like an IP
        elif res_id.count(".") == 3 or ":" in res_id:
            res_id = anonymize_ip(res_id)


    return {
        "id": str(log.id),
        "tenant_id": str(log.tenant_id) if log.tenant_id else None,
        "actor_user_id": str(log.actor_user_id) if log.actor_user_id else None,
        "actor_email": email,
        "actor_role": log.actor_role,
        "is_support_access": log.is_support_access,
        "action": log.action,
        "category": log.category,
        "resource_type": log.resource_type,
        "resource_id": res_id,
        "status": log.status,
        "details": mask_pii(log.details, deep=do_mask_pii) if log.details else None,
        "ip_address": ip,
        "user_agent": log.user_agent,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


async def stream_audit_logs(
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
    limit: int = 1000,
    mask_pii: bool = True,
    # Purpose Bindings (Phase 12)
    request: Optional[Request] = None,
    export_reason: Optional[str] = None,
):
    """
    Asynchronously stream audit logs one by one from the DB.
    Used for memory-efficient CSV exports.
    """
    # Forensic: Log the export event itself with full initiator context
    await audit_log(
        db,
        "data.export",
        request=request,  # Captures client IP and User-Agent
        category="data",
        resource_type="audit_logs",
        details={
            "justification": export_reason,
            "filters": {
                "tenant_id": str(tenant_id) if tenant_id else None,
                "category": category,
                "since": since.isoformat() if since else None,
                "until": until.isoformat() if until else None
            }
        }
    )


    query = _build_audit_query(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action_prefix=action_prefix,
        category=category,
        resource_type=resource_type,
        resource_id=resource_id,
        status=status,
        since=since,
        until=until
    )
    # Newest first + stable sort + limit
    query = query.order_by(desc(AuditLog.created_at), desc(AuditLog.id)).limit(limit)
    
    stream = await db.stream(query)
    async for row in stream:
        # row is a result tuple, the first element is the AuditLog object
        yield _serialize(row[0], do_mask_pii=mask_pii)




# ─── Data Masking (Imported from Utils) ──────────────────────────────────────
