import time
from typing import Any, Dict, Optional
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

class SettingsService:
    """
    Platform Settings Service with In-Memory TTL Caching.
    Used to fetch global prompts and greeting maps without DB overhead on every call.
    """
    _cache: Dict[str, Dict[str, Any]] = {}
    _ttl = 300  # 5 minutes

    @classmethod
    async def get_setting(cls, db: AsyncSession, key: str, default: Any = None) -> Any:
        """Get a setting from cache or database."""
        now = time.time()
        
        # Check cache
        if key in cls._cache:
            entry = cls._cache[key]
            if now - entry["timestamp"] < cls._ttl:
                return entry["value"]

        # Fetch from DB
        try:
            result = await db.execute(
                text("SELECT value FROM platform_settings WHERE key = :key"),
                {"key": key}
            )
            row = result.fetchone()
            if row:
                value = row._mapping["value"]
                cls._cache[key] = {"value": value, "timestamp": now}
                return value
        except Exception as e:
            logger.error("settings_fetch_error", key=key, error=str(e))
        
        return default

    @classmethod
    def invalidate_cache(cls, key: Optional[str] = None):
        """Invalidate specific or all cache entries."""
        if key:
            cls._cache.pop(key, None)
        else:
            cls._cache.clear()
