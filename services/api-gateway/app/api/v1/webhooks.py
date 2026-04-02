from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import urllib.parse
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.core.database import get_db
from app.models.user import Webhook
from app.schemas.auth import WebhookCreateRequest, WebhookCreatedResponse, WebhookResponse, WebhookUpdateRequest

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
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new webhook endpoint.
    The signing secret is returned ONCE in this response and never again.
    Store it securely — it cannot be recovered after creation.
    """
    tenant_id = _require_tenant(request)

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


@router.post("/stripe", status_code=200)
async def stripe_webhook(request: Request, raw_body: bytes, db: AsyncSession = Depends(get_db)):
    """
    Handle Stripe webhook events.
    Stripe will send events like: customer.subscription.created, invoice.paid, etc.
    """
    body = raw_body

    logger.info("stripe_webhook_received",
                headers=dict(request.headers),
                content_length=len(body))

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("stripe_webhook_invalid_json")
        return {"error": "Invalid JSON"}

    event_type = event.get("type", "unknown")
    logger.info("stripe_webhook_event", event_type=event_type)

    from app.models.tenant import Tenant

    if event_type == "customer.subscription.created":
        subscription = event.get("data", {}).get("object", {})
        metadata = subscription.get("metadata", {})
        tenant_id = metadata.get("tenant_id")
        plan = metadata.get("plan")

        if tenant_id and plan:
            try:
                tenant_uuid = uuid.UUID(tenant_id)
                result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
                tenant = result.scalar_one_or_none()
                if tenant:
                    tenant.plan = plan
                    tenant.subscription_status = "active"
                    tenant.subscription_id = subscription.get("id")
                    from app.services.tenant_service import PLAN_LIMITS
                    tenant.plan_limits = PLAN_LIMITS.get(plan, PLAN_LIMITS.get("voice_growth"))
                    await db.commit()
                    logger.info("tenant_plan_updated", tenant_id=tenant_id, plan=plan, sub_id=tenant.subscription_id)
            except Exception as e:
                logger.error("stripe_subscription_created_error", error=str(e), tenant_id=tenant_id)

    elif event_type == "customer.subscription.updated":
        subscription = event.get("data", {}).get("object", {})
        metadata = subscription.get("metadata", {})
        tenant_id = metadata.get("tenant_id")
        plan = metadata.get("plan")
        status = subscription.get("status")

        if tenant_id:
            try:
                tenant_uuid = uuid.UUID(tenant_id)
                result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
                tenant = result.scalar_one_or_none()
                if tenant:
                    tenant.subscription_id = subscription.get("id")
                    if plan:
                        tenant.plan = plan
                        from app.services.tenant_service import PLAN_LIMITS
                        tenant.plan_limits = PLAN_LIMITS.get(plan, PLAN_LIMITS.get("voice_growth"))
                    if status:
                        tenant.subscription_status = status
                    await db.commit()
                    logger.info("tenant_subscription_updated", tenant_id=tenant_id, plan=plan, status=status)
            except Exception as e:
                logger.error("stripe_subscription_updated_error", error=str(e), tenant_id=tenant_id)

    elif event_type == "customer.subscription.deleted":
        subscription = event.get("data", {}).get("object", {})
        metadata = subscription.get("metadata", {})
        tenant_id = metadata.get("tenant_id")

        if tenant_id:
            try:
                tenant_uuid = uuid.UUID(tenant_id)
                result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
                tenant = result.scalar_one_or_none()
                if tenant:
                    tenant.plan = "starter"
                    tenant.subscription_status = "cancelled"
                    from app.services.tenant_service import PLAN_LIMITS
                    tenant.plan_limits = PLAN_LIMITS.get("starter")
                    await db.commit()
                    logger.info("tenant_subscription_cancelled", tenant_id=tenant_id)
            except Exception as e:
                logger.error("stripe_subscription_deleted_error", error=str(e), tenant_id=tenant_id)

    elif event_type == "invoice.paid":
        invoice = event.get("data", {}).get("object", {})
        customer_id = invoice.get("customer")
        subscription_id = invoice.get("subscription")

        if customer_id:
            try:
                result = await db.execute(select(Tenant).where(Tenant.stripe_customer_id == customer_id))
                tenant = result.scalar_one_or_none()
                if tenant:
                    tenant.subscription_status = "active"
                    if subscription_id:
                        tenant.subscription_id = subscription_id
                    await db.commit()
                    logger.info("tenant_invoice_paid", tenant_id=str(tenant.id), customer_id=customer_id)
            except Exception as e:
                logger.error("stripe_invoice_paid_error", error=str(e), customer_id=customer_id)

    elif event_type == "invoice.payment_failed":
        invoice = event.get("data", {}).get("object", {})
        customer_id = invoice.get("customer")

        if customer_id:
            try:
                result = await db.execute(select(Tenant).where(Tenant.stripe_customer_id == customer_id))
                tenant = result.scalar_one_or_none()
                if tenant:
                    tenant.subscription_status = "past_due"
                    await db.commit()
                    logger.info("tenant_invoice_payment_failed", tenant_id=str(tenant.id), customer_id=customer_id)
            except Exception as e:
                logger.error("stripe_invoice_payment_failed_error", error=str(e), customer_id=customer_id)

    return {"received": True}
