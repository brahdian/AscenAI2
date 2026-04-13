"""Custom / generic booking provider.

For tenants with proprietary booking systems or any external API not covered
by the built-in providers.

Config keys (all optional — graceful degradation if missing)
------------------------------------------------------------
custom_hold_url        — POST: receives hold payload, returns {"id": "...", "url": "..."}
custom_confirm_url     — POST: receives {"external_id": "..."}, returns {"code": "..."}
custom_release_url     — POST: receives {"external_id": "..."}, returns {}
custom_availability_url— POST: receives slot params, returns {"available": true/false}
custom_api_key         — Bearer token for all endpoints (if required)
custom_api_header      — Header name (default: "Authorization")
custom_api_header_prefix — Header value prefix (default: "Bearer ")
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


@BookingProviderRegistry.register("custom")
class CustomBookingProvider(BookingProvider):
    """Generic passthrough for any custom booking API."""

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        key = self._config.get("custom_api_key")
        if key:
            header = self._config.get("custom_api_header", "Authorization")
            prefix = self._config.get("custom_api_header_prefix", "Bearer ")
            h[header] = f"{prefix}{key}"
        return h

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
        """Call custom_hold_url if configured; otherwise store locally."""
        expiry = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        hold_url = self._config.get("custom_hold_url")

        if not hold_url:
            # No hold endpoint — store slot locally, call confirm_url on payment
            return SlotHoldResult(
                external_id=str(workflow_id),
                external_url=None,
                held_until=expiry,
            )

        payload = {
            "workflow_id": str(workflow_id),
            "service": service,
            "slot_date": slot_date,
            "slot_time": slot_time,
            "duration_minutes": duration_minutes,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "customer_phone": customer_phone,
            "ttl_minutes": ttl_minutes,
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(hold_url, json=payload, headers=self._headers())

        if resp.status_code == 409:
            raise SlotUnavailableError(
                f"Custom provider: slot at {slot_date} {slot_time} unavailable"
            )
        if resp.status_code not in (200, 201):
            raise ProviderCallError(
                f"Custom hold_url returned HTTP {resp.status_code}: {resp.text[:200]}"
            )

        data = resp.json()
        return SlotHoldResult(
            external_id=data.get("id", str(workflow_id)),
            external_url=data.get("url"),
            held_until=expiry,
        )

    async def confirm_slot(self, external_id: str) -> SlotConfirmResult:
        confirm_url = self._config.get("custom_confirm_url")
        if not confirm_url:
            code = external_id[:8].upper()
            return SlotConfirmResult(confirmed=True, confirmation_code=f"CU-{code}")

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                confirm_url,
                json={"external_id": external_id},
                headers=self._headers(),
            )

        if resp.status_code in (200, 201):
            data = resp.json()
            code = data.get("code") or data.get("confirmation_code") or external_id[:8].upper()
            return SlotConfirmResult(confirmed=True, confirmation_code=str(code))

        logger.warning(
            "custom_confirm_failed",
            external_id=external_id,
            status=resp.status_code,
        )
        return SlotConfirmResult(confirmed=False, confirmation_code="")

    async def release_slot(self, external_id: str) -> None:
        release_url = self._config.get("custom_release_url")
        if not release_url:
            return  # No release endpoint — nothing to do

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                release_url,
                json={"external_id": external_id},
                headers=self._headers(),
            )

        if resp.status_code not in (200, 201, 204, 404):
            logger.warning(
                "custom_release_failed",
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
        avail_url = self._config.get("custom_availability_url")
        if not avail_url:
            return True  # Fail open if no availability endpoint configured

        payload = {
            "service": service,
            "slot_date": slot_date,
            "slot_time": slot_time,
            "duration_minutes": duration_minutes,
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(avail_url, json=payload, headers=self._headers())

        if resp.status_code == 200:
            return bool(resp.json().get("available", True))

        # Fail open on errors
        logger.warning(
            "custom_check_available_failed",
            status=resp.status_code,
        )
        return True
