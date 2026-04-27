import asyncio
import structlog
from arq import worker

logger = structlog.get_logger(__name__)

async def startup(ctx):
    logger.info("arq_worker_startup")

async def shutdown(ctx):
    logger.info("arq_worker_shutdown")

class WorkerSettings:
    functions = []
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = None # Will be configured from settings
