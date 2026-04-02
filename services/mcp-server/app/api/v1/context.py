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

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/context")


def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


def _get_provider(request: Request, db: AsyncSession) -> ContextProvider:
    redis = getattr(request.app.state, "redis", None)
    return ContextProvider(redis_client=redis, db=db)


@router.post("/retrieve", response_model=MCPContextResult)
async def retrieve_context(
    body: MCPContextRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve relevant context for a query."""
    tenant_id = _tenant_id(request)
    body_dict = body.model_dump()
    body_dict["tenant_id"] = tenant_id
    body = MCPContextRequest(**body_dict)

    provider = _get_provider(request, db)
    return await provider.retrieve_context(body)


@router.post("/knowledge-bases", response_model=KnowledgeBaseResponse, status_code=201)
async def create_knowledge_base(
    body: KnowledgeBaseCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a new knowledge base."""
    tenant_id = _tenant_id(request)
    provider = _get_provider(request, db)
    kb = await provider.create_knowledge_base(tenant_id, body)
    await db.commit()
    await db.refresh(kb)
    return kb


@router.get("/knowledge-bases", response_model=list[KnowledgeBaseResponse])
async def list_knowledge_bases(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """List knowledge bases for the tenant."""
    tenant_id = _tenant_id(request)
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
    db: AsyncSession = Depends(get_db),
):
    """Add a document to a knowledge base."""
    tenant_id = _tenant_id(request)
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
    db: AsyncSession = Depends(get_db),
):
    """Delete a document from a knowledge base."""
    tenant_id = _tenant_id(request)
    provider = _get_provider(request, db)
    deleted = await provider.delete_document(tenant_id, kb_id, doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found.")
    await db.commit()
