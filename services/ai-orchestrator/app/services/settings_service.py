import time
import json
from typing import Any, Dict, Optional
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

class SettingsService:
    """
    Platform Settings Service with Distributed (Redis) and Local (In-Memory) Caching.
    Used to fetch global prompts, Global Guardrails, and settings without DB overhead.
    """
    _cache: Dict[str, Any] = {}
    _ttl: int = 300  # 5 minutes
    @classmethod
    async def get_setting(cls, db: AsyncSession, key: str, default: Any = None) -> Any:
        """Get a setting from Redis (first), local cache (second), or database."""
        now = time.time()
        
        # 1. Check local in-memory cache first (ultrafast)
        if key in cls._cache:
            entry = cls._cache[key]
            if now - entry["timestamp"] < cls._ttl:
                return entry["value"]

        from app.core.redis_client import get_redis
        redis = await get_redis()
        redis_key = f"platform_setting:{key}"

        # 2. Check Redis (distributed)
        try:
            cached_val = await redis.get(redis_key)
            if cached_val:
                value = json.loads(cached_val)
                cls._cache[key] = {"value": value, "timestamp": now}
                return value
        except Exception as e:
            logger.warning("redis_setting_fetch_error", key=key, error=str(e))

        # 3. Fetch from DB (source of truth)
        try:
            result = await db.execute(
                text("SELECT value FROM platform_settings WHERE key = :key"),
                {"key": key}
            )
            row = result.fetchone()
            if row:
                value = row._mapping["value"]
                # Update both caches
                cls._cache[key] = {"value": value, "timestamp": now}
                await redis.setex(redis_key, cls._ttl, json.dumps(value))
                return value
        except Exception as e:
            logger.error("settings_fetch_error", key=key, error=str(e))
        
        return default

    @classmethod
    async def invalidate_cache(cls, key: Optional[str] = None):
        """Invalidate specific or all cache entries in both local and Redis."""
        from app.core.redis_client import get_redis
        redis = await get_redis()

        if key:
            cls._cache.pop(key, None)
            await redis.delete(f"platform_setting:{key}")
        else:
            cls._cache.clear()
            # Note: We don't flush all Redis, just wait for TTL or specific keys
