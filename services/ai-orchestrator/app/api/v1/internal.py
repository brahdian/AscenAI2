"""
Internal API endpoints — not exposed to end-users.

These endpoints are called service-to-service (e.g. api-gateway → ai-orchestrator)
and must not be reachable from the public internet.  The api-gateway is responsible
for authentication before forwarding requests here.
"""
from __future__ import annotations

import hashlib
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Message, Session as AgentSession

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/internal")


class ErasureRequest(BaseModel):
    tenant_id: str
    customer_identifier: str
    reason: str = ""


class ErasureResponse(BaseModel):
    sessions_anonymized: int
    messages_deleted: int


@router.post("/erasure", response_model=ErasureResponse)
async def erasure(
    body: ErasureRequest,
    db: AsyncSession = Depends(get_db),
) -> ErasureResponse:
    """
    GDPR / PIPEDA right-to-erasure handler.

    1. Deletes all Message rows that belong to sessions owned by
       (tenant_id, customer_identifier).
    2. Anonymizes those Session rows: sets customer_identifier to
       a SHA-256 hash prefix and clears metadata, preserving analytics counts.
    """
    try:
        tenant_uuid = uuid.UUID(body.tenant_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid tenant_id format.")

    session_result = await db.execute(
        select(AgentSession.id).where(
            AgentSession.tenant_id == tenant_uuid,
            AgentSession.customer_identifier == body.customer_identifier,
        )
    )
    session_ids = [row[0] for row in session_result.all()]

    messages_deleted = 0
    if session_ids:
        del_result = await db.execute(
            delete(Message).where(
                Message.session_id.in_(session_ids),
                Message.tenant_id == tenant_uuid,
            )
        )
        messages_deleted = del_result.rowcount or 0

        _id_hash = hashlib.sha256(body.customer_identifier.encode()).hexdigest()[:16]
        anon_identifier = f"[ERASED:{_id_hash}]"

        await db.execute(
            update(AgentSession)
            .where(AgentSession.id.in_(session_ids))
            .values(customer_identifier=anon_identifier, metadata_={})
        )

    await db.commit()

    sessions_anonymized = len(session_ids)
    logger.info(
        "erasure_completed",
        tenant_id=body.tenant_id,
        sessions_anonymized=sessions_anonymized,
        messages_deleted=messages_deleted,
        reason=body.reason,
    )
    return ErasureResponse(
        sessions_anonymized=sessions_anonymized,
        messages_deleted=messages_deleted,
    )
