import asyncio
import hashlib
import json
import uuid
from typing import Any, Optional

import httpx
import structlog
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.context import KnowledgeBase, KnowledgeDocument
from app.schemas.mcp import (
    ContextItem,
    KnowledgeBaseCreate,
    KnowledgeDocumentCreate,
    MCPContextRequest,
    MCPContextResult,
)

logger = structlog.get_logger(__name__)


async def _embed_text(text_input: str) -> list[float]:
    """
    Generate a text embedding using the Gemini text-embedding-004 model.
    Falls back to a deterministic hash-based pseudo-embedding for local dev
    when GEMINI_API_KEY is not configured.
    """
    api_key = settings.GEMINI_API_KEY
    if api_key:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.EMBEDDING_MODEL}:embedContent?key={api_key}"
        )
        payload = {
            "model": f"models/{settings.EMBEDDING_MODEL}",
            "content": {"parts": [{"text": text_input}]},
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["embedding"]["values"]
        except Exception as exc:
            logger.warning("gemini_embed_failed_falling_back", error=str(exc))

    # Fallback: deterministic hash-based pseudo-embedding (dev/testing only)
    dim = settings.EMBEDDING_DIMENSION
    digest = hashlib.sha256(text_input.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "big")
    values: list[float] = []
    for _ in range(dim):
        seed = (seed * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        values.append((seed / 0xFFFFFFFFFFFFFFFF) * 2 - 1)
    norm = sum(v ** 2 for v in values) ** 0.5 or 1.0
    return [v / norm for v in values]


class ContextProvider:
    """
    Retrieves contextual information from multiple sources:
    - knowledge: pgvector cosine similarity search in PostgreSQL
    - history:   conversation turns stored in Redis
    - customer:  customer profiles from PostgreSQL
    """

    def __init__(self, redis_client, db: AsyncSession) -> None:
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

        all_items: list[ContextItem] = []
        for items in results:
            all_items.extend(items)

        all_items.sort(key=lambda x: x.score, reverse=True)
        max_items = request.top_k * len(request.context_types)
        all_items = all_items[:max_items]

        return MCPContextResult(
            items=all_items,
            total_found=len(all_items),
        )

    # ------------------------------------------------------------------
    # Knowledge Base (pgvector cosine search)
    # ------------------------------------------------------------------

    async def _search_knowledge_base(
        self,
        tenant_id: str,
        query: str,
        top_k: int,
        kb_id: Optional[str] = None,
    ) -> list[ContextItem]:
        """Search the tenant's knowledge base using pgvector cosine similarity."""
        import time as _time
        _t0 = _time.monotonic()
        try:
            query_vector = await _embed_text(query)
            
            # Using SQLAlchemy pgvector extension for native search
            # Score = 1 - cosine_distance
            dist_col = KnowledgeDocument.embedding.cosine_distance(query_vector)
            score_col = (1.0 - dist_col).label("score")

            filters = [
                KnowledgeDocument.tenant_id == uuid.UUID(tenant_id),
                KnowledgeDocument.embedding != None,
            ]
            if kb_id:
                filters.append(KnowledgeDocument.kb_id == uuid.UUID(kb_id))

            # Phase 7: Over-fetch by 2x so the score filter doesn't starve the result
            stmt = (
                select(KnowledgeDocument, score_col)
                .where(and_(*filters))
                .order_by(dist_col)
                .limit(top_k * 2)
            )

            result = await self.db.execute(stmt)
            rows = result.all()

            items = []
            for doc, score in rows:
                # Phase 7 — Gap 2: Discard chunks below the minimum relevance threshold
                if float(score) < settings.MIN_KNOWLEDGE_SCORE:
                    continue
                # Phase 7 — Gap 3: Suppress semantic duplicates from retrieval
                doc_meta = doc.doc_metadata or {}
                if doc_meta.get("is_semantic_duplicate") == "true":
                    continue
                items.append(
                    ContextItem(
                        type="knowledge",
                        content=doc.content,
                        score=float(score),
                        metadata={
                            "title": doc.title or "",
                            "content_type": doc.content_type,
                            "kb_id": str(doc.kb_id),
                            "doc_id": str(doc.id),
                        },
                    )
                )
                if len(items) >= top_k:
                    break

            _latency_ms = int((_time.monotonic() - _t0) * 1000)
            logger.info(
                "rag_search_complete",
                tenant_id=tenant_id,
                kb_id=kb_id,
                results_returned=len(items),
                latency_ms=_latency_ms,
                min_score=settings.MIN_KNOWLEDGE_SCORE,
            )
            return items

        except Exception as exc:
            _latency_ms = int((_time.monotonic() - _t0) * 1000)
            logger.error(
                "knowledge_search_failed",
                tenant_id=tenant_id,
                latency_ms=_latency_ms,
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
            raw_items = await self.redis.lrange(key, 0, limit - 1)
            items = []
            for i, raw in enumerate(raw_items):
                try:
                    turn = json.loads(raw)
                    items.append(
                        ContextItem(
                            type="history",
                            content=turn.get("content", raw),
                            score=max(0.1, 1.0 - i * 0.1),
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
        pipe.ltrim(key, 0, 49)
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
            if row[6]:
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
    # Knowledge Upsert (pgvector)
    # ------------------------------------------------------------------

    async def upsert_knowledge(
        self,
        tenant_id: str,
        kb_id: str,
        document: KnowledgeDocument,
    ) -> str:
        """
        Generate embedding for document content and store it in the
        knowledge_documents.embedding column (pgvector).
        Returns the document ID as vector_id for backwards compatibility.
        """
        vector_id = str(document.id)
        try:
            embedding = await _embed_text(document.content)
            
            # Simple ORM update — SQLAlchemy + pgvector handles the rest
            document.embedding = embedding
            await self.db.flush()
            
            logger.info(
                "knowledge_upserted_pgvector",
                tenant_id=tenant_id,
                doc_id=str(document.id),
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
        """No-op: embedding is stored on the document row, deleted with the row."""
        pass

    # ------------------------------------------------------------------
    # Knowledge Base CRUD (PostgreSQL)
    # ------------------------------------------------------------------

    async def create_knowledge_base(
        self, tenant_id: str, body: KnowledgeBaseCreate
    ) -> KnowledgeBase:
        """Create and persist a new KnowledgeBase row."""
        kb = KnowledgeBase(
            id=uuid.uuid4(),
            tenant_id=uuid.UUID(tenant_id),
            name=body.name,
            description=body.description,
            agent_id=uuid.UUID(body.agent_id) if body.agent_id else None,
        )
        self.db.add(kb)
        await self.db.flush()
        return kb

    async def list_knowledge_bases(self, tenant_id: str) -> list[KnowledgeBase]:
        """Return all knowledge bases owned by a tenant."""
        result = await self.db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.tenant_id == uuid.UUID(tenant_id)
            )
        )
        return list(result.scalars().all())

    async def add_document(
        self, tenant_id: str, body: KnowledgeDocumentCreate
    ) -> KnowledgeDocument:
        """Persist a document and index its embedding in pgvector."""
        kb_result = await self.db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == uuid.UUID(body.kb_id),
                KnowledgeBase.tenant_id == uuid.UUID(tenant_id),
            )
        )
        kb = kb_result.scalar_one_or_none()
        if kb is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Knowledge base not found.")

        doc = KnowledgeDocument(
            id=uuid.uuid4(),
            kb_id=uuid.UUID(body.kb_id),
            tenant_id=uuid.UUID(tenant_id),
            title=body.title,
            content=body.content,
            content_type=body.content_type,
            doc_metadata=body.doc_metadata,
        )
        self.db.add(doc)
        await self.db.flush()

        # Index embedding in pgvector
        vector_id = await self.upsert_knowledge(tenant_id, body.kb_id, doc)
        doc.vector_id = vector_id
        return doc

    async def delete_document(
        self, tenant_id: str, kb_id: str, doc_id: str
    ) -> bool:
        """Delete a document row (embedding deleted automatically)."""
        result = await self.db.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id == uuid.UUID(doc_id),
                KnowledgeDocument.kb_id == uuid.UUID(kb_id),
                KnowledgeDocument.tenant_id == uuid.UUID(tenant_id),
            )
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            return False
        await self.db.delete(doc)
        return True

    async def delete_documents_by_metadata(
        self, tenant_id: str, kb_id: str, metadata_key: str, metadata_value: str
    ) -> int:
        """Delete all documents in a knowledge base matching a specific metadata key/value."""
        from sqlalchemy import delete
        
        # PostgreSQL-specific JSONB containment or key access
        # Since we use JSON column, we use ->> operator in raw text or cast
        from sqlalchemy import text
        
        stmt = (
            delete(KnowledgeDocument)
            .where(
                KnowledgeDocument.tenant_id == uuid.UUID(tenant_id),
                KnowledgeDocument.kb_id == uuid.UUID(kb_id),
                KnowledgeDocument.doc_metadata[metadata_key].astext == metadata_value
            )
        )
        
        result = await self.db.execute(stmt)
        return result.rowcount

    async def delete_all_tenant_knowledge(self, tenant_id: str) -> int:
        """Wipe all knowledge bases and documents for a specific tenant. High-performance operation for self-destruction."""
        from sqlalchemy import delete
        
        # 1. Delete all documents (cascades or manual depending on schema, but let's be explicit)
        doc_stmt = (
            delete(KnowledgeDocument)
            .where(KnowledgeDocument.tenant_id == uuid.UUID(tenant_id))
        )
        doc_result = await self.db.execute(doc_stmt)
        
        # 2. Delete all knowledge bases
        kb_stmt = (
            delete(KnowledgeBase)
            .where(KnowledgeBase.tenant_id == uuid.UUID(tenant_id))
        )
        kb_result = await self.db.execute(kb_stmt)
        
        logger.info(
            "tenant_knowledge_wiped",
            tenant_id=tenant_id,
            deleted_documents=doc_result.rowcount,
            deleted_kbs=kb_result.rowcount
        )
        return doc_result.rowcount
