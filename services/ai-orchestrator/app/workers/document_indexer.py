"""
Document Indexer Worker — async background queue for RAG document ingestion.

Architecture:
  - Documents are uploaded via the /documents endpoint
  - The upload handler pushes a job to the Redis queue ``doc_index_queue``
  - This worker pulls jobs and processes them (chunking + embedding + pgvector upsert)
  - Status is updated in the ``agent_documents`` table

Queue key:    ``doc_index_queue``
Dead-letter:  ``doc_index_dlq`` (after max_retries failures)
Job payload:
  {
    "document_id": str,
    "agent_id":    str,
    "tenant_id":   str,
    "storage_path": str,
    "file_type":   str,
  }
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

_QUEUE_KEY = "doc_index_queue"
_DLQ_KEY = "doc_index_dlq"
_POLL_INTERVAL = 2.0  # seconds between queue checks
_MAX_RETRIES = 3
_CHUNK_SIZE = 400       # tokens per chunk (approximate)
_CHUNK_OVERLAP = 50     # token overlap between adjacent chunks


class DocumentIndexer:
    """
    Async background worker that processes document indexing jobs from Redis.

    :param redis_client: async Redis client
    :param db_factory:   async context manager factory for DB sessions
    :param mcp_client:   MCP client (for calling the RAG service index endpoint)
    """

    def __init__(
        self,
        redis_client: Any,
        db_factory: Any,
        mcp_client: Optional[Any] = None,
    ) -> None:
        self._redis = redis_client
        self._db_factory = db_factory
        self._mcp = mcp_client
        self._running = False

    # ── Public API ────────────────────────────────────────────────────────────

    async def enqueue(self, payload: dict) -> None:
        """Push a document indexing job onto the Redis queue."""
        try:
            await self._redis.rpush(_QUEUE_KEY, json.dumps(payload))
            logger.info(
                "doc_index_enqueued",
                document_id=payload.get("document_id"),
                agent_id=payload.get("agent_id"),
            )
        except Exception as exc:
            logger.error("doc_index_enqueue_error", error=str(exc))

    async def start(self) -> None:
        """Start the background worker loop (runs until stop() is called)."""
        self._running = True
        logger.info("document_indexer_started")
        while self._running:
            try:
                await self._process_one()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("document_indexer_loop_error", error=str(exc))
                await asyncio.sleep(_POLL_INTERVAL)

    def stop(self) -> None:
        """Signal the worker loop to stop."""
        self._running = False
        logger.info("document_indexer_stopped")

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _process_one(self) -> None:
        """
        Blocking-pop one job from the queue (with timeout) and process it.
        """
        raw = await self._redis.blpop(_QUEUE_KEY, timeout=int(_POLL_INTERVAL))
        if raw is None:
            return

        _, job_bytes = raw
        try:
            job = json.loads(job_bytes)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error("doc_index_invalid_job", error=str(exc))
            return

        document_id = job.get("document_id")
        retry_count = job.get("retry_count", 0)

        logger.info("doc_index_processing", document_id=document_id, retry=retry_count)

        try:
            await self._index_document(job)
        except Exception as exc:
            logger.error(
                "doc_index_failed",
                document_id=document_id,
                retry=retry_count,
                error=str(exc),
            )
            if retry_count < _MAX_RETRIES:
                job["retry_count"] = retry_count + 1
                await asyncio.sleep(2 ** retry_count)
                await self._redis.rpush(_QUEUE_KEY, json.dumps(job))
                logger.info("doc_index_requeued", document_id=document_id)
            else:
                # Move to dead-letter queue
                await self._redis.rpush(_DLQ_KEY, json.dumps({**job, "error": str(exc)}))
                await self._mark_failed(document_id, str(exc))
                logger.error("doc_index_dlq", document_id=document_id, error=str(exc))

    async def _index_document(self, job: dict) -> None:
        """Full indexing pipeline: extract text → chunk → generate Gemini embeddings → store in pgvector."""
        document_id = job["document_id"]
        tenant_id = job["tenant_id"]
        storage_path = job["storage_path"]
        file_type = job.get("file_type", "txt")

        from app.services.llm_client import create_llm_client
        from app.models.agent import AgentDocumentChunk
        from sqlalchemy import delete

        # 1. Read file content
        text = await self._extract_text(storage_path, file_type)
        if not text or not text.strip():
            raise ValueError("No text content extracted from document")

        # 2. Chunk the text
        chunks = _chunk_text(text, chunk_size=_CHUNK_SIZE, overlap=_CHUNK_OVERLAP)
        logger.info("doc_index_chunks", document_id=document_id, chunks=len(chunks))

        # 3. Generate embeddings and store in pgvector
        llm_client = create_llm_client()
        vector_ids: list[str] = []
        
        async with self._db_factory() as db:
            # Clear existing chunks if any (re-processing)
            await db.execute(delete(AgentDocumentChunk).where(AgentDocumentChunk.doc_id == uuid.UUID(document_id)))
            
            for i, chunk_text in enumerate(chunks):
                embedding = await llm_client.embed(chunk_text)
                chunk_id = uuid.uuid4()
                chunk = AgentDocumentChunk(
                    id=chunk_id,
                    doc_id=uuid.UUID(document_id),
                    tenant_id=uuid.UUID(tenant_id),
                    content=chunk_text,
                    embedding=embedding,
                    chunk_index=i
                )
                db.add(chunk)
                vector_ids.append(str(chunk_id))
            
            await db.commit()

        # 4. Update document status in DB
        await self._mark_ready(
            document_id=document_id,
            chunk_count=len(chunks),
            vector_ids=vector_ids,
        )

    async def _extract_text(self, storage_path: str, file_type: str) -> str:
        """
        Extract plain text from the file at storage_path.

        Supports: txt, md, pdf (via pdfplumber), docx (via python-docx).
        """
        if not os.path.exists(storage_path):
            raise FileNotFoundError(f"Document file not found: {storage_path}")

        if file_type in ("txt", "md"):
            with open(storage_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()

        if file_type == "pdf":
            try:
                import pdfplumber  # type: ignore
                text_parts = []
                with pdfplumber.open(storage_path) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text() or ""
                        text_parts.append(page_text)
                return "\n".join(text_parts)
            except ImportError:
                logger.warning("pdfplumber_not_installed")
                with open(storage_path, "rb") as f:
                    return f.read().decode("utf-8", errors="replace")

        if file_type == "docx":
            try:
                from docx import Document  # type: ignore
                doc = Document(storage_path)
                return "\n".join(p.text for p in doc.paragraphs)
            except ImportError:
                logger.warning("python_docx_not_installed")
                with open(storage_path, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()

        # Fallback: try reading as text
        with open(storage_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    async def _mark_ready(
        self,
        document_id: str,
        chunk_count: int,
        vector_ids: list,
    ) -> None:
        from sqlalchemy import select
        from app.models.agent import AgentDocument

        try:
            async with self._db_factory() as db:
                result = await db.execute(
                    select(AgentDocument).where(AgentDocument.id == uuid.UUID(document_id))
                )
                doc = result.scalar_one_or_none()
                if doc:
                    doc.status = "ready"
                    doc.chunk_count = chunk_count
                    doc.vector_ids = vector_ids
                    doc.error_message = None
                    await db.commit()
                    logger.info(
                        "doc_index_complete",
                        document_id=document_id,
                        chunks=chunk_count,
                    )
        except Exception as exc:
            logger.error("doc_mark_ready_error", document_id=document_id, error=str(exc))

    async def _mark_failed(self, document_id: str, error: str) -> None:
        from sqlalchemy import select
        from app.models.agent import AgentDocument

        try:
            async with self._db_factory() as db:
                result = await db.execute(
                    select(AgentDocument).where(AgentDocument.id == uuid.UUID(document_id))
                )
                doc = result.scalar_one_or_none()
                if doc:
                    doc.status = "failed"
                    doc.error_message = error[:500]
                    await db.commit()
        except Exception as exc:
            logger.error("doc_mark_failed_error", document_id=document_id, error=str(exc))


# ── Text chunking ─────────────────────────────────────────────────────────────

def _chunk_text(
    text: str,
    chunk_size: int = _CHUNK_SIZE,
    overlap: int = _CHUNK_OVERLAP,
) -> list[str]:
    """
    Split text into overlapping word-token chunks.

    Uses a simple word-based approximation (1 word ≈ 1.3 tokens).
    """
    words = text.split()
    if not words:
        return []

    # Convert chunk_size from approx-tokens to words
    words_per_chunk = max(1, int(chunk_size / 1.3))
    overlap_words = max(0, int(overlap / 1.3))

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + words_per_chunk, len(words))
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk)
        if end >= len(words):
            break
        start += words_per_chunk - overlap_words

    return chunks
