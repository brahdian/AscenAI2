from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.mcp import (
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeDocumentCreate,
    KnowledgeDocumentResponse,
    MCPContextRequest,
    MCPContextResult,
)
from app.services.context_provider import ContextProvider
from app.api.v1.internal_auth import verify_internal_token

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/context", dependencies=[Depends(verify_internal_token)])


def _tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


async def _tenant_db(
    tenant_id: str = Depends(_tenant_id),
):
    async for session in get_db(tenant_id):
        yield session


def _get_provider(request: Request, db: AsyncSession) -> ContextProvider:
    redis = getattr(request.app.state, "redis", None)
    return ContextProvider(redis_client=redis, db=db)


@router.post("/retrieve", response_model=MCPContextResult)
async def retrieve_context(
    body: MCPContextRequest,
    request: Request,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(_tenant_db),
):
    """Retrieve relevant context for a query."""
    body_dict = body.model_dump()
    body_dict["tenant_id"] = tenant_id
    body = MCPContextRequest(**body_dict)

    provider = _get_provider(request, db)
    return await provider.retrieve_context(body)


@router.post("/knowledge-bases", response_model=KnowledgeBaseResponse, status_code=201)
async def create_knowledge_base(
    body: KnowledgeBaseCreate,
    request: Request,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(_tenant_db),
):
    """Create a new knowledge base."""
    provider = _get_provider(request, db)
    kb = await provider.create_knowledge_base(tenant_id, body)
    await db.commit()
    await db.refresh(kb)
    return kb


@router.get("/knowledge-bases", response_model=list[KnowledgeBaseResponse])
async def list_knowledge_bases(
    request: Request,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(_tenant_db),
):
    """List knowledge bases for the tenant."""
    provider = _get_provider(request, db)
    return await provider.list_knowledge_bases(tenant_id)


@router.post(
    "/knowledge-bases/{kb_id}/documents",
    response_model=KnowledgeDocumentResponse,
    status_code=201,
)
async def add_document(
    kb_id: str,
    body: KnowledgeDocumentCreate,
    request: Request,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(_tenant_db),
):
    """Add a document to a knowledge base."""
    body_dict = body.model_dump()
    body_dict["kb_id"] = kb_id
    body = KnowledgeDocumentCreate(**body_dict)

    provider = _get_provider(request, db)
    doc = await provider.add_document(tenant_id, body)
    await db.commit()
    await db.refresh(doc)
    return doc


@router.delete("/knowledge-bases/{kb_id}/documents/{doc_id}", status_code=204)
async def delete_document(
    kb_id: str,
    doc_id: str,
    request: Request,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(_tenant_db),
):
    """Delete a document from a knowledge base."""
    provider = _get_provider(request, db)
    deleted = await provider.delete_document(tenant_id, kb_id, doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found.")
    await db.commit()

@router.post("/knowledge-bases/{kb_id}/documents/cleanup", status_code=200)
async def cleanup_documents(
    kb_id: str,
    metadata_key: str,
    metadata_value: str,
    request: Request,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(_tenant_db),
):
    """Delete all documents matching metadata key/value."""
    # Phase 8 — Gap 3: Enforce metadata_key allowlist for security
    ALLOWED_KEYS = {"document_id", "agent_id", "source", "is_semantic_duplicate"}
    if metadata_key not in ALLOWED_KEYS:
        raise HTTPException(
            status_code=422, 
            detail=f"Invalid metadata_key '{metadata_key}'. Allowed: {', '.join(sorted(ALLOWED_KEYS))}"
        )

    provider = _get_provider(request, db)
    count = await provider.delete_documents_by_metadata(tenant_id, kb_id, metadata_key, metadata_value)
    await db.commit()
    return {"deleted_count": count}

@router.delete("/knowledge-bases/bulk-wipe", status_code=200)
async def bulk_wipe_knowledge(
    request: Request,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(_tenant_db),
):
    """Wipe ALL knowledge bases and documents for the current tenant. Permanent erasure."""
    provider = _get_provider(request, db)
    doc_count = await provider.delete_all_tenant_knowledge(tenant_id)
    await db.commit()
    return {"success": True, "deleted_documents": doc_count}
