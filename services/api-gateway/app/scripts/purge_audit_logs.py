#!/usr/bin/env python3
"""
Audit Log Retention Purge Script
================================
Iterates through all tenants and deletes audit log entries older than
their configured 'audit_retention_days'.

Usage:
    python3 app/scripts/purge_audit_logs.py [--dry-run]
"""
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.tenant import Tenant
from app.services.audit_service import audit_log

logger = structlog.get_logger(__name__)





async def purge_logs(dry_run: bool = False):
    async with AsyncSessionLocal() as session:
        # 1. Fetch all tenants with their retention settings
        result = await session.execute(select(Tenant))
        tenants = result.scalars().all()
        
        total_deleted = 0
        now = datetime.now(timezone.utc)
        
        # ── 1. Tenant-level Purging ──────────────────────────────────────────
        for tenant in tenants:
            try:
                retention_days = tenant.audit_retention_days or 365
                cutoff_date = now - timedelta(days=retention_days)
                
                # Count records to be deleted for logging
                # Count records to be deleted for logging
                count_q = select(func.count(AuditLog.id)).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.created_at < cutoff_date
                )
                count_res = await session.execute(count_q)
                to_delete_count = count_res.scalar() or 0
                
                if to_delete_count > 0:
                    logger.info("audit_purge_started", tenant_id=str(tenant.id), count=to_delete_count, cutoff_date=cutoff_date.isoformat())
                    
                    if not dry_run:
                        # Batch deletion to avoid table locks
                        batch_size = 5000
                        deleted_in_tenant = 0
                        while True:
                            batch_q = select(AuditLog.id).where(
                                AuditLog.tenant_id == tenant.id,
                                AuditLog.created_at < cutoff_date
                            ).limit(batch_size)
                            
                            batch_res = await session.execute(batch_q)
                            batch_ids = batch_res.scalars().all()
                            
                            if not batch_ids:
                                break
                                
                            delete_q = delete(AuditLog).where(AuditLog.id.in_(batch_ids))
                            await session.execute(delete_q)
                            await session.commit()
                            
                            deleted_in_tenant += len(batch_ids)
                            total_deleted += len(batch_ids)
                        
                        logger.info("audit_purge_completed", tenant_id=str(tenant.id), deleted=deleted_in_tenant)
            except Exception as exc:
                logger.error("audit_purge_tenant_failed", tenant_id=str(tenant.id), error=str(exc))
                await session.rollback()

        # ── 2. Platform-level Purging (tenant_id IS NULL) ───────────────────
        # Platform retention is usually stricter or consistent (default 90 days)
        try:
            platform_retention = 90  # Default 90 days for administrative logs
            platform_cutoff = now - timedelta(days=platform_retention)
            
            p_count_q = select(func.count(AuditLog.id)).where(
                AuditLog.tenant_id.is_(None),
                AuditLog.created_at < platform_cutoff
            )
            p_count_res = await session.execute(p_count_q)
            p_to_delete = p_count_res.scalar() or 0
            
            if p_to_delete > 0:
                logger.info("platform_audit_purge_started", count=p_to_delete, cutoff=platform_cutoff.isoformat())
                if not dry_run:
                    # Reuse Batch Deletion logic
                    while True:
                        batch_q = select(AuditLog.id).where(
                            AuditLog.tenant_id.is_(None),
                            AuditLog.created_at < platform_cutoff
                        ).limit(5000)
                        batch_res = await session.execute(batch_q)
                        batch_ids = batch_res.scalars().all()
                        if not batch_ids: break
                        await session.execute(delete(AuditLog).where(AuditLog.id.in_(batch_ids)))
                        await session.commit()
                        total_deleted += len(batch_ids)
                    logger.info("platform_audit_purge_completed", deleted=p_to_delete)
        except Exception as exc:
            logger.error("platform_audit_purge_failed", error=str(exc))
            await session.rollback()

        # ── 3. Audit of Audit ──────────────────────────────────────────────
        # Required by SOC 2 for integrity verification: log that a purge happened.
        if total_deleted > 0 and not dry_run:

            # Re-init a session if needed or use internal helper
            await audit_log(
                session,
                "data.audit_purge",
                category="data",
                status="success",
                details={
                    "records_deleted": total_deleted,
                    "tenant_retention_max_days": 365,
                    "platform_retention_days": 90
                }
            )
            await session.commit()

        if not dry_run:
            logger.info("global_audit_purge_completed", total_deleted=total_deleted)
        else:
            logger.info("global_audit_purge_dry_run_completed", total_deleted=total_deleted)
        
        return total_deleted


