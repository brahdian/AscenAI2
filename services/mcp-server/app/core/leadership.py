from __future__ import annotations

import os
import socket
import uuid


class RedisLeaderLease:
    def __init__(self, redis, name: str, ttl_seconds: int = 90) -> None:
        self.redis = redis
        self.name = name
        self.ttl_seconds = ttl_seconds
        self.owner_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4()}"

    @property
    def key(self) -> str:
        return f"leader:{self.name}"

    async def acquire_or_renew(self) -> bool:
        current_owner = await self.redis.get(self.key)
        if current_owner == self.owner_id:
            await self.redis.expire(self.key, self.ttl_seconds)
            return True
        acquired = await self.redis.set(self.key, self.owner_id, nx=True, ex=self.ttl_seconds)
        return bool(acquired)

    async def release(self) -> None:
        current_owner = await self.redis.get(self.key)
        if current_owner == self.owner_id:
            await self.redis.delete(self.key)
