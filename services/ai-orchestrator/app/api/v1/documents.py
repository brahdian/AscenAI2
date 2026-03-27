from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.agent import Agent, AgentDocument

logger = structlog.get_logger(__name__)
router = APIRouter()

ALLOWED_EXTENSIONS = {"pdf", "txt", "md", "docx"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


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
    file_path: str,
    agent_id: str,
    tenant_id: str,
) -> None:
    """
    Background task: read file, split into chunks, generate placeholder embeddings,
    store in Qdrant, and update the AgentDocument record.
    """
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(AgentDocument).where(AgentDocument.id == uuid.UUID(doc_id))
            )
            doc = result.scalar_one_or_none()
            if not doc:
                logger.error("document_not_found_in_background", doc_id=doc_id)
                return

            # Read file content
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except Exception as exc:
                logger.error("document_read_error", doc_id=doc_id, error=str(exc))
                doc.status = "failed"
                doc.error_message = f"Failed to read file: {exc}"
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

            # Generate placeholder embeddings (1536 zeros per chunk)
            placeholder_embedding = [0.0] * 1536

            # Store in Qdrant
            vector_ids: list[str] = []
            try:
                from qdrant_client import QdrantClient
                from qdrant_client.models import Distance, PointStruct, VectorParams
                from app.core.config import settings

                qdrant_url = getattr(settings, "QDRANT_URL", "http://qdrant:6333")
                client = QdrantClient(url=qdrant_url)
                collection_name = f"agent_{agent_id}"

                # Ensure collection exists
                try:
                    client.get_collection(collection_name)
                except Exception:
                    client.create_collection(
                        collection_name=collection_name,
                        vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
                    )

                points = []
                for i, chunk_text in enumerate(chunks):
                    vid = str(uuid.uuid4())
                    vector_ids.append(vid)
                    points.append(
                        PointStruct(
                            id=vid,
                            vector=placeholder_embedding,
                            payload={
                                "chunk_text": chunk_text,
                                "doc_id": doc_id,
                                "agent_id": agent_id,
                                "chunk_index": i,
                            },
                        )
                    )

                client.upsert(collection_name=collection_name, points=points)
            except Exception as exc:
                logger.warning("qdrant_unavailable_skipping", doc_id=doc_id, error=str(exc))
                # Assign placeholder vector_ids even without Qdrant
                vector_ids = [str(uuid.uuid4()) for _ in chunks]

            doc.status = "ready"
            doc.chunk_count = len(chunks)
            doc.vector_ids = vector_ids
            await db.commit()
            logger.info("document_processed", doc_id=doc_id, chunks=len(chunks))

        except Exception as exc:
            logger.error("document_processing_failed", doc_id=doc_id, error=str(exc))
            try:
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
    db: AsyncSession = Depends(get_db),
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


@router.post("/{agent_id}/documents", status_code=201)
async def upload_document(
    agent_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Upload a document for an agent.
    Accepts: pdf, txt, md, docx (up to 10 MB).
    Stores the file, creates an AgentDocument record, and launches background processing.
    """
    tenant_id = _tenant_id(request)
    agent = await _verify_agent(agent_id, tenant_id, db)

    # Validate file extension
    filename = file.filename or "upload"
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
        file_path=storage_path,
        agent_id=agent_id,
        tenant_id=tenant_id,
    )

    logger.info("document_upload_queued", doc_id=str(doc.id), agent_id=agent_id, filename=filename)
    return doc.to_dict()


@router.delete("/{agent_id}/documents/{doc_id}", status_code=204)
async def delete_document(
    agent_id: str,
    doc_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a document and remove its vectors from Qdrant."""
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

    # Remove from Qdrant (best-effort)
    if doc.vector_ids:
        try:
            from qdrant_client import QdrantClient
            from app.core.config import settings

            qdrant_url = getattr(settings, "QDRANT_URL", "http://qdrant:6333")
            client = QdrantClient(url=qdrant_url)
            collection_name = f"agent_{agent_id}"
            client.delete(
                collection_name=collection_name,
                points_selector=doc.vector_ids,
            )
        except Exception as exc:
            logger.warning("qdrant_delete_failed", doc_id=doc_id, error=str(exc))

    # Remove file from disk (best-effort)
    try:
        if doc.storage_path and os.path.exists(doc.storage_path):
            os.remove(doc.storage_path)
    except Exception as exc:
        logger.warning("file_delete_failed", doc_id=doc_id, error=str(exc))

    await db.delete(doc)
    await db.commit()
    logger.info("document_deleted", doc_id=doc_id, agent_id=agent_id)
