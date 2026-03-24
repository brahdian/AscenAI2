import redis.asyncio as aioredis
from typing import Optional
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

_redis_client: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=False,  # binary mode for audio data compatibility
            max_connections=20,
        )
    return _redis_client


async def init_redis() -> aioredis.Redis:
    global _redis_client
    _redis_client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=False,
        max_connections=20,
    )
    await _redis_client.ping()
    logger.info("redis_connected", url=settings.REDIS_URL)
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
    logger.info("redis_connection_closed")
