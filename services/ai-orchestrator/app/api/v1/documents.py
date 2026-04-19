from __future__ import annotations

import hashlib
import os
import uuid
from typing import Optional, Any
from pathlib import Path

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel, Field
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_tenant_db, require_forwarded_role
from app.models.agent import Agent, AgentDocument, AgentDocumentChunk
from app.services import pii_service
from app.services.mcp_client import MCPClient
from app.core.zenith import ZenithContext, get_zenith_context

logger = structlog.get_logger(__name__)
router = APIRouter()

# ── Redis Lock Constants ──────────────────────────────────────────────────
_DOC_LOCK_PREFIX = "doc_lock:"
_DOC_LOCK_TTL = 300  # 5 minutes

ALLOWED_EXTENSIONS = {"pdf", "txt", "md", "docx"}
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB (Harden: DoS prevention)
MAX_LINE_LENGTH = 10000  # Max chars per line to prevent Regex DoS

# Phase 7 — Gap 4: Ingestion Rate Limiting
_UPLOAD_RATE_LIMIT = 20      # max uploads per window
_UPLOAD_RATE_WINDOW = 3600  # 1 hour in seconds

# Magic-byte → allowed extension mapping.  Client-supplied filename and
# Content-Type are untrusted; we validate the actual file content instead.
_DOC_MAGIC: list[tuple[bytes, str]] = [
    (b"%PDF-", "pdf"),                                              # PDF
    (b"PK\x03\x04", "docx"),                                       # ZIP-based (docx, xlsx …)
    # Plain text / markdown: no reliable magic bytes — allowed by extension only
]


def _validate_doc_magic(content: bytes, declared_ext: str) -> None:
    """Raise HTTPException if the file's magic bytes conflict with its extension."""
    # Phase 10 — Gap 1: Adversarial Magic-Byte Denylist
    MALICIOUS_HEADERS = [
        b"MZ",          # Windows/DOS Executable
        b"\x7fELF",     # Linux Executable
        b"\xca\xfe\xba\xbe", # Java Class / Mach-O Fat Binary
        b"\xce\xfa\xed\xfe", # Mach-O
        b"\xcf\xfa\xed\xfe", # Mach-O
    ]
    for bad_magic in MALICIOUS_HEADERS:
        if content.startswith(bad_magic):
            raise HTTPException(status_code=400, detail="Executable formats are strictly prohibited.")

    if declared_ext in ("txt", "md"):
        # Harden: Check for extremely long lines to prevent Regex DoS in PII service
        try:
            text_content = content.decode("utf-8", errors="replace")
            for i, line in enumerate(text_content.splitlines()):
                if len(line) > MAX_LINE_LENGTH:
                     raise HTTPException(
                        status_code=400,
                        detail=f"Line {i+1} exceeds maximum length of {MAX_LINE_LENGTH} characters. Potential DoS detected.",
                    )
        except UnicodeDecodeError:
             raise HTTPException(status_code=400, detail="Text file contains invalid UTF-8 sequence.")
        return
    for magic, expected_ext in _DOC_MAGIC:
        if content[:len(magic)] == magic:
            if declared_ext != expected_ext:
                raise HTTPException(
                    status_code=400,
                    detail=f"File content does not match declared extension '.{declared_ext}'.",
                )
            return
    # None of the known magic bytes matched for a binary format
    if declared_ext in ("pdf", "docx"):
        raise HTTPException(
            status_code=400,
            detail=f"File does not appear to be a valid .{declared_ext} document.",
        )


def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


async def _check_upload_rate_limit(redis_client: Any, tenant_id: str) -> None:
    """Zenith Pillar 4: Redis-backed upload rate limiting."""
    if not redis_client:
        return
    key = f"doc_upload_rl:{tenant_id}"
    try:
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, _UPLOAD_RATE_WINDOW)
        if count > _UPLOAD_RATE_LIMIT:
            ttl = await redis_client.ttl(key)
            raise HTTPException(
                status_code=429,
                detail=f"Upload rate limit exceeded. Forensic Trace: {tenant_id}",
                headers={"Retry-After": str(max(ttl, 1))},
            )
    except HTTPException:
        raise
    except Exception as rl_exc:
        logger.warning("upload_rate_limit_check_failed", tenant_id=tenant_id, error=str(rl_exc))


