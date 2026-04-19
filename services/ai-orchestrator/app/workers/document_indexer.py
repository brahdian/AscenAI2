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

from app.core.leadership import RedisLeaderLease

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
        self._lease = RedisLeaderLease(redis_client, "ai-orchestrator:document-indexer")

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
        if not await self._lease.acquire_or_renew():
            await asyncio.sleep(_POLL_INTERVAL)
            return

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

        # ── Distributed Locking for Coalescence ──────────────────────────────
        # Ensure only one worker processes a specific document at a time.
        # This prevents "Chunk Multiplying" race conditions.
        lock_key = f"doc_index_lock:{document_id}"
        lock_acquired = await self._redis.set(lock_key, "1", nx=True, ex=300)  # 5 minute TTL
        if not lock_acquired:
            logger.info("doc_index_locked_skipping", document_id=document_id)
            # Re-enqueue for later processing
            await self._redis.rpush(_QUEUE_KEY, json.dumps(job))
            await asyncio.sleep(1.0)
            return

        logger.info("doc_index_processing", document_id=document_id, retry=retry_count)

        try:
            # Phase 9 — Gap 2: Enforce per-document indexing timeout (60s)
            # to prevent malicious files from starving worker resources.
            await asyncio.wait_for(self._index_document(job), timeout=60.0)
        except asyncio.TimeoutError:
            logger.error("doc_index_timeout", document_id=document_id, timeout=60, trace_id=job.get("trace_id"))
            await self._mark_failed(document_id, "Indexing timed out after 60 seconds (Worker Guardrail)")
        except Exception as exc:
            logger.error(
                "doc_index_failed",
                document_id=document_id,
                retry=retry_count,
                trace_id=job.get("trace_id"),
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
                
                # Harden: Cascade cleanup to MCP on final failure to prevent "Zombie" chunks
                try:
                    await self._cleanup_mcp_partially(job)
                except Exception as cleanup_exc:
                    logger.warning("doc_index_final_cleanup_failed", error=str(cleanup_exc))

                await self._mark_failed(document_id, str(exc))
                logger.error("doc_index_dlq", document_id=document_id, error=str(exc))
        finally:
            await self._redis.delete(lock_key)
            
            # G11 Hardening: Attempt to process a few pending purges from the registry
            await self._process_pending_purges()

    async def _index_document(self, job: dict) -> None:
        """Full indexing pipeline: extract text → moderate → chunk → generate Gemini embeddings → store in pgvector."""
        document_id = job["document_id"]
        tenant_id = job["tenant_id"]
        storage_path = job["storage_path"]
        file_type = job.get("file_type", "txt")

        from app.services.llm_client import create_llm_client
        from app.models.agent import AgentDocumentChunk
        from app.services.moderation_service import ModerationService
        from app.core.config import settings
        from sqlalchemy import delete

        extraction_start = asyncio.get_event_loop().time()
        
        if job.get("content"):
            text = job["content"]
        else:
            text = await self._extract_text(storage_path, file_type)

        extraction_duration = asyncio.get_event_loop().time() - extraction_start

        # 1. Task 1: Ingestion Safety (Moderation)
        mod_service = ModerationService(openai_api_key=settings.OPENAI_API_KEY)
        mod_result = await mod_service.check_input(text)
        
        if mod_result.is_blocked:
            logger.warning("doc_index_moderation_blocked", document_id=document_id, categories=mod_result.categories)
            raise ValueError(f"Content safety violation: {mod_result.reason}")

        # Task 2: Extraction Quality Metrics
        file_size = 0
        if job.get("storage_path") and os.path.exists(job["storage_path"]):
            file_size = os.path.getsize(job["storage_path"])
        
        char_count = len(text or "")
        density = char_count / file_size if file_size > 0 else 1.0
        
        quality_metadata = {
            "char_count": char_count,
            "file_size_bytes": file_size,
            "density": float(f"{density:.6f}"),
            "extraction_duration_sec": float(f"{extraction_duration:.3f}"),
            "moderation_provider": mod_result.provider,
            "moderation_severity": mod_result.severity,
            "is_suspiciously_low_density": False
        }

        # G12: High-Fidelity Extraction Check (CHARS / BYTES)
        # If a large file yields almost no text, it's likely an image-only PDF/OCR failure.
        if not job.get("content") and file_size > 0:
            # Binary files (PDF/DOCX) usually have lower density, but 0.0001 is a red flag
            threshold = 0.0001 if file_type in ("pdf", "docx") else 0.01
            if density < threshold:
                quality_metadata["is_suspiciously_low_density"] = True
                logger.warning("low_extraction_density_detected", document_id=document_id, density=density)
                await self._update_doc_warning(document_id, "Low quality text extraction detected. File may require OCR or be protected.")

        # Update extraction_metadata in DB
        await self._update_extraction_metadata(document_id, quality_metadata)

        if not text or not text.strip():
            raise ValueError("No text content extracted from document")

        # 2. Compliance: PII Redaction
        # Scrub sensitive data before vectorization to ensure privacy/HIPAA.
        from app.services import pii_service
        try:
            # Check if agent has guardrails enabled for PII
            async with self._db_factory() as db:
                from app.models.agent import Agent, AgentGuardrails
                from sqlalchemy import select
                agent_res = await db.execute(select(Agent).where(Agent.id == uuid.UUID(job["agent_id"])))
                agent = agent_res.scalar_one_or_none()
                
                guardrails_res = await db.execute(select(AgentGuardrails).where(AgentGuardrails.agent_id == agent.id))
                guardrails = guardrails_res.scalar_one_or_none()
                
                # If guardrails exist and PII redaction is active, scrub it.
                if guardrails and guardrails.config.get("pii_redaction"):
                    pii_ctx = pii_service.PIIContext(tenant_id=tenant_id)
                    text = pii_service.redact_pii(text, pii_ctx, session_id=f"doc_{document_id}")
                    logger.info("doc_index_pii_redacted", document_id=document_id)
        except Exception as pii_exc:
            logger.warning("doc_index_pii_redaction_skip", document_id=document_id, error=str(pii_exc))

        # 3. Chunk the text
        chunks = _chunk_text(text, chunk_size=_CHUNK_SIZE, overlap=_CHUNK_OVERLAP)
        logger.info("doc_index_chunks", document_id=document_id, chunks=len(chunks))

        # 4. Generate embeddings and store in pgvector (Local + MCP Sync)
        llm_client = create_llm_client()
        
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
                    chunk_index=i,
                    trace_id=job.get("trace_id") # Zenith Pillar 1
                )
                db.add(chunk)
            
            await db.commit()

        # Sync context to MCP Server Context Hub for actual retrieval
        if self._mcp:
            try:
                from sqlalchemy import select
                from app.models.agent import Agent
                async with self._db_factory() as db:
                    agent_res = await db.execute(select(Agent).where(Agent.id == uuid.UUID(job["agent_id"])))
                    agent = agent_res.scalar_one_or_none()
                    agent_name = agent.name if agent else "Agent"
                    
                kb_id = await self._mcp.get_or_create_agent_kb(tenant_id, job["agent_id"], agent_name)
                
                # Pre-cleanup in MCP for this doc (idempotency)
                await self._mcp.cleanup_knowledge_by_metadata(tenant_id, kb_id, "document_id", document_id)

                for i, chunk_text in enumerate(chunks):
                    # Harden: Deep-redact metadata before syncing to vector store
                    raw_metadata = {
                        "document_id": document_id,
                        "agent_id": job["agent_id"],
                        "source": job.get('filename', 'upload'),
                        "actor_email": job.get("actor_email")
                    }
                    redacted_metadata = pii_service.redact_deep(raw_metadata)

                    # Phase 7 — Gap 3: Semantic Deduplication via ANN check
                    # Embed the chunk and compare against existing chunks in the DB.
                    # If a near-identical chunk (score > 0.97) already exists from a
                    # different document, mark this as a semantic duplicate to suppress it.
                    is_semantic_dup = False
                    try:
                        from app.models.agent import AgentDocumentChunk
                        from sqlalchemy import select, text as sql_text
                        chunk_emb = await llm_client.embed(chunk_text)
                        async with self._db_factory() as dup_db:
                            # Use pgvector ANN: cosine similarity > 0.97 means near-duplicate
                            dup_res = await dup_db.execute(
                                sql_text(
                                    """
                                    SELECT id FROM agent_document_chunks
                                    WHERE tenant_id = :tid
                                      AND doc_id != :doc_id
                                      AND 1 - (embedding <=> cast(:emb as vector)) > 0.97
                                    LIMIT 1
                                    """
                                ),
                                {"tid": tenant_id, "doc_id": document_id, "emb": str(chunk_emb)},
                            )
                            if dup_res.fetchone():
                                is_semantic_dup = True
                                logger.info("semantic_duplicate_chunk_detected", document_id=document_id, chunk_index=i)
                    except Exception as _sem_exc:
                        logger.debug("semantic_dup_check_skipped", error=str(_sem_exc))

                    if is_semantic_dup:
                        redacted_metadata["is_semantic_duplicate"] = "true"

                    # Phase 9 — Gap 1: Critical — content-level PII redaction (platform baseline)
                    # We always redact raw text content before storing in the vector repository.
                    redacted_chunk = pii_service.redact(chunk_text)

                    await self._mcp.upsert_knowledge_document(
                        tenant_id=tenant_id,
                        kb_id=kb_id,
                        title=pii_service.redact(f"{job.get('filename', 'Doc')} - Pt {i+1}"),
                        content=redacted_chunk,
                        doc_metadata=redacted_metadata,
                        trace_id=job.get("trace_id")
                    )

                logger.info("doc_index_mcp_synced", document_id=document_id, chunks=len(chunks), trace_id=job.get("trace_id"))
            except Exception as mcp_exc:
                logger.warning("doc_index_mcp_sync_failed", error=str(mcp_exc), trace_id=job.get("trace_id"))
                # G11: Register for retry if cleanup/sync failed to prevent "Ghost Chunks"
                await self._register_purge_retry(tenant_id, job["agent_id"], document_id)

        # 5. Update document status in DB
        await self._mark_ready(
            document_id=document_id,
            chunk_count=len(chunks),
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
                    # Phase 10 — Gap 2: PDF Resource Guardrail (max 100 pages)
                    for i, page in enumerate(pdf.pages):
                        if i >= 100:
                            logger.warning("pdf_page_limit_reached", storage_path=storage_path, total_pages=len(pdf.pages))
                            text_parts.append("\n... [EXTRACTION TRUNCATED AT 100 PAGES]")
                            break
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
                    # doc.vector_ids = vector_ids  # DEPRECATED: Relying on relationship in AgentDocumentChunk
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

    async def _cleanup_mcp_partially(self, job: dict) -> None:
        """Attempt to clear any chunks already pushed to MCP for a failed job."""
        if not self._mcp:
            return
        
        tenant_id = job["tenant_id"]
        agent_id = job["agent_id"]
        document_id = job["document_id"]
        
        kb_id = await self._mcp.get_or_create_agent_kb(tenant_id, agent_id, "System")
        await self._mcp.cleanup_knowledge_by_metadata(tenant_id, kb_id, "document_id", document_id)
        logger.info("doc_index_mcp_zombie_cleanup", document_id=document_id)

    async def _update_doc_warning(self, document_id: str, warning: str) -> None:
        """Update document with a warning message while preserving status."""
        from sqlalchemy import select
        from app.models.agent import AgentDocument
        try:
            async with self._db_factory() as db:
                result = await db.execute(select(AgentDocument).where(AgentDocument.id == uuid.UUID(document_id)))
                doc = result.scalar_one_or_none()
                if doc:
                    doc.error_message = f"Warning: {warning}"
                    await db.commit()
        except Exception as e:
            logger.warning("failed_to_update_doc_warning", error=str(e))

    async def _update_extraction_metadata(self, document_id: str, metadata: dict) -> None:
        """Persist quality metrics into the document record."""
        from sqlalchemy import select
        from app.models.agent import AgentDocument
        try:
            async with self._db_factory() as db:
                result = await db.execute(select(AgentDocument).where(AgentDocument.id == uuid.UUID(document_id)))
                doc = result.scalar_one_or_none()
                if doc:
                    doc.extraction_metadata = metadata
                    await db.commit()
        except Exception as e:
            logger.warning("failed_to_update_extraction_metadata", error=str(e))

    async def _register_purge_retry(self, tenant_id: str, agent_id: str, document_id: str) -> None:
        """Record a failed cleanup for later background retry."""
        retry_key = "doc_index_purge_retries"
        payload = json.dumps({"tid": tenant_id, "aid": agent_id, "did": document_id})
        await self._redis.sadd(retry_key, payload)
        logger.info("mcp_purge_retry_registered", document_id=document_id)

    async def _process_pending_purges(self) -> None:
        """Attempt to clear a few items from the purge registry."""
        if not self._mcp or not self._redis:
            return
        retry_key = "doc_index_purge_retries"
        # Pop up to 5 items to keep it light
        for _ in range(5):
            raw = await self._redis.spop(retry_key)
            if not raw:
                break
            try:
                data = json.loads(raw)
                kb_id = await self._mcp.get_or_create_agent_kb(data["tid"], data["aid"], "System")
                await self._mcp.cleanup_knowledge_by_metadata(data["tid"], kb_id, "document_id", data["did"])
                logger.info("mcp_purge_retry_success", document_id=data["did"])
            except Exception as e:
                # Put it back if it failed again
                await self._redis.sadd(retry_key, raw)
                logger.debug("mcp_purge_retry_failed_still", error=str(e))
                break


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
