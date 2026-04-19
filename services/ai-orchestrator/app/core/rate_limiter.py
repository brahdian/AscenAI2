import time
import structlog
from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

class RateLimiter:
    """
    Zenith Resilience: Redis-backed sliding window rate limiter for expensive 
    API operations. Prevents resource exhaustion and DDoS.
    """
    def __init__(self, redis: Redis):
        self.redis = redis

    async def is_allowed(
        self, 
        key: str, 
        limit: int, 
        window_seconds: int = 60
    ) -> bool:
        """
        Check if an action is allowed based on the sliding window algorithm.
        key: The unique identifier for the limit (e.g., 'tenant_id:action')
        limit: Max actions allowed in the window
        window_seconds: The time window in seconds
        """
        now = time.time()
        # Key for the Redis sorted set
        redis_key = f"rl:{key}"
        
        # LUA script for atomic sliding window rate limiting
        lua_script = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local window = tonumber(ARGV[2])
        local limit = tonumber(ARGV[3])
        
        -- Remove old entries outside the window
        redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
        
        -- Count entries in the current window
        local current_count = redis.call('ZCARD', key)
        
        if current_count < limit then
            -- Add new entry
            redis.call('ZADD', key, now, now)
            -- Set TTL on the key to ensure cleanup
            redis.call('EXPIRE', key, window + 1)
            return 1
        else
            return 0
        end
        """
        
        try:
            allowed = await self.redis.eval(lua_script, 1, redis_key, now, window_seconds, limit)
            return bool(allowed)
        except Exception as e:
            # Zenith Resilience: Fail-open if Redis is down, but log the failure
            logger.error("rate_limiter_error", key=key, error=str(e))
            return True
