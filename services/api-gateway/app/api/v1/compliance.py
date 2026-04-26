"""
PIPEDA / Privacy compliance endpoints.

Implements the basics required for Canadian clinic clients:
  - GET/PATCH /compliance/settings   — data retention & privacy config
  - POST /compliance/erasure         — right-to-erasure request (PIPEDA s.5, Principle 5)
  - GET  /compliance/privacy-notice  — machine-readable privacy notice

Settings are stored in the tenant's metadata JSON column so no migration is required.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import engine as _db_engine
from app.core.security import get_current_tenant, get_tenant_db
from app.services.tenant_service import tenant_service

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/compliance")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_tenant(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return tid


def _require_owner_or_admin(request: Request) -> str:
    tid = _require_tenant(request)
    role = getattr(request.state, "role", "viewer")
    if role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Owner or admin role required.")
    return tid


def _default_settings() -> dict:
    return {
        "data_retention_days": 365,
        "session_retention_days": 90,
        "auto_anonymize_after_days": 730,
        "collect_consent_enabled": False,
        "consent_message": "By chatting, you agree to our privacy policy.",
        "privacy_policy_url": "",
        "data_residency": "Canada",
        "hipaa_mode": False,
    }


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ComplianceSettings(BaseModel):
    data_retention_days: int = Field(
        365, ge=30, le=3650, description="Days to retain raw session data"
    )
    session_retention_days: int = Field(
        90, ge=7, le=3650, description="Days to retain session records"
    )
    auto_anonymize_after_days: int = Field(
        730, ge=30, le=3650, description="Days after which PII is automatically anonymized"
    )
    collect_consent_enabled: bool = Field(
        False, description="Show consent banner before first chat"
    )
    consent_message: str = Field(
        "By chatting, you agree to our privacy policy.",
        max_length=500,
    )
    privacy_policy_url: str = Field("", max_length=2048, description="Link to your privacy policy")
    data_residency: str = Field("Canada", max_length=100)
    hipaa_mode: bool = Field(
        False, description="Enable HIPAA-mode logging (audit trail, no PII in logs)"
    )


class ErasureRequest(BaseModel):
    contact_identifier: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Email address or customer ID to erase",
    )
    reason: str = Field(default="customer_request", max_length=500)
    requester_name: str = Field(default="", max_length=255)


class ErasureResponse(BaseModel):
    request_id: str
    contact_identifier: str
    status: str
    submitted_at: str
    estimated_completion: str
    message: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=ComplianceSettings)
async def get_compliance_settings(
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
) -> ComplianceSettings:
    """Return current compliance/privacy settings for this tenant."""
    tenant = await tenant_service.get_tenant(tenant_id, db)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    stored = (tenant.metadata_ or {}).get("compliance", {})
    defaults = _default_settings()
    merged = {**defaults, **stored}
    return ComplianceSettings(**merged)


@router.patch("/settings", response_model=ComplianceSettings)
async def update_compliance_settings(
    body: ComplianceSettings,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
    request: Request = None,  # Added to access state
) -> ComplianceSettings:
    """Update compliance/privacy settings (owner/admin only)."""
    if request:
        _require_owner_or_admin(request)

    tenant = await tenant_service.get_tenant(tenant_id, db)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    current_meta = dict(tenant.metadata_ or {})
    current_meta["compliance"] = body.model_dump()
    await tenant_service.update_tenant(tenant_id, {"metadata_": current_meta}, db)

    logger.info(
        "compliance_settings_updated",
        tenant_id=tenant_id,
        settings=body.model_dump(),
    )
    return body


async def _execute_erasure(
    tenant_id: str,
    contact_identifier: str,
    request_id: str,
) -> None:
    """Background task: hard-delete all messages, sessions, and traces for the contact."""
    _session_factory = async_sessionmaker(_db_engine, expire_on_commit=False)
    async with _session_factory() as db:
        try:
            # 1. Delete message feedback belonging to contact's sessions
            await db.execute(
                text(
                    """
                    DELETE FROM message_feedback
                    WHERE session_id IN (
                        SELECT id FROM sessions
                        WHERE tenant_id = :tid
                          AND customer_identifier = :contact
                    )
                    """
                ),
                {"tid": tenant_id, "contact": contact_identifier},
            )

            # 2. Delete conversation traces
            await db.execute(
                text(
                    """
                    DELETE FROM conversation_traces
                    WHERE tenant_id = :tid
                      AND session_id IN (
                        SELECT id FROM sessions
                        WHERE tenant_id = :tid
                          AND customer_identifier = :contact
                    )
                    """
                ),
                {"tid": tenant_id, "contact": contact_identifier},
            )

            # 3. Delete messages
            await db.execute(
                text(
                    """
                    DELETE FROM messages
                    WHERE session_id IN (
                        SELECT id FROM sessions
                        WHERE tenant_id = :tid
                          AND customer_identifier = :contact
                    )
                    """
                ),
                {"tid": tenant_id, "contact": contact_identifier},
            )

            # 4. Delete the sessions themselves
            await db.execute(
                text(
                    """
                    DELETE FROM sessions
                    WHERE tenant_id = :tid
                      AND customer_identifier = :contact
                    """
                ),
                {"tid": tenant_id, "contact": contact_identifier},
            )
            await db.commit()
            logger.info(
                "erasure_executed_complete",
                tenant_id=tenant_id,
                request_id=request_id,
                contact=contact_identifier,
            )
        except Exception as exc:
            await db.rollback()
            logger.error(
                "erasure_execution_failed",
                tenant_id=tenant_id,
                request_id=request_id,
                error=str(exc),
            )


@router.post("/erasure", response_model=ErasureResponse, status_code=202)
async def request_erasure(
    body: ErasureRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
) -> ErasureResponse:
    """
    Submit a right-to-erasure request (PIPEDA Principle 4.3.6 / GDPR Art. 17).

    This logs the request and queues background deletion of all sessions, messages,
    feedback, traces, and associated PII for the given contact identifier.
    """
    tenant = await tenant_service.get_tenant(tenant_id, db)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    request_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # Persist the erasure request in tenant metadata for audit trail
    current_meta = dict(tenant.metadata_ or {})
    erasure_log: list = current_meta.get("erasure_requests", [])
    erasure_log.append(
        {
            "id": request_id,
            "contact": body.contact_identifier,
            "reason": body.reason,
            "requester": body.requester_name,
            "submitted_at": now.isoformat(),
            "status": "pending",
        }
    )
    current_meta["erasure_requests"] = erasure_log[-100:]  # Keep last 100
    await tenant_service.update_tenant(tenant_id, {"metadata_": current_meta}, db)

    logger.info(
        "erasure_request_submitted",
        tenant_id=tenant_id,
        request_id=request_id,
        contact=body.contact_identifier,
        reason=body.reason,
    )

    # Kick off actual deletion in the background
    background_tasks.add_task(
        _execute_erasure,
        tenant_id=tenant_id,
        contact_identifier=body.contact_identifier,
        request_id=request_id,
    )

    return ErasureResponse(
        request_id=request_id,
        contact_identifier=body.contact_identifier,
        status="pending",
        submitted_at=now.isoformat(),
        estimated_completion=(now + timedelta(days=30)).isoformat(),
        message=(
            "Your erasure request has been received and will be processed within 30 days "
            "as required by PIPEDA. You will be notified once complete."
        ),
    )


@router.get("/erasure-log")
async def get_erasure_log(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
) -> list[dict]:
    """Return the audit log of erasure requests for this tenant (owner/admin only)."""
    _require_owner_or_admin(request)
    tenant = await tenant_service.get_tenant(tenant_id, db)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    log = (tenant.metadata_ or {}).get("erasure_requests", [])
    return list(reversed(log))  # Most recent first


@router.get("/privacy-notice")
async def get_privacy_notice(
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    """Return a machine-readable summary of this tenant's privacy practices."""
    tenant = await tenant_service.get_tenant(tenant_id, db)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    stored = (tenant.metadata_ or {}).get("compliance", {})
    defaults = _default_settings()
    settings = {**defaults, **stored}

    return {
        "controller": tenant.business_name or tenant.name,
        "jurisdiction": "Canada",
        "framework": "PIPEDA",
        "data_residency": settings["data_residency"],
        "data_retention_days": settings["data_retention_days"],
        "auto_anonymize_after_days": settings["auto_anonymize_after_days"],
        "consent_required": settings["collect_consent_enabled"],
        "privacy_policy_url": settings["privacy_policy_url"],
        "right_to_erasure": True,
        "right_to_access": True,
        "contact_email": "privacy@ascenai.com",
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
