from __future__ import annotations

import ipaddress
import secrets
import urllib.parse
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.core.security import get_current_tenant, get_tenant_db
from app.models.user import Webhook
from app.schemas.auth import (
    WebhookCreatedResponse,
    WebhookCreateRequest,
    WebhookResponse,
    WebhookUpdateRequest,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks")

# ---------------------------------------------------------------------------
# SSRF guard (Critical fix)
# ---------------------------------------------------------------------------

_PRIVATE_PREFIXES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),  # Carrier-grade NAT
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]
_MAX_EVENTS = 20  # prevent unbounded event list


def _validate_webhook_url(url: str) -> None:
    """
    Reject URLs that target localhost, private/internal IPs, or use non-HTTPS
    schemes. Prevents SSRF via webhook registration.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid webhook URL.")

    if parsed.scheme != "https":
        raise HTTPException(status_code=422, detail="Webhook URL must use HTTPS.")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise HTTPException(status_code=422, detail="Webhook URL must include a hostname.")

    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        raise HTTPException(status_code=422, detail="Webhook URL must not target localhost.")

    # Reject private / link-local / loopback IP ranges
    try:
        ip = ipaddress.ip_address(hostname)
        for net in _PRIVATE_PREFIXES:
            if ip in net:
                raise HTTPException(
                    status_code=422,
                    detail="Webhook URL must not target a private or reserved IP address.",
                )
    except ValueError:
        pass  # hostname is a domain name — allowed


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return tenant_id


@router.post("", response_model=WebhookCreatedResponse, status_code=201)
async def create_webhook(
    body: WebhookCreateRequest,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """
    Create a new webhook endpoint.
    The signing secret is returned ONCE in this response and never again.
    Store it securely — it cannot be recovered after creation.
    """
    # Auth handled by get_tenant_db

    # SSRF guard
    _validate_webhook_url(body.url)

    # Enforce event list size cap
    if len(body.events) > _MAX_EVENTS:
        raise HTTPException(
            status_code=422,
            detail=f"Too many events. Maximum {_MAX_EVENTS} event types per webhook.",
        )

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
    # Return secret ONE TIME only — mirrors APIKeyCreatedResponse pattern
    return WebhookCreatedResponse(
        id=str(webhook.id),
        tenant_id=str(webhook.tenant_id),
        url=webhook.url,
        events=webhook.events,
        is_active=webhook.is_active,
        created_at=webhook.created_at.isoformat(),
        secret=secret,
    )


@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """List all webhooks for the current tenant."""
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
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Update a webhook."""
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
        _validate_webhook_url(body.url)  # SSRF guard on update too
        webhook.url = body.url
    if body.events is not None:
        if len(body.events) > _MAX_EVENTS:
            raise HTTPException(
                status_code=422,
                detail=f"Too many events. Maximum {_MAX_EVENTS} event types per webhook.",
            )
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
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Delete a webhook."""
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


# Redundant stripe_webhook removed — use /api/v1/billing/webhook instead.


async def _send_welcome_email_async(email: str, full_name: str) -> None:
    """Send a welcome email after payment activation."""
    from app.core.config import settings
    from app.services.email_service import send_email

    html_body = f"""
    <html><body>
    <h1>Welcome to AscenAI, {full_name}!</h1>
    <p>Your account is now active. Get started at <a href="{settings.FRONTEND_URL}">{settings.FRONTEND_URL}</a></p>
    </body></html>
    """
    await send_email(email, "Welcome to AscenAI!", html_body)