async def _verify_agent(agent_id: str, tenant_id: str, db: AsyncSession, ctx: ZenithContext | None = None) -> Agent:
    """Zenith Pillar 3: Isolation Locks and Agent Verification."""
    agent_uuid = uuid.UUID(agent_id)
    
    # Apply isolation (CRIT-005 / Zenith Pillar 3)
    if ctx and ctx.restricted_agent_id and agent_uuid != ctx.restricted_agent_id:
        logger.warning("agent_isolation_violation", agent_id=agent_id, restricted_id=str(ctx.restricted_agent_id))
        raise HTTPException(status_code=404, detail="Agent not found.")

    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_uuid,
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return agent


# Removed broken inline _process_document. Processing is now handled by app.workers.document_indexer.


@router.get("/{agent_id}/documents")
@zenith_error_handler
async def list_documents(
    agent_id: str,
    include_archived: bool = False,
    db: AsyncSession = Depends(get_tenant_db),
    ctx: ZenithContext = Depends(get_zenith_context),
) -> list[dict]:
    """List documents for an agent. By default excludes archived docs.
    Deterministic sorting enforced: created_at DESC, id DESC."""
    await _verify_agent(agent_id, ctx.tenant_id, db, ctx=ctx)

    from sqlalchemy import and_
    filters = [AgentDocument.agent_id == uuid.UUID(agent_id)]
    if not include_archived:
        filters.append(AgentDocument.status != "archived")

    result = await db.execute(
        select(AgentDocument)
        .where(and_(*filters))
        .order_by(AgentDocument.created_at.desc(), AgentDocument.id.desc())
    )
    return [doc.to_dict() for doc in result.scalars().all()]


class TextDocumentCreateRequest(BaseModel):
    name: str = Field(..., max_length=255)
    content: str
    status: Optional[str] = Field(None, pattern="^(draft|published)$")

class TextDocumentUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    content: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(draft|published)$")


