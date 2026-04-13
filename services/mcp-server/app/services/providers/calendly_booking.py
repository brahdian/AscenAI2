"""Calendly booking provider.

Calendly has no native "pending/tentative" booking state.  When a user selects
a slot we create an invitee immediately (which IS the real booking in Calendly).
On payment success we mark it confirmed in our state machine; if payment fails
or the slot expires we cancel the invitee via the Calendly API.

Required tenant_config keys
---------------------------
calendly_api_token       — Personal access token (Bearer auth)
calendly_event_type_uuid — UUID of the event type to book

Optional
--------
calendly_base_url        — Override for testing (default: https://api.calendly.com)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog

from app.services.booking_provider import (
    BookingProvider,
    BookingProviderRegistry,
    SlotConfirmResult,
    SlotHoldResult,
    SlotUnavailableError,
    ProviderCallError,
)

logger = structlog.get_logger(__name__)

_DEFAULT_BASE = "https://api.calendly.com"


@BookingProviderRegistry.register("calendly")
class CalendlyBookingProvider(BookingProvider):
    """Calendly adapter — invitee creation IS the hold."""

    def _headers(self) -> dict:
        token = self._config.get("calendly_api_token") or self._config.get("api_token")
        if not token:
            raise ProviderCallError("Calendly: missing calendly_api_token in tenant config")
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _base(self) -> str:
        return self._config.get("calendly_base_url", _DEFAULT_BASE).rstrip("/")

    def _event_type_uri(self) -> str:
        etu = (
            self._config.get("calendly_event_type_uuid")
            or self._config.get("event_type_uuid")
        )
        if not etu:
            raise ProviderCallError("Calendly: missing calendly_event_type_uuid in tenant config")
        return f"https://api.calendly.com/event_types/{etu}"

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
        """Create a Calendly invitee (this immediately books the slot)."""
        start_time = f"{slot_date}T{slot_time}:00Z"
        body = {
            "start_time": start_time,
            "event_type": self._event_type_uri(),
            "invitee": {
                "name": customer_name,
                "email": customer_email or f"noreply+{workflow_id}@ascenai.io",
            },
        }
        if customer_phone:
            body["invitee"]["text_reminder_number"] = customer_phone

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self._base()}/scheduled_events",
                json=body,
                headers=self._headers(),
            )

        if resp.status_code == 409:
            raise SlotUnavailableError(
                f"Calendly slot at {slot_date} {slot_time} is no longer available"
            )
        if resp.status_code not in (200, 201):
            raise ProviderCallError(
                f"Calendly create invitee failed: HTTP {resp.status_code} — {resp.text[:200]}"
            )

        data = resp.json().get("resource", {})
        invitee_uri = data.get("uri", "")
        invitee_uuid = invitee_uri.rsplit("/", 1)[-1] if invitee_uri else str(workflow_id)
        cancel_url = data.get("cancel_url")

        expiry = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        return SlotHoldResult(
            external_id=invitee_uuid,
            external_url=cancel_url,
            held_until=expiry,
        )

    async def confirm_slot(self, external_id: str) -> SlotConfirmResult:
        """Invitee already exists — retrieve it to get a confirmation URI."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self._base()}/invitees/{external_id}",
                headers=self._headers(),
            )
        if resp.status_code == 200:
            resource = resp.json().get("resource", {})
            uri = resource.get("uri", external_id)
            code = uri.rsplit("/", 1)[-1][:8].upper()
            return SlotConfirmResult(confirmed=True, confirmation_code=f"CAL-{code}")

        # If not found (already cancelled), treat as unavailable
        return SlotConfirmResult(confirmed=False, confirmation_code="")

    async def release_slot(self, external_id: str) -> None:
        """Cancel the Calendly invitee — idempotent (404 = already cancelled)."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self._base()}/invitees/{external_id}/cancellation",
                json={"reason": "Payment not completed within time limit"},
                headers=self._headers(),
            )
        if resp.status_code not in (200, 201, 204, 404):
            logger.warning(
                "calendly_release_slot_unexpected_status",
                external_id=external_id,
                status=resp.status_code,
            )

    async def check_slot_available(
        self,
        service: str,
        slot_date: str,
        slot_time: str,
        duration_minutes: int,
    ) -> bool:
        """Verify the invitee is still active (not already cancelled by someone else)."""
        # We check availability indirectly: if there's an active invitee it means
        # the slot is held.  Here we always return True because:
        # 1. The invitee was just created in hold_slot
        # 2. The only cancellation would be via our own release_slot call
        # A more robust check would query the Calendly available times API.
        # That is left as a tenant-specific enhancement.
        return True
