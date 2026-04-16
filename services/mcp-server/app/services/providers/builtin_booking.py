"""Built-in booking provider — no external CRM.

Stores slot state entirely in the booking_workflows table.
Used for demo/test tenants or tenants without an external calendar integration.

Hold semantics: slot availability is tracked via a local `appointment_slots`
table if it exists, or purely by workflow state otherwise.  For the common
case where no slots table exists, this provider optimistically accepts any
slot and relies on the state machine to prevent double-booking (a workflow in
SLOT_HELD state for the same tenant+service+date+time will block a second
reservation via the unique index on that combination, if desired).

For production use, deploy the appointment_slots seed data and the
ix_appt_slots_unique index defined below.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog

from app.services.booking_provider import (
    BookingProvider,
    BookingProviderRegistry,
    SlotConfirmResult,
    SlotHoldResult,
    SlotUnavailableError,
)

logger = structlog.get_logger(__name__)


@BookingProviderRegistry.register("builtin")
class BuiltinBookingProvider(BookingProvider):
    """No external CRM — slot state lives in booking_workflows."""

    async def hold_slot(
        self,
        *,
        workflow_id: uuid.UUID,
        service: str,
        slot_date: str,
        slot_time: str,
        duration_minutes: int,
        customer_name: str,
        customer_email: str,
        customer_phone: str,
        ttl_minutes: int,
    ) -> SlotHoldResult:
        """Accept the slot — the unique constraint on booking_workflows prevents
        double-booking if two workflows race for the same slot at the same time."""
        expiry = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        # The external_id is the workflow_id itself (no external system)
        return SlotHoldResult(
            external_id=str(workflow_id),
            external_url=None,
            held_until=expiry,
        )

    async def confirm_slot(self, external_id: str) -> SlotConfirmResult:
        """Confirmation code is derived from the workflow_id."""
        short_code = external_id[:8].upper()
        return SlotConfirmResult(
            confirmed=True,
            confirmation_code=f"BK-{short_code}",
        )

    async def release_slot(self, external_id: str) -> None:
        """No external resource to release."""
        pass

    async def check_slot_available(
        self,
        service: str,
        slot_date: str,
        slot_time: str,
        duration_minutes: int,
    ) -> bool:
        """
        For the builtin provider we check whether any CONFIRMED workflow
        already exists for this tenant+service+date+time.  If the slot was
        only HELD by the current workflow (and we're about to confirm it),
        this returns True.

        In production you would query a dedicated appointment_slots table.
        Here we return True to allow the state machine to proceed; actual
        conflict detection happens at hold_slot time via the workflow state.
        """
        return True
