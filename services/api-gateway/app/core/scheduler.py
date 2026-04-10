import asyncio
import structlog
from app.core.database import AsyncSessionLocal
from app.services.auth_service import auth_service

logger = structlog.get_logger(__name__)

CLEANUP_INTERVAL_SECONDS = 900  # 15 minutes

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

def start_scheduler(app):
    """Start the background cleanup scheduler."""
    @app.on_event("startup")
    async def startup():
        redis = getattr(app.state, "redis", None)
        asyncio.create_task(_cleanup_loop(redis))
        logger.info("cleanup_scheduler_started", interval_seconds=CLEANUP_INTERVAL_SECONDS)
