"""
Admin API — Platform administration endpoints.

Endpoints:
- GET  /admin/tenants                    — List all tenants
- GET  /admin/tenants/{id}               — Get tenant details
- POST /admin/tenants/{id}/suspend       — Suspend tenant
- POST /admin/tenants/{id}/reactivate    — Reactivate tenant
- DELETE /admin/tenants/{id}             — Delete tenant
- GET  /admin/users                      — List users
- PUT  /admin/users/{id}/role            — Update user role
- GET  /admin/prompts                    — Get system prompts
- PUT  /admin/prompts/{agent_id}         — Update system prompt
- GET  /admin/traces                     — Get conversation traces
- GET  /admin/metrics                    — Get platform metrics
- GET  /admin/roles                      — List available roles
"""

from __future__ import annotations

import uuid
import csv
import io
from typing import Optional, Any
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.admin_service import AdminService, get_all_roles

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/admin")


def _require_super_admin(request: Request) -> str:
    """Require super_admin role."""
    role = getattr(request.state, "role", "")
    if role != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required.")
    return getattr(request.state, "user_id", "")


def _require_admin(request: Request) -> tuple[str, str]:
    """Require tenant admin/owner or super_admin role."""
    role = getattr(request.state, "role", "")
    if role not in ("super_admin", "owner", "admin"):
        raise HTTPException(status_code=403, detail="Admin access required.")
    user_id = getattr(request.state, "user_id", "")
    tenant_id = getattr(request.state, "tenant_id", "")
    return user_id, tenant_id


def _get_admin_service(request: Request, db: AsyncSession) -> AdminService:
    """Build AdminService from request-scoped dependencies."""
    redis = request.app.state.redis
    return AdminService(db, redis)