@router.post("/{agent_id}/documents/text", status_code=201)
@zenith_error_handler
async def create_text_document(
    agent_id: str,
    payload: TextDocumentCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    ctx: ZenithContext = Depends(get_zenith_context),
    role: str = Depends(require_forwarded_role("admin")),
) -> dict:
    """Create a raw text document directly. Defaults to 'draft' unless status='published'."""
    agent = await _verify_agent(agent_id, ctx.tenant_id, db, ctx=ctx)
    # Rate limit check (Resilience Layer)
    # Note: _check_upload_rate_limit would need adjusting or just use ctx.tenant_id

    initial_status = payload.status or "draft"
    if initial_status == "published":
        initial_status = "processing"

    # Harden: Size and Line Length validation for direct text input
    text_bytes = payload.content.encode('utf-8')
    if len(text_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Text content exceeds 5MB limit.")
    
    for i, line in enumerate(payload.content.splitlines()):
        if len(line) > MAX_LINE_LENGTH:
             raise HTTPException(status_code=400, detail=f"Line {i+1} exceeds maximum length.")

    # Calculate SHA-256 for deduplication
    content_hash = hashlib.sha256(text_bytes).hexdigest()

    doc = AgentDocument(
        id=uuid.uuid4(),
        agent_id=agent.id,
        tenant_id=agent.tenant_id,
        name=payload.name,
        file_type="txt",
        file_size_bytes=len(text_bytes),
        content=payload.content,
        content_hash=content_hash,
        status=initial_status,
        # Zenith Pillar 1: Identity & Traceability
        created_by=ctx.actor_email,
        trace_id=ctx.trace_id,
        original_ip=ctx.original_ip,
        justification_id=ctx.justification_id
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # Deduplication Check (Same Agent + Ready Content)
    # G22 Fix: We STILL index the duplicate so it has its own search vectors (required by MCP id-binding),
    # but we can reuse the DB hash for reporting.
    dup_res = await db.execute(
        select(AgentDocument).where(
            AgentDocument.agent_id == agent.id,
            AgentDocument.content_hash == content_hash,
            AgentDocument.status == "ready",
            AgentDocument.id != doc.id,
        ).limit(1)
    )
    duplicate = dup_res.scalar_one_or_none()
    if duplicate:
        logger.info("document_deduplication_hit", doc_id=str(doc.id), source_doc_id=str(duplicate.id))

    # Trigger durable background processing if published
    if payload.status == "published":
        indexer = request.app.state.document_indexer
        await indexer.enqueue({
            "document_id": str(doc.id),
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "content": doc.content,
            "filename": doc.name,
            "file_type": doc.file_type
        })

    return doc.to_dict()


@router.put("/{agent_id}/documents/{doc_id}")
@zenith_error_handler
async def update_document(
    agent_id: str,
    doc_id: str,
    payload: TextDocumentUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    ctx: ZenithContext = Depends(get_zenith_context),
    role: str = Depends(require_forwarded_role("admin")),
) -> dict:
    """Update a text document. Zenith forensic update."""
    await _verify_agent(agent_id, ctx.tenant_id, db, ctx=ctx)

    result = await db.execute(select(AgentDocument).where(AgentDocument.id == uuid.UUID(doc_id), AgentDocument.agent_id == uuid.UUID(agent_id)))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    if payload.name is not None:
        doc.name = payload.name
    if payload.content is not None:
        doc.content = payload.content
        text_bytes = payload.content.encode('utf-8')
        doc.file_size_bytes = len(text_bytes)
        doc.content_hash = hashlib.sha256(text_bytes).hexdigest()
        
    previously_draft = (doc.status == "draft")
    
    if payload.status is not None:
        if payload.status == "published":
            doc.status = "processing"
        else:
            doc.status = payload.status

    await db.commit()
    await db.refresh(doc)

    # Trigger re-indexing if content changed or if doc is being published
    # Fix P0: Ensure content updates result in vector updates
    content_changed = (payload.content is not None)
    if should_reindex:
        doc.status = "processing"
        doc.updated_at = func.now()
        doc.updated_by = ctx.actor_email
        doc.trace_id = ctx.trace_id
        await db.commit()
        
        # Zenith Pillar 1: Propagate forensic metadata to the worker
        indexer = request.app.state.document_indexer
        await indexer.enqueue({
            "document_id": str(doc.id),
            "agent_id": agent_id,
            "tenant_id": ctx.tenant_id,
            "content": doc.content,
            "storage_path": doc.storage_path,
            "filename": doc.name,
            "file_type": doc.file_type,
            "trace_id": ctx.trace_id,
            "actor_email": ctx.actor_email
        })
        logger.info("document_reindex_queued", doc_id=str(doc.id), trace_id=ctx.trace_id)

    return doc.to_dict()


@router.post("/{agent_id}/documents", status_code=201)
@zenith_error_handler
async def upload_document(
    agent_id: str,
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_tenant_db),
    ctx: ZenithContext = Depends(get_zenith_context),
    role: str = Depends(require_forwarded_role("admin")),
) -> dict:
    """
    Upload a document for an agent. Zenith forensic upload.
    Accepts: pdf, txt, md, docx (up to 10 MB).
    """
    agent = await _verify_agent(agent_id, ctx.tenant_id, db, ctx=ctx)
    redis_client = getattr(request.app.state, "redis", None)
    await _check_upload_rate_limit(redis_client, ctx.tenant_id)

    # Validate file extension — strip path components to prevent path traversal
    filename = Path(file.filename or "upload").name
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # Read content and enforce size limit
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB.",
        )

    # Validate actual file content against declared extension
    _validate_doc_magic(content, ext)

    # Store file — use persistent storage path (configure DOCUMENT_STORAGE_PATH env var)
    doc_uuid = uuid.uuid4()
    storage_dir = Path(settings.DOCUMENT_STORAGE_PATH) / tenant_id / agent_id
    storage_dir.mkdir(parents=True, exist_ok=True)
    safe_filename = f"{doc_uuid}_{filename}"
    storage_path = str(storage_dir / safe_filename)

    try:
        with open(storage_path, "wb") as f_out:
            f_out.write(content)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to store file: {exc}")

    # Calculate SHA-256 for binary content deduplication
    content_hash = hashlib.sha256(content).hexdigest()

    # Create DB record
    doc = AgentDocument(
        id=doc_uuid,
        agent_id=agent.id,
        tenant_id=agent.tenant_id,
        name=filename,
        file_type=ext,
        file_size_bytes=len(content),
        storage_path=storage_path,
        chunk_count=0,
        content_hash=content_hash,
        status="processing",
        # Zenith Pillar 1: Identity & Traceability
        created_by=ctx.actor_email,
        trace_id=ctx.trace_id,
        original_ip=ctx.original_ip,
        justification_id=ctx.justification_id
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # Deduplication & Storage Reuse (G19/G22)
    # We always re-index the duplicate so it has its own vectors in MCP,
    # BUT we can reuse the storage_path if another doc in the same agent has the same hash.
    dup_res = await db.execute(
        select(AgentDocument).where(
            AgentDocument.agent_id == agent.id,
            AgentDocument.content_hash == content_hash,
            AgentDocument.status == "ready",
            AgentDocument.id != doc.id,
        ).limit(1)
    )
    duplicate = dup_res.scalar_one_or_none()

    if duplicate and duplicate.storage_path:
         logger.info("document_deduplication_storage_hit", doc_id=str(doc.id), source_doc_id=str(duplicate.id))
         # Re-use existing storage but force new indexing under new doc_uuid
         doc.storage_path = duplicate.storage_path
         # Try to clean up the newly created (redundant) file on disk since we're pivoting to the existing one
         try:
             if storage_path != duplicate.storage_path and os.path.exists(storage_path):
                 os.remove(storage_path)
         except Exception: pass
         storage_path = duplicate.storage_path

    # Launch durable background processing via Redis queue
    indexer = request.app.state.document_indexer
    await indexer.enqueue({
        "document_id": str(doc.id),
        "agent_id": agent_id,
        "tenant_id": tenant_id,
        "storage_path": storage_path,
        "filename": filename,
        "file_type": ext
    })

    logger.info("document_upload_queued", doc_id=str(doc.id), agent_id=agent_id, filename=filename)
    return doc.to_dict()


@router.post("/{agent_id}/documents/{doc_id}/retry")
@zenith_error_handler
async def retry_document_indexing(
    agent_id: str,
    doc_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    ctx: ZenithContext = Depends(get_zenith_context),
    role: str = Depends(require_forwarded_role("admin")),
) -> dict:
    """Retry indexing for a failed document"""
    await _verify_agent(agent_id, ctx.tenant_id, db, ctx=ctx)
    
    result = await db.execute(
        select(AgentDocument).where(
            AgentDocument.id == uuid.UUID(doc_id),
            AgentDocument.agent_id == uuid.UUID(agent_id),
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    
    doc.status = "processing"
    doc.error_message = None
    doc.chunk_count = 0
    doc.updated_by = ctx.actor_email
    doc.trace_id = ctx.trace_id
    await db.commit()
    
    indexer = request.app.state.document_indexer
    await indexer.enqueue({
        "document_id": str(doc.id),
        "agent_id": agent_id,
        "tenant_id": ctx.tenant_id,
        "storage_path": doc.storage_path,
        "content": doc.content,
        "filename": doc.name,
        "file_type": doc.file_type,
        "trace_id": ctx.trace_id,
        "actor_email": ctx.actor_email
    })
    
    logger.info("document_reindex_queued", doc_id=str(doc.id), trace_id=ctx.trace_id)
    return doc.to_dict()


@router.delete("/{agent_id}/documents/{doc_id}")
@zenith_error_handler
async def delete_document(
    agent_id: str,
    doc_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    ctx: ZenithContext = Depends(get_zenith_context),
    role: str = Depends(require_forwarded_role("admin")),
):
    """Delete a document and remove its vectors from the database. Zenith forensic deletion."""
    await _verify_agent(agent_id, ctx.tenant_id, db, ctx=ctx)

    result = await db.execute(
        select(AgentDocument).where(
            AgentDocument.id == uuid.UUID(doc_id),
            AgentDocument.agent_id == uuid.UUID(agent_id),
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Remove file from disk (Hardened: only if not shared by other documents) (G17/G16 Fix)
    try:
        if doc.storage_path:
            # Check if any OTHER documents are using this same physical file
            shared_res = await db.execute(
                select(func.count(AgentDocument.id)).where(
                    AgentDocument.storage_path == doc.storage_path,
                    AgentDocument.id != doc.id
                )
            )
            shared_count = shared_res.scalar() or 0
            if shared_count == 0 and os.path.exists(doc.storage_path):
                os.remove(doc.storage_path)
                logger.info("document_physically_deleted", path=doc.storage_path)
            else:
                logger.info("document_file_preserved_sharing", path=doc.storage_path, count=shared_count)
    except Exception as exc:
        logger.warning("file_delete_failed", doc_id=doc_id, error=str(exc))

    # ── Sync Deletion to MCP Context Server (Zenith Pillar 3: Inter-Service Zero-Trust) ────
    try:
        mcp = getattr(request.app.state, "mcp_client", None)
        if mcp:
            # Fetch KB ID for this agent
            kb_id = await mcp.get_or_create_agent_kb(ctx.tenant_id, agent_id, "Cleanup")
            # Perform bulk cleanup of all chunks associated with this document ID
            # Propagate trace_id for cross-service forensic correlation
            deleted_count = await mcp.cleanup_knowledge_by_metadata(
                ctx.tenant_id, kb_id, "document_id", str(doc.id), trace_id=ctx.trace_id
            )
            logger.info("mcp_knowledge_cleanup_complete", doc_id=doc_id, trace_id=ctx.trace_id, deleted_chunks=deleted_count)
    except Exception as exc:
        logger.warning("mcp_cleanup_failed", doc_id=doc_id, trace_id=ctx.trace_id, error=str(exc))

    await db.delete(doc)
    await db.commit()
    logger.info("document_deleted", doc_id=doc_id, agent_id=agent_id)
