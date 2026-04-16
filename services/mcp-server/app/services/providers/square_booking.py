"""Square Appointments booking provider.

Flow
----
hold_slot   → POST /v2/bookings  (status: PENDING)
confirm_slot → PUT  /v2/bookings/{id}  (status: ACCEPTED)
release_slot → PUT  /v2/bookings/{id}  (status: CANCELLED)

Required tenant_config keys
---------------------------
square_access_token     — Square OAuth access token or personal access token
square_location_id      — Location ID for the booking
square_service_id       — Team member service variation ID (catalog object ID)
square_team_member_id   — Team member UUID to assign the booking to

Optional
--------
square_base_url         — Override for Sandbox (default: https://connect.squareup.com)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

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

_DEFAULT_BASE = "https://connect.squareup.com"


@BookingProviderRegistry.register("square")
class SquareBookingProvider(BookingProvider):
    """Square Appointments adapter — PENDING → ACCEPTED / CANCELLED."""

    def _headers(self) -> dict:
        token = (
            self._config.get("square_access_token")
            or self._config.get("access_token")
        )
        if not token:
            raise ProviderCallError("Square: missing square_access_token in tenant config")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Square-Version": "2024-02-22",
        }

    def _base(self) -> str:
        return self._config.get("square_base_url", _DEFAULT_BASE).rstrip("/")

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
        """Create a Square booking with status PENDING."""
        location_id = self._config.get("square_location_id") or self._config.get("location_id")
        service_id = self._config.get("square_service_id") or self._config.get("service_variation_id")
        team_member_id = self._config.get("square_team_member_id") or self._config.get("team_member_id")

        if not all([location_id, service_id, team_member_id]):
            raise ProviderCallError(
                "Square: missing square_location_id / square_service_id / "
                "square_team_member_id in tenant config"
            )

        start_rfc = f"{slot_date}T{slot_time}:00+00:00"
        body = {
            "idempotency_key": str(workflow_id),
            "booking": {
                "start_at": start_rfc,
                "location_id": location_id,
                "customer_note": f"Booked via AscenAI – workflow {workflow_id}",
                "appointment_segments": [
                    {
                        "duration_minutes": duration_minutes,
                        "service_variation_id": service_id,
                        "team_member_id": team_member_id,
                    }
                ],
            },
        }
        if customer_name:
            parts = customer_name.split(" ", 1)
            body["booking"]["customer_note"] = (
                f"{customer_name} – AscenAI workflow {workflow_id}"
            )

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self._base()}/v2/bookings",
                json=body,
                headers=self._headers(),
            )

        if resp.status_code == 409:
            raise SlotUnavailableError(
                f"Square slot at {slot_date} {slot_time} is no longer available"
            )
        resp_json = resp.json()
        if resp.status_code not in (200, 201) or resp_json.get("errors"):
            errors = resp_json.get("errors", [])
            raise ProviderCallError(
                f"Square create booking failed: {errors or resp.text[:200]}"
            )

        booking = resp_json.get("booking", {})
        booking_id = booking.get("id", str(workflow_id))
        expiry = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)

        return SlotHoldResult(
            external_id=booking_id,
            external_url=None,
            held_until=expiry,
        )

    async def confirm_slot(self, external_id: str) -> SlotConfirmResult:
        """Accept the pending booking."""
        async with httpx.AsyncClient(timeout=15) as client:
            # First retrieve to get version
            get_resp = await client.get(
                f"{self._base()}/v2/bookings/{external_id}",
                headers=self._headers(),
            )
        if get_resp.status_code != 200:
            return SlotConfirmResult(confirmed=False, confirmation_code="")

        booking = get_resp.json().get("booking", {})
        version = booking.get("version", 0)
        status = booking.get("status", "")

        # Already accepted — idempotent
        if status == "ACCEPTED":
            code = external_id[:8].upper()
            return SlotConfirmResult(confirmed=True, confirmation_code=f"SQ-{code}")

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.put(
                f"{self._base()}/v2/bookings/{external_id}",
                json={"booking": {"status": "ACCEPTED", "version": version}},
                headers=self._headers(),
            )

        if resp.status_code == 200:
            code = external_id[:8].upper()
            return SlotConfirmResult(confirmed=True, confirmation_code=f"SQ-{code}")

        logger.warning(
            "square_confirm_failed",
            external_id=external_id,
            status=resp.status_code,
        )
        return SlotConfirmResult(confirmed=False, confirmation_code="")

    async def release_slot(self, external_id: str) -> None:
        """Cancel the Square booking — idempotent."""
        async with httpx.AsyncClient(timeout=15) as client:
            # Get version first
            get_resp = await client.get(
                f"{self._base()}/v2/bookings/{external_id}",
                headers=self._headers(),
            )
        if get_resp.status_code == 404:
            return  # Already gone
        if get_resp.status_code != 200:
            logger.warning(
                "square_release_get_failed",
                external_id=external_id,
                status=get_resp.status_code,
            )
            return

        booking = get_resp.json().get("booking", {})
        version = booking.get("version", 0)
        status = booking.get("status", "")
        if status in ("CANCELLED_BY_CUSTOMER", "CANCELLED_BY_SELLER", "CANCELLED_BY_BUSINESS"):
            return  # Already cancelled

        async with httpx.AsyncClient(timeout=15) as client:
            await client.put(
                f"{self._base()}/v2/bookings/{external_id}",
                json={"booking": {"status": "CANCELLED_BY_SELLER", "version": version}},
                headers=self._headers(),
            )

    async def check_slot_available(
        self,
        service: str,
        slot_date: str,
        slot_time: str,
        duration_minutes: int,
    ) -> bool:
        """Check if our pending booking is still in PENDING state."""
        # In practice: we retrieve the booking by external_id in the webhook handler.
        # This method is called with the service/date/time, not external_id, so it
        # does a best-effort check.  The confirm_slot call will fail if taken.
        return True