async def _check_admin_mutation_rate_limit(request: Request):
    """
    Tactical rate limit for high-risk admin mutations.
    Limit: 10 mutations per hour per super_admin.
    """
    redis = getattr(request.app.state, "redis", None)
    if not redis:
        return

    admin_id = getattr(request.state, "user_id", "anonymous")
    key = f"admin_mutation_limit:{admin_id}"
    
    # 10 actions per 3600 seconds
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 3600)
        
        if count > 10:
            logger.warning("admin_mutation_rate_limit_exceeded", admin_id=admin_id)
            raise HTTPException(
                status_code=429, 
                detail="Administrative mutation rate limit exceeded (10/hour). Please wait."
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("admin_rate_limit_check_failed", error=str(e))


_VALID_TENANT_STATUSES = {"", "active", "suspended", "deleted"}


@router.get("/tenants")
async def list_tenants(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    status: str = Query("", pattern="^(active|suspended|deleted|)$"),
    db: AsyncSession = Depends(get_db),
):
    """List all tenants (super_admin only)."""
    _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.list_tenants(page, per_page, status)


@router.get("/tenants/{tenant_id}")
async def get_tenant_details(
    tenant_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get detailed tenant information."""
    _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.get_tenant_details(str(tenant_id))


class SuspendRequest(BaseModel):
    reason: str = Field(..., description="Reason for suspension")


@router.post("/tenants/{tenant_id}/suspend")
async def suspend_tenant(
    tenant_id: uuid.UUID,
    body: SuspendRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(_check_admin_mutation_rate_limit),
):
    """Suspend a tenant."""
    from app.services.audit_service import audit_log
    admin_user_id = _require_super_admin(request)
    service = _get_admin_service(request, db)
    result = await service.suspend_tenant(str(tenant_id), body.reason, admin_user_id)
    await audit_log(db, "tenant.suspended", request=request, category="admin",
                    resource_type="tenant", resource_id=str(tenant_id),
                    details={"reason": body.reason})
    return result


@router.post("/tenants/{tenant_id}/reactivate")
async def reactivate_tenant(
    tenant_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Reactivate a suspended tenant."""
    from app.services.audit_service import audit_log
    admin_user_id = _require_super_admin(request)
    service = _get_admin_service(request, db)
    result = await service.reactivate_tenant(str(tenant_id), admin_user_id)
    await audit_log(db, "tenant.reactivated", request=request, category="admin",
                    resource_type="tenant", resource_id=str(tenant_id))
    return result


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(
    tenant_id: uuid.UUID,
    request: Request,
    hard_delete: bool = False,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(_check_admin_mutation_rate_limit),
):
    """Delete a tenant (soft or hard delete)."""
    from app.services.audit_service import audit_log
    admin_user_id = _require_super_admin(request)
    service = _get_admin_service(request, db)
    result = await service.delete_tenant(str(tenant_id), admin_user_id, hard_delete)
    await audit_log(db, "tenant.deleted", request=request, category="admin",
                    resource_type="tenant", resource_id=str(tenant_id),
                    details={"hard_delete": hard_delete})
    return result


@router.get("/users")
async def list_users(
    request: Request,
    tenant_id: str = "",
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List users (scoped to tenant for non-super-admins)."""
    role = getattr(request.state, "role", "")
    caller_tenant_id = getattr(request.state, "tenant_id", None)
    
    enforce_tenant_id = None
    if role != "super_admin":
        _require_admin(request)
        enforce_tenant_id = caller_tenant_id

    service = _get_admin_service(request, db)
    return await service.list_users(tenant_id, page, per_page, enforced_tenant_id=enforce_tenant_id)


class RoleUpdateRequest(BaseModel):
    role: str = Field(..., description="New role")


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: uuid.UUID,
    body: RoleUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(_check_admin_mutation_rate_limit),
):
    """Update a user's role."""
    from app.services.audit_service import audit_log
    
    role = getattr(request.state, "role", "")
    caller_tenant_id = getattr(request.state, "tenant_id", None)
    
    enforce_tenant_id = None
    if role != "super_admin":
        _require_admin(request)
        enforce_tenant_id = caller_tenant_id
    else:
        # Require super_admin for global role changes if no tenant context
        admin_user_id = _require_super_admin(request)

    service = _get_admin_service(request, db)
    result = await service.update_user_role(str(user_id), body.role, getattr(request.state, "user_id", ""), enforced_tenant_id=enforce_tenant_id)
    
    if "error" not in result:
        await audit_log(db, "user.role_changed", request=request, category="user",
                        resource_type="user", resource_id=str(user_id),
                        details={"new_role": body.role})
    return result


@router.get("/prompts")
async def get_system_prompts(
    request: Request,
    agent_id: str = "",
    db: AsyncSession = Depends(get_db),
):
    role = getattr(request.state, "role", "")
    caller_tenant_id = getattr(request.state, "tenant_id", None)
    
    enforce_tenant_id = None
    if role != "super_admin":
        _require_admin(request)
        enforce_tenant_id = caller_tenant_id

    service = _get_admin_service(request, db)
    return await service.get_system_prompts(agent_id, tenant_id=enforce_tenant_id)


class PromptUpdateRequest(BaseModel):
    system_prompt: str = Field(..., description="New system prompt")


@router.put("/prompts/{agent_id}")
async def update_system_prompt(
    agent_id: str,
    body: PromptUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update an agent's system prompt."""
    role = getattr(request.state, "role", "")
    caller_tenant_id = getattr(request.state, "tenant_id", None)
    
    enforce_tenant_id = None
    if role != "super_admin":
        _require_admin(request)
        enforce_tenant_id = caller_tenant_id

    service = _get_admin_service(request, db)
    return await service.update_system_prompt(agent_id, body.system_prompt, getattr(request.state, "user_id", ""), tenant_id=enforce_tenant_id)


@router.get("/traces")
async def get_traces(
    request: Request,
    session_id: str = "",
    tenant_id: str = "",
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Get conversation traces (redacted)."""
    role = getattr(request.state, "role", "")
    caller_tenant_id = getattr(request.state, "tenant_id", None)
    
    enforce_tenant_id = None
    if role != "super_admin":
        _require_admin(request)
        enforce_tenant_id = caller_tenant_id

    service = _get_admin_service(request, db)
    return await service.get_traces(session_id, tenant_id, limit, enforced_tenant_id=enforce_tenant_id)


@router.get("/metrics")
async def get_platform_metrics(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get platform-wide metrics."""
    _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.get_platform_metrics()


@router.get("/roles")
async def list_roles(db: AsyncSession = Depends(get_db)):
    """List available roles and their permissions."""
    roles = await get_all_roles(db)
    return {"roles": roles}


@router.get("/settings")
async def get_platform_settings(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get all platform settings (super_admin only)."""
    _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.get_platform_settings()


class SettingUpdateRequest(BaseModel):
    value: Any = Field(..., description="New setting value (JSON serializable)")


@router.put("/settings/{key}")
async def update_platform_setting(
    key: str,
    body: SettingUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(_check_admin_mutation_rate_limit),
):
    """Update a platform setting (super_admin only)."""
    admin_user_id = _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.update_platform_setting(key, body.value, admin_user_id)


class TrialTenantCreateRequest(BaseModel):
    name: str = Field(..., description="Tenant name (slug)")
    business_name: str = Field(..., description="Business display name")
    plan: str = Field(default="starter", description="Plan tier")
    admin_email: str = Field(..., description="Admin user email")
    admin_password: str = Field(..., description="Admin user password")


@router.post("/trial-tenants")
async def create_trial_tenant(
    body: TrialTenantCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a trial tenant with admin user (bypasses Stripe/payment)."""
    admin_user_id = _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.create_trial_tenant(
        name=body.name,
        business_name=body.business_name,
        plan=body.plan,
        admin_email=body.admin_email,
        admin_password=body.admin_password,
        created_by=admin_user_id,
    )


@router.get("/tenants/usage")
async def get_all_tenants_usage(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get usage stats for all tenants (LLM, STT, TTS tokens)."""
    admin_user_id = _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.get_all_tenants_usage()


# ---------------------------------------------------------------------------
# Platform Guardrails — view and toggle global enforcement rules
# ---------------------------------------------------------------------------

# The canonical list of platform-level guardrails is defined in code
# (services/ai-orchestrator/app/guardrails/voice_agent_guardrails.py).
# Super-admins can DISABLE individual rules (e.g. for debugging) or add
# extra blocked keywords/topics via PlatformSetting("platform_guardrails").
# Disabling a guardrail does NOT remove the code — it adds a runtime bypass.

_DEFAULT_GUARDRAILS = [
    {
        "id": "GG-01",
        "name": "Prompt injection strip",
        "description": "Remove system_prompt / instructions fields forwarded by the client so tenants cannot override the agent's core directives.",
        "category": "security",
        "enabled": True,
        "severity": "critical",
        "toggleable": False,
    },
    {
        "id": "GG-02",
        "name": "Role injection sanitization",
        "description": "Sanitize role-injection tokens (e.g. 'Ignore previous instructions') from user messages before they reach the LLM.",
        "category": "security",
        "enabled": True,
        "severity": "critical",
        "toggleable": False,
    },
    {
        "id": "GG-03",
        "name": "Auth from JWT only",
        "description": "Agent identity and permissions are derived exclusively from the JWT, never from conversation claims.",
        "category": "security",
        "enabled": True,
        "severity": "critical",
        "toggleable": False,
    },
    {
        "id": "GG-04",
        "name": "No stack-trace leakage",
        "description": "Strip stack traces, config values, and internal URLs from LLM responses and error messages.",
        "category": "privacy",
        "enabled": True,
        "severity": "high",
        "toggleable": False,
    },
    {
        "id": "GG-05",
        "name": "Emergency keyword intercept",
        "description": "Immediately return a canned emergency response for health/safety keywords (~0 ms, bypasses LLM).",
        "category": "safety",
        "enabled": True,
        "severity": "critical",
        "toggleable": False,
    },
    {
        "id": "GG-06",
        "name": "Anti-impersonation gate",
        "description": "Agent cannot claim to be a human, licensed professional, or regulatory authority.",
        "category": "compliance",
        "enabled": True,
        "severity": "high",
        "toggleable": True,
    },
    {
        "id": "GG-07",
        "name": "Auto-escalate after 3 failures",
        "description": "Transfer to human after 3 consecutive fallback responses to prevent indefinite loops.",
        "category": "quality",
        "enabled": True,
        "severity": "medium",
        "toggleable": True,
    },
    {
        "id": "GG-08",
        "name": "High-risk tool confirmation gate",
        "description": "Stripe, Twilio SMS, Gmail, and other high-risk tools require an explicit user confirmation step before execution.",
        "category": "security",
        "enabled": True,
        "severity": "high",
        "toggleable": True,
    },
    {
        "id": "GG-09",
        "name": "High-risk tool receipt read-back",
        "description": "After a high-risk tool executes, the agent must read back a confirmation receipt to the user.",
        "category": "compliance",
        "enabled": True,
        "severity": "medium",
        "toggleable": True,
    },
    {
        "id": "GG-10",
        "name": "Session-scoped concurrency lock",
        "description": "Only one utterance is processed at a time per session (asyncio.Lock) to prevent race conditions.",
        "category": "reliability",
        "enabled": True,
        "severity": "high",
        "toggleable": False,
    },
    {
        "id": "GG-11",
        "name": "PII pseudonymization",
        "description": "PII (names, emails, phone, SSN, credit cards) is pseudonymized before reaching the LLM and restored in the response stream.",
        "category": "privacy",
        "enabled": True,
        "severity": "high",
        "toggleable": True,
    },
    {
        "id": "GG-12",
        "name": "Output moderation",
        "description": "LLM responses are scanned for toxic content, hate speech, and medical advice before delivery. Fail-open (logs violation, does not block).",
        "category": "safety",
        "enabled": True,
        "severity": "medium",
        "toggleable": True,
    },
    {
        "id": "GG-13",
        "name": "Voice response closure",
        "description": "Every voice response must end with a clear spoken next-step or question so the caller knows when to speak.",
        "category": "voice_ux",
        "enabled": True,
        "severity": "low",
        "toggleable": True,
    },
    {
        "id": "GG-14",
        "name": "Low-confidence STT rejection",
        "description": "If STT transcription confidence is below 0.6, the pipeline asks the user to repeat rather than proceeding with an unreliable transcript.",
        "category": "voice_ux",
        "enabled": True,
        "severity": "medium",
        "toggleable": True,
    },
    {
        "id": "GG-15",
        "name": "PII redaction",
        "description": "Output guardrails redact PII (email, phone, card numbers) before including them in any response when pii_redaction is enabled for the agent.",
        "category": "privacy",
        "enabled": True,
        "severity": "high",
        "toggleable": True,
    },
    {
        "id": "GG-16",
        "name": "Credential isolation",
        "description": "Tool API keys stored in tool metadata must never appear in LLM prompts or user-facing responses.",
        "category": "privacy",
        "enabled": True,
        "severity": "critical",
        "toggleable": False,
    },
]


@router.get("/guardrails")
async def list_platform_guardrails(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Return the list of platform-level guardrails with their current enabled status.
    Overrides are read from PlatformSetting('platform_guardrails').
    """
    _require_super_admin(request)
    overrides: dict = {}
    try:
        from app.models.platform import PlatformSetting
        from sqlalchemy import select as _select
        result = await db.execute(
            _select(PlatformSetting).where(PlatformSetting.key == "platform_guardrails")
        )
        setting = result.scalar_one_or_none()
        if setting and setting.value:
            overrides = setting.value  # {guardrail_id: {enabled: bool, ...}}
    except Exception as e:
        logger.warning("guardrails_fetch_failed", error=str(e))

    merged = []
    for gr in _DEFAULT_GUARDRAILS:
        override = overrides.get(gr["id"], {})
        merged.append({**gr, **override})

    return {"guardrails": merged}


class GuardrailUpdateRequest(BaseModel):
    enabled: bool = Field(..., description="Enable or disable this guardrail")


@router.patch("/guardrails/{guardrail_id}")
async def update_platform_guardrail(
    guardrail_id: str,
    body: GuardrailUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Toggle a platform guardrail on/off.
    Only toggleable=True guardrails can be disabled; critical rules are immutable.
    """
    admin_user_id = _require_super_admin(request)

    # Validate the guardrail ID and check it's toggleable
    guardrail = next((g for g in _DEFAULT_GUARDRAILS if g["id"] == guardrail_id), None)
    if not guardrail:
        raise HTTPException(status_code=404, detail=f"Guardrail {guardrail_id!r} not found.")
    if not guardrail["toggleable"] and not body.enabled:
        raise HTTPException(
            status_code=403,
            detail=f"Guardrail {guardrail_id} is a critical non-toggleable rule and cannot be disabled.",
        )

    try:
        from app.models.platform import PlatformSetting
        from sqlalchemy import select as _select
        result = await db.execute(
            _select(PlatformSetting).where(PlatformSetting.key == "platform_guardrails")
        )
        setting = result.scalar_one_or_none()
        current: dict = {}
        if setting and setting.value:
            current = dict(setting.value)
        current[guardrail_id] = {"enabled": body.enabled}

        if setting:
            setting.value = current
        else:
            setting = PlatformSetting(
                key="platform_guardrails",
                value=current,
                description="Per-guardrail enable/disable overrides (super_admin only).",
                is_sensitive=False,
                is_public=False,
            )
            db.add(setting)

        await db.commit()
        logger.info(
            "platform_guardrail_updated",
            guardrail_id=guardrail_id,
            enabled=body.enabled,
            admin_user_id=admin_user_id,
        )
    except Exception as e:
        logger.error("guardrail_update_failed", error=str(e), guardrail_id=guardrail_id)
        raise HTTPException(status_code=500, detail="Failed to update guardrail setting.")

    return {"guardrail_id": guardrail_id, "enabled": body.enabled}


# ---------------------------------------------------------------------------
# Audit Logs
# ---------------------------------------------------------------------------

@router.get("/audit-logs")
async def list_audit_logs(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    tenant_id: Optional[str] = Query(None),
    actor_user_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None, pattern="^(auth|user|tenant|agent|billing|admin|data|api_key|general|)$"),
    action: Optional[str] = Query(None, max_length=100),
    status: Optional[str] = Query(None, pattern="^(success|failure|)$"),
    since: Optional[str] = Query(None, description="ISO 8601 datetime"),
    until: Optional[str] = Query(None, description="ISO 8601 datetime"),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve paginated audit logs.  Super admins see all tenants; tenant admins
    see only their own tenant's logs.

    Required by SOC2 CC6.1/CC7.2, GDPR Art.30, HIPAA §164.312(b), PCI-DSS 10.2.
    """
    from app.services.audit_service import list_audit_logs as _list, audit_log
    from datetime import datetime, timedelta

    role = getattr(request.state, "role", "")
    caller_tenant_id = getattr(request.state, "tenant_id", None)

    # Forensic: Log the viewing of audit logs (Who watched the watchers?)
    await audit_log(
        db,
        "data.access",
        request=request,
        category="data",
        resource_type="audit_logs",
        details={"page": page, "per_page": per_page}
    )

    if role != "super_admin":
        # Non-super-admin can only see their own tenant
        if role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="Admin access required.")
        tenant_id = caller_tenant_id

    from app.utils.dates import enforce_temporal_cap
    
    since_dt = datetime.fromisoformat(since) if since else None
    until_dt = datetime.fromisoformat(until) if until else datetime.now(timezone.utc)
    
    # DoS Protection: Enforce maximum date range (90 days) for real-time audit queries
    if since_dt and until_dt:
        if until_dt - since_dt > timedelta(days=90):
            raise HTTPException(
                status_code=400, 
                detail="Audit log range cannot exceed 90 days for real-time viewing. Use export for larger windows."
            )
    
    since_dt = enforce_temporal_cap(since_dt, max_days=90)
    
    return await _list(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action_prefix=action,
        category=category or None,
        status=status or None,
        since=since_dt,
        until=until_dt,
        page=page,
        per_page=per_page,
    )


@router.get("/audit-logs/export")
async def export_audit_logs(
    request: Request,
    tenant_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    justification_id: str = Query(..., min_length=5, description="Zenith Pillar 2: Justification ID for data export"),
    db: AsyncSession = Depends(get_db),
):
    """
    Export audit logs to CSV via streaming.
    SOC2/HIPAA compliance requirement: forensic data export.
    """
    from app.utils.dates import enforce_temporal_cap, sanitize_for_csv
    from app.services.audit_service import stream_audit_logs as _stream
    from datetime import datetime, timedelta

    # Security: Exports of all tenant data are restricted to Super Admins
    _require_super_admin(request)

    since_dt = datetime.fromisoformat(since) if since else datetime.now(timezone.utc) - timedelta(days=30)
    until_dt = datetime.fromisoformat(until) if until else datetime.now(timezone.utc)

    # Zenith Pillar 4: Forensic Temporal Cap (366 days)
    since_dt = enforce_temporal_cap(since_dt, max_days=366)

    async def csv_generator():
        # Write CSV header to buffer
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "ID", "Timestamp", "Tenant ID", "Actor Email", "Role", 
            "Support Access", "Action", "Category", "Resource Type", 
            "Resource ID", "Status", "IP Address"
        ])
        yield output.getvalue()
        output.truncate(0)
        output.seek(0)

        # Stream rows
        async for log in _stream(
            db, 
            tenant_id=tenant_id, 
            category=category, 
            since=since_dt, 
            until=until_dt,
            request=request,
            export_reason=justification_id
        ):
            writer.writerow([
                sanitize_for_csv(log["id"]), 
                sanitize_for_csv(log["created_at"]), 
                sanitize_for_csv(log["tenant_id"]), 
                sanitize_for_csv(log["actor_email"]), 
                sanitize_for_csv(log["actor_role"]), 
                sanitize_for_csv(log["is_support_access"]),
                sanitize_for_csv(log["action"]), 
                sanitize_for_csv(log["category"]), 
                sanitize_for_csv(log["resource_type"]), 
                sanitize_for_csv(log["resource_id"]), 
                sanitize_for_csv(log["status"]), 
                sanitize_for_csv(log["ip_address"])
            ])
            yield output.getvalue()
            output.truncate(0)
            output.seek(0)

        # Zenith Pillar 2: Forensic Continuity Marker
        writer.writerow(["# END OF AUDIT EXPORT #", f"Exported By: {getattr(request.state, 'actor_email', 'unknown')}", f"Justification: {justification_id}"])
        yield output.getvalue()

    filename = f"audit_export_{datetime.now().strftime('%Y%p%m_%H%M%S')}.csv"
    return StreamingResponse(
        csv_generator(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
