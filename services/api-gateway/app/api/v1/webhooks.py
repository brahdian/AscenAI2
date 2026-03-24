from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import Webhook
from app.schemas.auth import WebhookCreateRequest, WebhookResponse, WebhookUpdateRequest

router = APIRouter(prefix="/webhooks")


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return tenant_id


@router.post("", response_model=WebhookResponse, status_code=201)
async def create_webhook(
    body: WebhookCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a new webhook endpoint."""
    tenant_id = _require_tenant(request)
    secret = "whsec_" + secrets.token_hex(32)
    webhook = Webhook(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant_id),
        url=body.url,
        events=body.events,
        secret=secret,
        is_active=True,
    )
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)
    return WebhookResponse(
        id=str(webhook.id),
        tenant_id=str(webhook.tenant_id),
        url=webhook.url,
        events=webhook.events,
        is_active=webhook.is_active,
        created_at=webhook.created_at.isoformat(),
    )


@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """List all webhooks for the current tenant."""
    tenant_id = _require_tenant(request)
    result = await db.execute(
        select(Webhook).where(Webhook.tenant_id == uuid.UUID(tenant_id))
    )
    webhooks = result.scalars().all()
    return [
        WebhookResponse(
            id=str(w.id),
            tenant_id=str(w.tenant_id),
            url=w.url,
            events=w.events,
            is_active=w.is_active,
            created_at=w.created_at.isoformat(),
        )
        for w in webhooks
    ]


@router.patch("/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: str,
    body: WebhookUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update a webhook."""
    tenant_id = _require_tenant(request)
    result = await db.execute(
        select(Webhook).where(
            Webhook.id == uuid.UUID(webhook_id),
            Webhook.tenant_id == uuid.UUID(tenant_id),
        )
    )
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found.")

    if body.url is not None:
        webhook.url = body.url
    if body.events is not None:
        webhook.events = body.events
    if body.is_active is not None:
        webhook.is_active = body.is_active

    await db.commit()
    await db.refresh(webhook)
    return WebhookResponse(
        id=str(webhook.id),
        tenant_id=str(webhook.tenant_id),
        url=webhook.url,
        events=webhook.events,
        is_active=webhook.is_active,
        created_at=webhook.created_at.isoformat(),
    )


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Delete a webhook."""
    tenant_id = _require_tenant(request)
    result = await db.execute(
        select(Webhook).where(
            Webhook.id == uuid.UUID(webhook_id),
            Webhook.tenant_id == uuid.UUID(tenant_id),
        )
    )
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found.")
    await db.delete(webhook)
    await db.commit()
