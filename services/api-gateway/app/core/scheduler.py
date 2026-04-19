import asyncio
import structlog
from app.core.database import AsyncSessionLocal
from app.services.auth_service import auth_service
from app.services.billing_service import BillingService
from app.scripts.purge_audit_logs import purge_logs

logger = structlog.get_logger(__name__)

CLEANUP_INTERVAL_SECONDS = 900  # 15 minutes
RECONCILE_INTERVAL_SECONDS = 1800 # 30 minutes
PURGE_INTERVAL_SECONDS = 86400  # 24 hours


async def _cleanup_loop(redis=None):
    """Background loop that cleans up unpaid pending accounts."""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                cleaned = await auth_service.cleanup_pending_accounts(db, redis)
                if cleaned > 0:
                    logger.info("scheduled_cleanup", cleaned=cleaned)
        except Exception as exc:
            logger.error("scheduled_cleanup_failed", error=str(exc))
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        
async def _billing_reconciliation_loop(redis=None):
    """Background loop that reconciles PENDING_PAYMENT agents with Stripe."""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                billing_svc = BillingService(db, redis)
                recovered = await billing_svc.reconcile_pending_agents()
                if recovered > 0:
                    logger.info("scheduled_billing_reconciliation", recovered=recovered)
        except Exception as exc:
            logger.error("scheduled_billing_reconciliation_failed", error=str(exc))
        await asyncio.sleep(RECONCILE_INTERVAL_SECONDS)

async def _audit_purge_loop():
    """Background loop that automatically deletes expired audit logs (GDPR alignment)."""
    while True:
        try:
            # We don't need Redis here; it uses the DB.
            deleted = await purge_logs(dry_run=False)
            if deleted > 0:
                logger.info("scheduled_audit_purge", deleted=deleted)
        except Exception as exc:
            logger.error("scheduled_audit_purge_failed", error=str(exc))
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)


# Expose the raw coroutines so `main.py` can orchestrate them as native asyncio tasks
# within the `lifespan` context manager.
BACKGROUND_TASKS = [
    _cleanup_loop,
    _billing_reconciliation_loop,
    _audit_purge_loop,
]

