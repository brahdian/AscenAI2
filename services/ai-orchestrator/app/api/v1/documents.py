from __future__ import annotations

import asyncio
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
from app.core.security import get_tenant_db
from app.models.agent import Agent, AgentDocument

logger = structlog.get_logger(__name__)
router = APIRouter()

ALLOWED_EXTENSIONS = {"pdf", "txt", "md", "docx"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

# Magic-byte → allowed extension mapping.  Client-supplied filename and
# Content-Type are untrusted; we validate the actual file content instead.
_DOC_MAGIC: list[tuple[bytes, str]] = [
    (b"%PDF-", "pdf"),                                              # PDF
    (b"PK\x03\x04", "docx"),                                       # ZIP-based (docx, xlsx …)
    # Plain text / markdown: no reliable magic bytes — allowed by extension only
]


def _validate_doc_magic(content: bytes, declared_ext: str) -> None:
    """Raise HTTPException if the file's magic bytes conflict with its extension."""
    if declared_ext in ("txt", "md"):
        # No reliable magic bytes for plain text; accept as-is (already size-limited)
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


async def _verify_agent(agent_id: str, tenant_id: str, db: AsyncSession) -> Agent:
    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return agent


async def _process_document(
    doc_id: str,
    agent_id: str,
    tenant_id: str,
    file_path: Optional[str] = None,
) -> None:
    """
    Background task: read file, split into chunks, generate Gemini embeddings,
    store in AgentDocumentChunk (pgvector), and update the AgentDocument record.
    """
    from app.core.database import AsyncSessionLocal
    from app.services.llm_client import create_llm_client
    from app.models.agent import AgentDocumentChunk

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(AgentDocument).where(AgentDocument.id == uuid.UUID(doc_id))
            )
            doc = result.scalar_one_or_none()
            if not doc:
                logger.error("document_not_found_in_background", doc_id=doc_id)
                return

            # Read file content or use DB content
            try:
                if file_path and os.path.exists(file_path):
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        text = f.read()
                else:
                    text = doc.content or ""
            except Exception as exc:
                logger.error("document_read_error", doc_id=doc_id, error=str(exc))
                doc.status = "failed"
                doc.error_message = f"Failed to read content: {exc}"
                await db.commit()
                return

            if not text.strip():
                doc.status = "ready"
                doc.chunk_count = 0
                doc.vector_ids = []
                await db.commit()
                return

            # Split into chunks (~500 words, 50-word overlap)
            words = text.split()
            chunk_size = 500
            overlap = 50
            chunks: list[str] = []
            start = 0
            while start < len(words):
                end = start + chunk_size
                chunk_text = " ".join(words[start:end])
                if chunk_text.strip():
                    chunks.append(chunk_text)
                start = end - overlap
                if start >= len(words):
                    break

            if not chunks:
                doc.status = "ready"
                doc.chunk_count = 0
                doc.vector_ids = []
                await db.commit()
                return

            # Clear existing chunks if any (re-processing)
            from sqlalchemy import delete
            await db.execute(delete(AgentDocumentChunk).where(AgentDocumentChunk.doc_id == doc.id))

            # Generate embeddings and store in pgvector
            llm_client = create_llm_client()
            vector_ids: list[str] = []
            
            for i, chunk_text in enumerate(chunks):
                try:
                    embedding = await llm_client.embed(chunk_text)
                    chunk_id = uuid.uuid4()
                    chunk = AgentDocumentChunk(
                        id=chunk_id,
                        doc_id=doc.id,
                        tenant_id=doc.tenant_id,
                        content=chunk_text,
                        embedding=embedding,
                        chunk_index=i
                    )
                    db.add(chunk)
                    vector_ids.append(str(chunk_id))
                except Exception as exc:
                    logger.error("chunk_embedding_failed", doc_id=doc_id, chunk_index=i, error=str(exc))
                    # Continue with other chunks if possible, or fail the whole doc? 
                    # For now, let's fail the whole doc if embedding fails
                    raise exc

            doc.status = "ready"
            doc.chunk_count = len(chunks)
            doc.vector_ids = vector_ids
            # Store the first chunk's embedding as the document's representative embedding if needed
            if chunks:
                # We already have the embedding from the loop, but we need to re-fetch if we didn't save it
                # For simplicity, let's just use the last one or re-save
                pass

            await db.commit()
            logger.info("document_processed_pgvector", doc_id=doc_id, chunks=len(chunks))

        except Exception as exc:
            logger.error("document_processing_failed", doc_id=doc_id, error=str(exc))
            try:
                # Use a fresh query to avoid session issues
                result = await db.execute(
                    select(AgentDocument).where(AgentDocument.id == uuid.UUID(doc_id))
                )
                doc = result.scalar_one_or_none()
                if doc:
                    doc.status = "failed"
                    doc.error_message = str(exc)
                    await db.commit()
            except Exception:
                pass


