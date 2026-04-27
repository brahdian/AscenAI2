"""SMS Workflow Engine — async post-disconnect automation.

Sends SMS messages at key points in the booking lifecycle:
  1. Payment link (immediately after slot is held)
  2. Payment reminder (when close to expiry, no payment yet)
  3. Booking confirmation (after payment + CRM confirmation)
  4. Slot lost notification (payment received but slot taken)
  5. Reservation expired (TTL elapsed without payment)

Design
------
* All methods are fire-and-forget from the caller's perspective: SMS failures
  are logged but NEVER crash the booking flow.  A missed SMS is bad; a lost
  booking confirmation is worse.
* Each send is recorded as a BookingEvent for auditability.
* `customer_phone` must be in E.164 format (validated at booking creation).
* The engine is stateless — it receives a BookingWorkflow ORM object and
  the tenant_config dict, looks up Twilio credentials, and calls handle_send_sms.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import BookingWorkflow
from app.services.booking_state_machine import record_event
from app.tools.builtin.sms import handle_send_sms

logger = structlog.get_logger(__name__)


from shared.dates import utcnow as _utcnow


class SMSWorkflowEngine:
    """Sends templated SMS messages for booking workflow events."""

    def __init__(self, db: AsyncSession, tenant_config: dict) -> None:
        self._db = db
        self._tenant_config = tenant_config
        # Base URL for rebooking links — configurable via tenant_config or env
        import os
        self._base_url = (
            tenant_config.get("app_base_url")
            or os.getenv("APP_BASE_URL", "https://app.ascenai.io")
        ).rstrip("/")

    # ------------------------------------------------------------------
    # Public send methods
    # ------------------------------------------------------------------

    async def send_payment_link(self, wf: BookingWorkflow) -> None:
        """Sent immediately after a slot is held."""
        minutes_left = max(1, int((wf.expiry_time - _utcnow()).total_seconds() / 60))
        message = (
            f"Hi {wf.customer_name}, your {wf.slot_service} appointment slot on "
            f"{wf.slot_date} at {wf.slot_time} is reserved for {minutes_left} minutes. "
            f"Complete payment to confirm: {wf.payment_link_url}"
        )
        await self._send(wf, message, event_type="PAYMENT_LINK_SENT",
                         idempotency_key=f"sms:payment_link:{wf.id}")

    async def send_payment_reminder(self, wf: BookingWorkflow) -> None:
        """Sent when the slot is approaching expiry and no payment has arrived."""
        minutes_left = max(0, int((wf.expiry_time - _utcnow()).total_seconds() / 60))
        message = (
            f"Reminder: your {wf.slot_service} slot expires in {minutes_left} minute(s). "
            f"Pay now to keep it: {wf.payment_link_url}"
        )
        await self._send(wf, message, event_type="PAYMENT_REMINDER_SENT",
                         idempotency_key=f"sms:reminder:{wf.id}")
        # Record that a reminder was sent so the worker doesn't send another
        wf.sms_reminder_sent_at = _utcnow()

    async def send_booking_confirmation(
        self, wf: BookingWorkflow, confirmation_code: str
    ) -> None:
        """Sent after payment + CRM confirmation."""
        message = (
            f"Confirmed! Your {wf.slot_service} appointment is booked for "
            f"{wf.slot_date} at {wf.slot_time}. "
            f"Confirmation code: {confirmation_code}. "
            f"Reply CANCEL to cancel."
        )
        await self._send(wf, message, event_type="BOOKING_CONFIRMED_SMS",
                         idempotency_key=f"sms:confirmed:{wf.id}")

    async def send_slot_lost_notification(self, wf: BookingWorkflow) -> None:
        """Sent when payment succeeded but the slot was taken by someone else."""
        rebooking_url = f"{self._base_url}/rebook/{wf.id}"
        message = (
            f"Sorry {wf.customer_name} — your payment was received but your "
            f"{wf.slot_service} slot is no longer available. "
            f"Choose a new time: {rebooking_url}"
        )
        await self._send(wf, message, event_type="SLOT_LOST_NOTIFIED",
                         idempotency_key=f"sms:slot_lost:{wf.id}")

    async def send_payment_expired_notice(self, wf: BookingWorkflow) -> None:
        """Sent when the TTL expires without a payment."""
        rebooking_url = f"{self._base_url}/rebook/{wf.id}"
        message = (
            f"Your {wf.slot_service} reservation has expired. "
            f"Start over to book a new slot: {rebooking_url}"
        )
        await self._send(wf, message, event_type="RESERVATION_EXPIRED_SMS",
                         idempotency_key=f"sms:expired:{wf.id}")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _send(
        self,
        wf: BookingWorkflow,
        message: str,
        event_type: str,
        idempotency_key: Optional[str] = None,
    ) -> None:
        """Send an SMS and record the result as a BookingEvent.

        Never raises — failures are logged and stored as SMS_FAILED events.
        The booking flow must continue regardless of SMS delivery outcome.
        """
        if not wf.customer_phone:
            logger.warning(
                "sms_skipped_no_phone",
                workflow_id=str(wf.id),
                event_type=event_type,
            )
            return

        try:
            masked_to = f"{wf.customer_phone[:4]}...{wf.customer_phone[-2:]}" if wf.customer_phone and len(wf.customer_phone) > 6 else "***"
            
            result = await handle_send_sms(
                {"to": wf.customer_phone, "message": message},
                self._tenant_config,
            )

            if result.get("success"):
                logger.info(
                    "sms_sent",
                    workflow_id=str(wf.id),
                    to=masked_to,
                    event_type=event_type,
                    sid=result.get("sid"),
                )
                await record_event(
                    self._db,
                    wf.id,
                    event_type=event_type,
                    actor="sms_engine",
                    idempotency_key=idempotency_key,
                    payload={"sid": result.get("sid"), "to": wf.customer_phone},
                )
            else:
                logger.error(
                    "sms_send_failed",
                    workflow_id=str(wf.id),
                    to=masked_to,
                    event_type=event_type,
                    error=result.get("error"),
                )
                await record_event(
                    self._db,
                    wf.id,
                    event_type="SMS_FAILED",
                    actor="sms_engine",
                    payload={
                        "intended_event": event_type,
                        "error": result.get("error"),
                        "to": wf.customer_phone,
                    },
                )

        except Exception as exc:
            logger.exception(
                "sms_engine_exception",
                workflow_id=str(wf.id),
                to=masked_to,
                event_type=event_type,
                error=str(exc),
            )
            # Do not re-raise — SMS failure must not abort the booking flow
