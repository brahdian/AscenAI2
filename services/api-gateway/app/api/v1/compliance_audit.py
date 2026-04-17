"""
Compliance Audit API — Automated compliance checking.

Endpoints:
- GET  /compliance-audit/scan/pii           — Scan for raw PII
- GET  /compliance-audit/scan/rls           — Verify RLS policies
- GET  /compliance-audit/scan/encryption    — Verify encryption
- GET  /compliance-audit/report/pci         — PCI-DSS report
- GET  /compliance-audit/report/hipaa       — HIPAA report
- GET  /compliance-audit/report/gdpr        — GDPR report
- GET  /compliance-audit/report/full        — Full compliance report
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_tenant_db, get_current_tenant
from app.core.redis_client import get_redis
from app.services.compliance_auditor import ComplianceAuditor

router = APIRouter(prefix="/compliance-audit")


def _require_admin(request: Request) -> str:
    role = getattr(request.state, "role", "")
    if role not in ("super_admin", "tenant_owner", "tenant_admin"):
        raise HTTPException(status_code=403, detail="Admin access required.")
    return getattr(request.state, "tenant_id", "")


@router.get("/scan/pii")
async def scan_for_pii(
    request: Request,
    tenant_id: str = "",
    limit: int = 1000,
    db: AsyncSession = Depends(get_tenant_db),
    # Note: Using get_tenant_db for db, but tenant_id is passed as query param/arg here?
    # Scanning for PII usually targets a specific tenant.
):
    """Scan messages for raw PII."""
    _require_admin(request)
    redis = await get_redis()
    auditor = ComplianceAuditor(db, redis)
    return await auditor.scan_messages_for_pii(tenant_id, limit)


@router.get("/scan/rls")
async def verify_rls(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Verify RLS policies are active."""
    _require_admin(request)
    redis = await get_redis()
    auditor = ComplianceAuditor(db, redis)
    return await auditor.verify_rls_policies()


@router.get("/scan/encryption")
async def verify_encryption(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Verify encryption configuration."""
    _require_admin(request)
    redis = await get_redis()
    auditor = ComplianceAuditor(db, redis)
    return await auditor.verify_encryption()


@router.get("/report/pci")
async def pci_dss_report(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Generate PCI-DSS compliance report."""
    _require_admin(request)
    redis = await get_redis()
    auditor = ComplianceAuditor(db, redis)
    return await auditor.generate_pci_dss_report()


@router.get("/report/hipaa")
async def hipaa_report(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Generate HIPAA compliance report."""
    _require_admin(request)
    redis = await get_redis()
    auditor = ComplianceAuditor(db, redis)
    return await auditor.generate_hipaa_report()


@router.get("/report/gdpr")
async def gdpr_report(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Generate GDPR compliance report."""
    _require_admin(request)
    redis = await get_redis()
    auditor = ComplianceAuditor(db, redis)
    return await auditor.generate_gdpr_report()


@router.get("/report/full")
async def full_compliance_report(
    request: Request,
    tenant_id: str = "",
    db: AsyncSession = Depends(get_tenant_db),
):
    """Generate comprehensive compliance report."""
    _require_admin(request)
    redis = await get_redis()
    auditor = ComplianceAuditor(db, redis)
    return await auditor.generate_full_compliance_report(tenant_id)
