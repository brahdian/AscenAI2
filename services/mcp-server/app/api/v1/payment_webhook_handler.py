"""Idempotent payment event processor.

Called from the Stripe webhook route after signature verification and event
normalization.  This handler owns the critical section:

    payment received
        → re-verify slot still available with external CRM
        → confirm or trigger rebooking
        → send SMS

Idempotency guarantee
---------------------
The Stripe event ID is stored in booking_events with a unique idempotency_key.
If Stripe retries the same webhook (which happens routinely), the second call
hits the "already_processed" path and returns immediately without writing
anything to the database.

Race conditions handled
-----------------------
1. Two Stripe retries processed concurrently:
   SELECT … FOR UPDATE in booking_state_machine.transition() serializes them.
   The second caller finds the workflow already at PAYMENT_COMPLETED and the
   idempotency record already written → returns "already_processed".

2. Expiry worker fires at the same time as webhook arrives:
   Both race for the SELECT FOR UPDATE on the workflow row.
   If expiry worker wins → workflow is EXPIRED; webhook finds illegal transition
   EXPIRED → PAYMENT_COMPLETED and returns "invalid_state".
   We then send a slot-lost SMS because the user's money moved but the slot
   is gone.

3. Webhook arrives for an unknown workflow (wrong tenant, test event, etc.):
   Returns "no_workflow" without writing anything.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import BookingEvent, BookingState, BookingWorkflow
from app.services.booking_provider import BookingProviderRegistry
from app.services.booking_state_machine import (
    InvalidTransitionError,
    record_event,
    transition,
)
from app.services.sms_workflow_engine import SMSWorkflowEngine

logger = structlog.get_logger(__name__)


async def handle_payment_completed(
    db: AsyncSession,
    payment_intent_id: str,
    stripe_event_id: str,
    tenant_config_loader,  # async callable: (tenant_id: UUID) -> dict
    sms_engine_factory=None,  # optional: (db, config) -> SMSWorkflowEngine
) -> dict:
    """Process a Stripe payment_intent.succeeded event.

    Parameters
    ----------
    db                  : Async SQLAlchemy session (caller manages final commit).
    payment_intent_id   : Stripe PaymentIntent ID from the event payload.
    stripe_event_id     : Stripe event ID — used as idempotency key.
    tenant_config_loader: Async callable that returns tenant config dict.
    sms_engine_factory  : Optional factory for injecting a mock in tests.

    Returns
    -------
    dict with "status" key:
      "already_processed" — duplicate Stripe event, nothing written
      "no_workflow"       — no workflow found for this PaymentIntent
      "invalid_state"     — workflow in terminal state (expiry race)
      "processed"         — successfully confirmed or marked NEEDS_REBOOK
    """
    log = logger.bind(
        payment_intent_id=payment_intent_id,
        stripe_event_id=stripe_event_id,
    )

    # ── 1. Idempotency gate ────────────────────────────────────────────────
    idem_key = f"stripe:{stripe_event_id}"
    existing = await db.scalar(
        select(BookingEvent).where(BookingEvent.idempotency_key == idem_key)
    )
    if existing is not None:
        log.info("payment_webhook_already_processed")
        return {"status": "already_processed"}

    # ── 2. Find workflow by PaymentIntent ID ───────────────────────────────
    wf: Optional[BookingWorkflow] = await db.scalar(
        select(BookingWorkflow).where(
            BookingWorkflow.payment_intent_id == payment_intent_id,
        )
    )
    if wf is None:
        log.warning("payment_webhook_no_workflow")
        return {"status": "no_workflow"}

    log = log.bind(workflow_id=str(wf.id), workflow_state=wf.state.value)

    # ── 3. Guard: must be in a payable state ───────────────────────────────
    payable_states = {BookingState.PAYMENT_PENDING, BookingState.PAYMENT_COMPLETED}
    if wf.state not in payable_states:
        log.warning(
            "payment_webhook_invalid_state",
            state=wf.state.value,
        )
        # BLOCKER-4: User paid after the slot expired (classic race: expiry worker
        # fired between payment initiation and Stripe's webhook delivery).
        # The card has already been charged — we MUST refund automatically or this
        # becomes a chargeback and a consumer-protection violation.
        if wf.state == BookingState.EXPIRED:
            tenant_config = await tenant_config_loader(wf.tenant_id)
            sms = _make_sms_engine(db, tenant_config, sms_engine_factory)
            await sms.send_slot_lost_notification(wf)

            # Automatic Stripe refund for the captured payment
            if payment_intent_id:
                try:
                    import stripe as _stripe
                    from app.core.config import settings as _settings
                    _stripe.api_key = _settings.STRIPE_SECRET_KEY
                    import asyncio as _asyncio
                    refund = await _asyncio.to_thread(
                        _stripe.Refund.create,
                        payment_intent=payment_intent_id,
                        reason="duplicate",
                    )
                    log.info(
                        "stripe_refund_issued_expired_slot",
                        payment_intent_id=payment_intent_id,
                        refund_id=refund.id,
                        refund_status=refund.status,
                    )
                except Exception as refund_exc:
                    # Log loudly — ops must manually refund if this fails.
                    log.error(
                        "stripe_refund_failed_expired_slot_MANUAL_ACTION_REQUIRED",
                        payment_intent_id=payment_intent_id,
                        error=str(refund_exc),
                    )

            await db.commit()
        return {"status": "invalid_state", "current_state": wf.state.value}

    # ── 4. Transition to PAYMENT_COMPLETED ─────────────────────────────────
    try:
        await transition(
            db,
            wf.id,
            BookingState.PAYMENT_COMPLETED,
            actor="stripe_webhook",
            payload={"stripe_event_id": stripe_event_id},
        )
    except InvalidTransitionError:
        # Already PAYMENT_COMPLETED (webhook replay while confirming)
        pass

    # ── 5. Load tenant config for provider + SMS ───────────────────────────
    tenant_config = await tenant_config_loader(wf.tenant_id)
    sms = _make_sms_engine(db, tenant_config, sms_engine_factory)

    # ── 6. Re-verify slot with external CRM ───────────────────────────────
    #       THIS IS THE RACE CONDITION GUARD: a concurrent booking may have
    #       taken the slot between hold_slot and payment completion.
    provider = BookingProviderRegistry.get(wf.provider, tenant_config)
    slot_still_available = await provider.check_slot_available(
        wf.slot_service,
        str(wf.slot_date),
        wf.slot_time,
        wf.slot_duration_minutes,
    )

    if slot_still_available and wf.external_reservation_id:
        # ── 7a. Confirm booking with external CRM ─────────────────────────
        try:
            confirm = await provider.confirm_slot(wf.external_reservation_id)
        except Exception as exc:
            log.error("provider_confirm_failed", error=str(exc))
            confirm = None

        if confirm and confirm.confirmed:
            await transition(
                db,
                wf.id,
                BookingState.CONFIRMED,
                actor="payment_webhook",
                payload={"confirmation_code": confirm.confirmation_code},
            )
            await sms.send_booking_confirmation(wf, confirm.confirmation_code)
            booking_state = "CONFIRMED"
        else:
            # CRM confirm failed — treat as slot lost
            await _handle_slot_lost(db, wf, provider, sms, log)
            booking_state = "NEEDS_REBOOK"
    else:
        # ── 7b. Slot taken — trigger rebooking flow ───────────────────────
        await _handle_slot_lost(db, wf, provider, sms, log)
        booking_state = "NEEDS_REBOOK"

    # ── 8. Seal idempotency record ─────────────────────────────────────────
    await record_event(
        db,
        wf.id,
        event_type="STRIPE_EVENT_PROCESSED",
        actor="stripe_webhook",
        idempotency_key=idem_key,
        payload={"payment_intent_id": payment_intent_id, "booking_state": booking_state},
    )
    await db.commit()

    log.info("payment_webhook_processed", booking_state=booking_state)
    return {"status": "processed", "booking_state": booking_state}


async def _handle_slot_lost(
    db: AsyncSession,
    wf: BookingWorkflow,
    provider,
    sms: SMSWorkflowEngine,
    log,
) -> None:
    """Release the CRM hold, transition to NEEDS_REBOOK, and refund the user.

    The payment was captured but the slot is no longer available (either taken
    by a concurrent booking or CRM confirm failed).  We MUST issue a Stripe
    refund to avoid holding the user's money indefinitely while they wait for
    a rebook that may never complete.
    """
    if wf.external_reservation_id:
        try:
            await provider.release_slot(wf.external_reservation_id)
        except Exception as exc:
            log.error("provider_release_failed", error=str(exc))

    await transition(
        db,
        wf.id,
        BookingState.NEEDS_REBOOK,
        actor="payment_webhook",
        payload={"reason": "slot_unavailable_at_confirm_time"},
    )
    await sms.send_slot_lost_notification(wf)

    # Refund the captured payment — user's money should not be held while we
    # search for a replacement slot (HIGH-5 fix).
    if wf.payment_intent_id:
        try:
            import stripe as _stripe
            from app.core.config import settings as _settings
            import asyncio as _asyncio
            _stripe.api_key = _settings.STRIPE_SECRET_KEY
            refund = await _asyncio.to_thread(
                _stripe.Refund.create,
                payment_intent=wf.payment_intent_id,
                reason="duplicate",
            )
            log.info(
                "stripe_refund_issued_slot_lost",
                payment_intent_id=wf.payment_intent_id,
                refund_id=refund.id,
                refund_status=refund.status,
            )
        except Exception as refund_exc:
            # Log loudly — ops must manually refund if this fails.
            log.error(
                "stripe_refund_failed_slot_lost_MANUAL_ACTION_REQUIRED",
                payment_intent_id=wf.payment_intent_id,
                error=str(refund_exc),
            )


def _make_sms_engine(db, tenant_config, factory=None) -> SMSWorkflowEngine:
    if factory is not None:
        return factory(db, tenant_config)
    return SMSWorkflowEngine(db, tenant_config)
