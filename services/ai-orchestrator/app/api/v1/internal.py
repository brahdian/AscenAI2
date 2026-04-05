"""
Internal API endpoints — not exposed to end-users.

These endpoints are called service-to-service (e.g. api-gateway → ai-orchestrator)
and must not be reachable from the public internet.  Every request must present the
shared INTERNAL_API_KEY in the X-Internal-Key header; the InternalAuthMiddleware
already rejects requests that fail this check for non-public paths.

An explicit per-route guard (``_require_internal_key``) is added as defense-in-depth
so these endpoints remain protected even if middleware configuration changes.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.config import settings
from app.core.database import get_db
from app.models.agent import Message, Session as AgentSession

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/internal")


def _require_internal_key(x_internal_key: Optional[str] = Header(default=None)) -> None:
    """
    Defense-in-depth guard: verify the shared INTERNAL_API_KEY is present and correct.

    The InternalAuthMiddleware already rejects bad keys at the middleware layer.
    This per-route check ensures the endpoint remains protected even if the
    middleware is bypassed (e.g. direct uvicorn access without nginx/middleware).
    """
    expected = getattr(settings, "INTERNAL_API_KEY", "")
    if not expected:
        # If no key is configured we still accept the request but log a warning.
        # This preserves backwards-compatibility for deployments that haven't yet
        # configured INTERNAL_API_KEY (e.g. local dev).
        logger.warning(
            "internal_key_not_configured",
            detail="Set INTERNAL_API_KEY to protect internal endpoints.",
        )
        return
    if not x_internal_key or not hmac.compare_digest(
        x_internal_key.encode(), expected.encode()
    ):
        raise HTTPException(status_code=401, detail="Invalid internal credentials.")


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
    _: None = Depends(_require_internal_key),
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
