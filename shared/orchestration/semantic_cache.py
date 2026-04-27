"""
SemanticCache — cosine-similarity response cache for the LLM.

When a user's query is semantically near-duplicate to a recently-cached query
(cosine similarity >= 0.92), the cached response is returned without calling
the LLM.

Cache key namespace: ``sem_cache:{tenant_id}:{agent_id}``
TTL:                 3600 seconds (1 hour)

Cache entries are stored as Redis hashes:
  {
    "query_embedding": <json float[]>,
    "response":        <str>,
    "created_at":      <iso timestamp>,
  }

Only responses that pass ALL of the following conditions are cached:
  - No tool calls were made
  - No PII tokens present in the response
  - No guardrail actions were triggered
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

_SIMILARITY_THRESHOLD = 0.92
_CACHE_TTL = 3600        # 1 hour
_MAX_ENTRIES = 500       # per (tenant, agent) bucket
_EMBEDDING_DIM = 384     # sentence-transformers default


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Fast pure-Python cosine similarity for small vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticCache:
    """
    Redis-backed semantic response cache.

    :param redis_client: async Redis client
    :param embed_fn: async callable that takes a string and returns list[float]
    """

    def __init__(self, redis_client, embed_fn) -> None:
        self._redis = redis_client
        self._embed = embed_fn

    # ── Public API ────────────────────────────────────────────────────────────

    async def get(
        self,
        query: str,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> Optional[str]:
        """
        Return cached response if a near-duplicate query exists, else None.

        :param query: raw user query text
        :param tenant_id: tenant scope
        :param agent_id: agent scope
        :returns: cached response string, or None on miss
        """
        t0 = time.monotonic()
        try:
            query_embedding = await self._embed(query)
            bucket_key = _bucket_key(tenant_id, agent_id)

            # Scan all entries in this bucket
            entries_raw = await self._redis.hgetall(bucket_key)
            best_score = 0.0
            best_response: Optional[str] = None

            for _field, value_bytes in entries_raw.items():
                try:
                    entry = json.loads(value_bytes)
                    cached_embedding = entry.get("query_embedding", [])
                    if not cached_embedding:
                        continue
                    score = _cosine_similarity(query_embedding, cached_embedding)
                    if score > best_score:
                        best_score = score
                        best_response = entry.get("response")
                except Exception:
                    continue

            elapsed_ms = (time.monotonic() - t0) * 1000
            if best_score >= _SIMILARITY_THRESHOLD and best_response:
                logger.info(
                    "semantic_cache_hit",
                    agent_id=str(agent_id),
                    similarity=round(best_score, 4),
                    elapsed_ms=round(elapsed_ms, 1),
                )
                return best_response

            logger.debug(
                "semantic_cache_miss",
                agent_id=str(agent_id),
                best_score=round(best_score, 4),
                elapsed_ms=round(elapsed_ms, 1),
            )
            return None

        except Exception as exc:
            logger.warning("semantic_cache_get_error", error=str(exc))
            return None

    async def set(
        self,
        query: str,
        response: str,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        tool_calls_made: bool = False,
        pii_active: bool = False,
        guardrail_actions: Optional[list] = None,
    ) -> None:
        """
        Store a response in the semantic cache.

        Silently skips caching if:
        - tool calls were made (non-deterministic)
        - PII tokens are present
        - guardrail actions were triggered
        """
        if tool_calls_made or pii_active or guardrail_actions:
            return

        try:
            query_embedding = await self._embed(query)
            bucket_key = _bucket_key(tenant_id, agent_id)

            # Evict oldest entry if bucket is full
            count = await self._redis.hlen(bucket_key)
            if count >= _MAX_ENTRIES:
                # Delete the first 50 fields (FIFO approximation)
                all_fields = await self._redis.hkeys(bucket_key)
                if all_fields:
                    await self._redis.hdel(bucket_key, *all_fields[:50])

            field = f"{time.monotonic_ns()}"
            entry = {
                "query_embedding": query_embedding,
                "response": response,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await self._redis.hset(bucket_key, field, json.dumps(entry))
            await self._redis.expire(bucket_key, _CACHE_TTL)

            logger.debug("semantic_cache_set", agent_id=str(agent_id), field=field)

        except Exception as exc:
            logger.warning("semantic_cache_set_error", error=str(exc))

    async def invalidate(self, tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
        """Clear all cached entries for an agent."""
        try:
            await self._redis.delete(_bucket_key(tenant_id, agent_id))
            logger.info("semantic_cache_invalidated", agent_id=str(agent_id))
        except Exception as exc:
            logger.warning("semantic_cache_invalidate_error", error=str(exc))


def _bucket_key(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    return f"sem_cache:{tenant_id}:{agent_id}"
