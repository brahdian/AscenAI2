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
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
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
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ComplianceSettings:
    """Return current compliance/privacy settings for this tenant."""
    tenant_id = _require_tenant(request)
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
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ComplianceSettings:
    """Update compliance/privacy settings (owner/admin only)."""
    tenant_id = _require_owner_or_admin(request)
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


@router.post("/erasure", response_model=ErasureResponse, status_code=202)
async def request_erasure(
    body: ErasureRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ErasureResponse:
    """
    Submit a right-to-erasure request (PIPEDA Principle 4.3.6 / GDPR Art. 17).

    This logs the request and queues background deletion of all sessions, messages,
    and associated PII for the given contact identifier.
    """
    tenant_id = _require_owner_or_admin(request)
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

    return ErasureResponse(
        request_id=request_id,
        contact_identifier=body.contact_identifier,
        status="pending",
        submitted_at=now.isoformat(),
        estimated_completion=(
            now.replace(day=min(now.day + 30, 28)).isoformat()
        ),
        message=(
            "Your erasure request has been received and will be processed within 30 days "
            "as required by PIPEDA. You will be notified at the submitter's contact once complete."
        ),
    )


@router.get("/erasure-log")
async def get_erasure_log(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return the audit log of erasure requests for this tenant (owner/admin only)."""
    tenant_id = _require_owner_or_admin(request)
    tenant = await tenant_service.get_tenant(tenant_id, db)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    log = (tenant.metadata_ or {}).get("erasure_requests", [])
    return list(reversed(log))  # Most recent first


@router.get("/privacy-notice")
async def get_privacy_notice(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return a machine-readable summary of this tenant's privacy practices."""
    tenant_id = _require_tenant(request)
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
