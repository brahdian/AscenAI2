import asyncio
import hashlib
import json
import uuid
from typing import Any, Optional

import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.context import KnowledgeBase, KnowledgeDocument
from app.schemas.mcp import ContextItem, MCPContextRequest, MCPContextResult

logger = structlog.get_logger(__name__)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x ** 2 for x in a) ** 0.5
    norm_b = sum(x ** 2 for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def _embed_text(text: str) -> list[float]:
    """
    Generate a text embedding.
    Uses OpenAI when OPENAI_API_KEY is set, otherwise falls back to
    a deterministic hash-based pseudo-embedding for local development.
    """
    if settings.OPENAI_API_KEY:
        import httpx
        headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {"model": settings.EMBEDDING_MODEL, "input": text}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            return data["data"][0]["embedding"]

    # Fallback: deterministic hash-based pseudo-embedding (for dev/testing only)
    dim = settings.EMBEDDING_DIMENSION
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # Expand digest to `dim` floats using a simple LCG seeded from the digest
    seed = int.from_bytes(digest[:8], "big")
    values: list[float] = []
    for i in range(dim):
        seed = (seed * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        values.append((seed / 0xFFFFFFFFFFFFFFFF) * 2 - 1)
    # Normalize
    norm = sum(v ** 2 for v in values) ** 0.5 or 1.0
    return [v / norm for v in values]


class ContextProvider:
    """
    Retrieves contextual information from multiple sources:
    - knowledge: vector search in Qdrant
    - history:   conversation turns stored in Redis
    - customer:  customer profiles from PostgreSQL
    """

    def __init__(
        self,
        qdrant_client,
        redis_client,
        db: AsyncSession,
    ) -> None:
        self.qdrant = qdrant_client
        self.redis = redis_client
        self.db = db

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def retrieve_context(
        self, request: MCPContextRequest
    ) -> MCPContextResult:
        """Gather context from all requested sources in parallel."""
        tasks = []
        task_labels = []

        if "knowledge" in request.context_types:
            tasks.append(
                self._search_knowledge_base(
                    request.tenant_id,
                    request.query,
                    request.top_k,
                    kb_id=request.kb_id,
                )
            )
            task_labels.append("knowledge")

        if "history" in request.context_types:
            tasks.append(
                self._get_conversation_history(request.session_id, limit=10)
            )
            task_labels.append("history")

        if "customer" in request.context_types:
            tasks.append(
                self._get_customer_profile(
                    request.tenant_id,
                    request.customer_id,
                )
            )
            task_labels.append("customer")

        results: list[list[ContextItem]] = await asyncio.gather(
            *tasks, return_exceptions=False
        )

        # Merge and sort by score descending
        all_items: list[ContextItem] = []
        for label, items in zip(task_labels, results):
            all_items.extend(items)

        all_items.sort(key=lambda x: x.score, reverse=True)

        # Cap at top_k * number of types to avoid bloat
        max_items = request.top_k * len(request.context_types)
        all_items = all_items[:max_items]

        return MCPContextResult(
            items=all_items,
            total_found=len(all_items),
        )

    # ------------------------------------------------------------------
    # Knowledge Base (Qdrant vector search)
    # ------------------------------------------------------------------

    async def _search_knowledge_base(
        self,
        tenant_id: str,
        query: str,
        top_k: int,
        kb_id: Optional[str] = None,
    ) -> list[ContextItem]:
        """Search the tenant's knowledge base using vector similarity."""
        if self.qdrant is None:
            logger.warning("qdrant_unavailable", tenant_id=tenant_id)
            return []

        try:
            query_vector = await _embed_text(query)
            collection_name = f"{settings.QDRANT_COLLECTION_PREFIX}{tenant_id.replace('-', '_')}"

            # Build filter for kb_id if specified
            search_filter = None
            if kb_id:
                from qdrant_client.models import Filter, FieldCondition, MatchValue
                search_filter = Filter(
                    must=[
                        FieldCondition(
                            key="kb_id",
                            match=MatchValue(value=kb_id),
                        )
                    ]
                )

            hits = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.qdrant.search(
                    collection_name=collection_name,
                    query_vector=query_vector,
                    limit=top_k,
                    query_filter=search_filter,
                    with_payload=True,
                ),
            )

            items = []
            for hit in hits:
                payload: dict = hit.payload or {}
                items.append(
                    ContextItem(
                        type="knowledge",
                        content=payload.get("content", ""),
                        score=float(hit.score),
                        metadata={
                            "title": payload.get("title", ""),
                            "content_type": payload.get("content_type", "text"),
                            "kb_id": payload.get("kb_id", ""),
                            "doc_id": payload.get("doc_id", ""),
                        },
                    )
                )
            return items

        except Exception as exc:
            logger.error(
                "knowledge_search_failed",
                tenant_id=tenant_id,
                error=str(exc),
                exc_info=exc,
            )
            return []

    # ------------------------------------------------------------------
    # Conversation History (Redis)
    # ------------------------------------------------------------------

    async def _get_conversation_history(
        self, session_id: str, limit: int = 10
    ) -> list[ContextItem]:
        """Retrieve recent conversation turns from Redis."""
        if self.redis is None:
            return []

        try:
            key = f"conversation:{session_id}"
            # Store as a Redis list (most recent at head)
            raw_items = await self.redis.lrange(key, 0, limit - 1)
            items = []
            for i, raw in enumerate(raw_items):
                try:
                    turn = json.loads(raw)
                    items.append(
                        ContextItem(
                            type="history",
                            content=turn.get("content", raw),
                            score=max(0.1, 1.0 - i * 0.1),  # Recency score
                            metadata={
                                "role": turn.get("role", "unknown"),
                                "timestamp": turn.get("timestamp", ""),
                                "session_id": session_id,
                            },
                        )
                    )
                except (json.JSONDecodeError, AttributeError):
                    items.append(
                        ContextItem(
                            type="history",
                            content=str(raw),
                            score=max(0.1, 1.0 - i * 0.1),
                            metadata={"session_id": session_id},
                        )
                    )
            return items

        except Exception as exc:
            logger.error(
                "history_retrieval_failed",
                session_id=session_id,
                error=str(exc),
            )
            return []

    async def store_conversation_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        ttl_seconds: int = 3600,
    ) -> None:
        """Append a conversation turn to the Redis session list."""
        if self.redis is None:
            return
        import time
        key = f"conversation:{session_id}"
        turn = json.dumps(
            {"role": role, "content": content, "timestamp": time.time()}
        )
        pipe = self.redis.pipeline()
        pipe.lpush(key, turn)
        pipe.ltrim(key, 0, 49)  # Keep last 50 turns
        pipe.expire(key, ttl_seconds)
        await pipe.execute()

    # ------------------------------------------------------------------
    # Customer Profile (PostgreSQL)
    # ------------------------------------------------------------------

    async def _get_customer_profile(
        self, tenant_id: str, customer_id: Optional[str]
    ) -> list[ContextItem]:
        """Retrieve customer profile data from the database."""
        if not customer_id:
            return []

        try:
            from sqlalchemy import text
            result = await self.db.execute(
                text(
                    """
                    SELECT id, name, email, phone, preferences, order_history, notes
                    FROM customers
                    WHERE tenant_id = :tenant_id
                      AND (id::text = :customer_id
                           OR email = :customer_id
                           OR phone = :customer_id)
                    LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id, "customer_id": customer_id},
            )
            row = result.fetchone()
            if not row:
                return []

            profile_text = (
                f"Customer: {row[1]} | Email: {row[2]} | Phone: {row[3]}"
            )
            if row[6]:  # notes
                profile_text += f" | Notes: {row[6]}"

            items = [
                ContextItem(
                    type="customer",
                    content=profile_text,
                    score=1.0,
                    metadata={
                        "customer_id": str(row[0]),
                        "name": row[1] or "",
                        "email": row[2] or "",
                        "phone": row[3] or "",
                        "preferences": row[4] or {},
                    },
                )
            ]

            # Add order history if available
            if row[5]:
                order_hist = row[5]
                if isinstance(order_hist, list) and order_hist:
                    latest = order_hist[:3]
                    order_text = "Recent orders: " + "; ".join(
                        str(o) for o in latest
                    )
                    items.append(
                        ContextItem(
                            type="customer",
                            content=order_text,
                            score=0.9,
                            metadata={"customer_id": str(row[0]), "type": "order_history"},
                        )
                    )
            return items

        except Exception as exc:
            logger.error(
                "customer_profile_failed",
                tenant_id=tenant_id,
                customer_id=customer_id,
                error=str(exc),
            )
            return []

    # ------------------------------------------------------------------
    # Knowledge Upsert
    # ------------------------------------------------------------------

    async def upsert_knowledge(
        self,
        tenant_id: str,
        kb_id: str,
        document: KnowledgeDocument,
    ) -> str:
        """
        Generate embedding for document content and upsert into Qdrant.
        Returns the Qdrant point ID (vector_id).
        """
        vector_id = str(document.id)

        if self.qdrant is None:
            logger.warning("qdrant_unavailable_skipping_embedding", doc_id=str(document.id))
            return vector_id

        try:
            embedding = await _embed_text(document.content)
            collection_name = f"{settings.QDRANT_COLLECTION_PREFIX}{tenant_id.replace('-', '_')}"

            # Ensure collection exists
            await self._ensure_collection(collection_name, len(embedding))

            from qdrant_client.models import PointStruct
            point = PointStruct(
                id=vector_id,
                vector=embedding,
                payload={
                    "doc_id": str(document.id),
                    "kb_id": kb_id,
                    "tenant_id": tenant_id,
                    "title": document.title,
                    "content": document.content,
                    "content_type": document.content_type,
                    "metadata": document.doc_metadata,
                },
            )
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.qdrant.upsert(
                    collection_name=collection_name,
                    points=[point],
                ),
            )
            logger.info(
                "knowledge_upserted",
                tenant_id=tenant_id,
                doc_id=str(document.id),
                collection=collection_name,
            )
        except Exception as exc:
            logger.error(
                "knowledge_upsert_failed",
                tenant_id=tenant_id,
                doc_id=str(document.id),
                error=str(exc),
                exc_info=exc,
            )

        return vector_id

    async def delete_knowledge(self, tenant_id: str, vector_id: str) -> None:
        """Delete a Qdrant point by vector_id."""
        if self.qdrant is None:
            return
        collection_name = f"{settings.QDRANT_COLLECTION_PREFIX}{tenant_id.replace('-', '_')}"
        try:
            from qdrant_client.models import PointIdsList
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.qdrant.delete(
                    collection_name=collection_name,
                    points_selector=PointIdsList(points=[vector_id]),
                ),
            )
        except Exception as exc:
            logger.warning(
                "knowledge_delete_failed",
                vector_id=vector_id,
                error=str(exc),
            )

    async def _ensure_collection(
        self, collection_name: str, vector_size: int
    ) -> None:
        """Create the Qdrant collection if it doesn't exist."""
        try:
            from qdrant_client.models import Distance, VectorParams
            collections = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.qdrant.get_collections(),
            )
            existing = {c.name for c in collections.collections}
            if collection_name not in existing:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.qdrant.create_collection(
                        collection_name=collection_name,
                        vectors_config=VectorParams(
                            size=vector_size,
                            distance=Distance.COSINE,
                        ),
                    ),
                )
                logger.info("qdrant_collection_created", collection=collection_name)
        except Exception as exc:
            logger.warning(
                "qdrant_ensure_collection_failed",
                collection=collection_name,
                error=str(exc),
            )