@router.get("/{agent_id}/documents")
async def list_documents(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
) -> list[dict]:
    """List all documents for an agent."""
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db)

    result = await db.execute(
        select(AgentDocument)
        .where(AgentDocument.agent_id == uuid.UUID(agent_id))
        .order_by(AgentDocument.created_at.desc())
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
async def create_text_document(
    agent_id: str,
    payload: TextDocumentCreateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Create a raw text document directly. Defaults to 'draft' unless status='published'."""
    tenant_id = _tenant_id(request)
    agent = await _verify_agent(agent_id, tenant_id, db)

    initial_status = payload.status or "draft"
    if initial_status == "published":
        initial_status = "processing"

    doc = AgentDocument(
        id=uuid.uuid4(),
        agent_id=agent.id,
        tenant_id=agent.tenant_id,
        name=payload.name,
        file_type="txt",
        file_size_bytes=len(payload.content.encode('utf-8')),
        content=payload.content,
        status=initial_status,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # Trigger processing if published
    if payload.status == "published":
        background_tasks.add_task(
            _process_document,
            doc_id=str(doc.id),
            agent_id=agent_id,
            tenant_id=tenant_id,
            file_path=doc.storage_path
        )

    return doc.to_dict()


@router.put("/{agent_id}/documents/{doc_id}")
async def update_document(
    agent_id: str,
    doc_id: str,
    payload: TextDocumentUpdateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Update a text document. If status changes to 'published', triggers background processing."""
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db)

    result = await db.execute(select(AgentDocument).where(AgentDocument.id == uuid.UUID(doc_id), AgentDocument.agent_id == uuid.UUID(agent_id)))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    if payload.name is not None:
        doc.name = payload.name
    if payload.content is not None:
        doc.content = payload.content
        doc.file_size_bytes = len(payload.content.encode('utf-8'))
        
    previously_draft = (doc.status == "draft")
    
    if payload.status is not None:
        if payload.status == "published":
            doc.status = "processing"
        else:
            doc.status = payload.status

    await db.commit()
    await db.refresh(doc)

    # Trigger processing if transitioning to published
    if previously_draft and payload.status == "published":
        background_tasks.add_task(
            _process_document,
            doc_id=str(doc.id),
            agent_id=agent_id,
            tenant_id=tenant_id,
            file_path=doc.storage_path
        )

    return doc.to_dict()


@router.post("/{agent_id}/documents", status_code=201)
async def upload_document(
    agent_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """
    Upload a document for an agent.
    Accepts: pdf, txt, md, docx (up to 10 MB).
    Stores the file, creates an AgentDocument record, and launches background processing.
    """
    tenant_id = _tenant_id(request)
    agent = await _verify_agent(agent_id, tenant_id, db)

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
        vector_ids=[],
        status="processing",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # Launch background processing
    background_tasks.add_task(
        _process_document,
        doc_id=str(doc.id),
        agent_id=agent_id,
        tenant_id=tenant_id,
        file_path=storage_path,
    )

    logger.info("document_upload_queued", doc_id=str(doc.id), agent_id=agent_id, filename=filename)
    return doc.to_dict()


@router.delete("/{agent_id}/documents/{doc_id}")
async def delete_document(
    agent_id: str,
    doc_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Delete a document and remove its vectors from the database."""
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db)

    result = await db.execute(
        select(AgentDocument).where(
            AgentDocument.id == uuid.UUID(doc_id),
            AgentDocument.agent_id == uuid.UUID(agent_id),
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Remove file from disk (best-effort)
    try:
        if doc.storage_path and os.path.exists(doc.storage_path):
            os.remove(doc.storage_path)
    except Exception as exc:
        logger.warning("file_delete_failed", doc_id=doc_id, error=str(exc))

    await db.delete(doc)
    await db.commit()
    logger.info("document_deleted", doc_id=doc_id, agent_id=agent_id)
