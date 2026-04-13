"""Google Calendar booking provider.

Flow
----
hold_slot    → POST /calendar/v3/calendars/{calId}/events  (status: tentative)
confirm_slot → PATCH …/events/{eventId}  (status: confirmed)
release_slot → DELETE …/events/{eventId}

Required tenant_config keys
---------------------------
gcal_access_token    — OAuth 2.0 access token
gcal_calendar_id     — Calendar ID (default: "primary")

Optional
--------
gcal_refresh_token   — Refresh token for automatic renewal
gcal_client_id       — OAuth client ID (needed if refreshing)
gcal_client_secret   — OAuth client secret (needed if refreshing)
gcal_timezone        — IANA timezone for event (default: UTC)
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

_GCAL_BASE = "https://www.googleapis.com/calendar/v3"
_TOKEN_URL = "https://oauth2.googleapis.com/token"


@BookingProviderRegistry.register("google_calendar")
class GoogleCalendarBookingProvider(BookingProvider):
    """Google Calendar adapter — tentative events as holds."""

    async def _access_token(self) -> str:
        token = self._config.get("gcal_access_token") or self._config.get("access_token")
        if not token:
            raise ProviderCallError("GCal: missing gcal_access_token in tenant config")
        return token

    def _calendar_id(self) -> str:
        return (
            self._config.get("gcal_calendar_id")
            or self._config.get("calendar_id")
            or "primary"
        )

    def _tz(self) -> str:
        return self._config.get("gcal_timezone") or self._config.get("timezone") or "UTC"

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
        """Create a TENTATIVE Google Calendar event."""
        token = await self._access_token()
        cal_id = self._calendar_id()
        tz = self._tz()

        # Build RFC3339 start/end
        start_dt = datetime.strptime(f"{slot_date}T{slot_time}", "%Y-%m-%dT%H:%M")
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
        end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%S")

        attendees = []
        if customer_email:
            attendees.append({"email": customer_email, "displayName": customer_name})

        event_body = {
            "summary": f"{service} — {customer_name}",
            "description": (
                f"Booked via AscenAI\n"
                f"Workflow: {workflow_id}\n"
                f"Customer: {customer_name}"
            ),
            "start": {"dateTime": start_str, "timeZone": tz},
            "end": {"dateTime": end_str, "timeZone": tz},
            "status": "tentative",
            "attendees": attendees,
            "extendedProperties": {
                "private": {"ascenai_workflow_id": str(workflow_id)},
            },
        }

        url = f"{_GCAL_BASE}/calendars/{cal_id}/events"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url,
                json=event_body,
                headers={"Authorization": f"Bearer {token}"},
            )

        if resp.status_code == 409:
            raise SlotUnavailableError(
                f"GCal slot at {slot_date} {slot_time} conflicts with an existing event"
            )
        if resp.status_code not in (200, 201):
            raise ProviderCallError(
                f"GCal create event failed: HTTP {resp.status_code} — {resp.text[:200]}"
            )

        event = resp.json()
        event_id = event.get("id", str(workflow_id))
        html_link = event.get("htmlLink")
        expiry = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)

        return SlotHoldResult(
            external_id=event_id,
            external_url=html_link,
            held_until=expiry,
        )

    async def confirm_slot(self, external_id: str) -> SlotConfirmResult:
        """PATCH the event to status: confirmed."""
        token = await self._access_token()
        cal_id = self._calendar_id()
        url = f"{_GCAL_BASE}/calendars/{cal_id}/events/{external_id}"

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.patch(
                url,
                json={"status": "confirmed"},
                headers={"Authorization": f"Bearer {token}"},
            )

        if resp.status_code == 200:
            code = external_id[:8].upper()
            return SlotConfirmResult(confirmed=True, confirmation_code=f"GC-{code}")

        logger.warning(
            "gcal_confirm_failed",
            external_id=external_id,
            status=resp.status_code,
        )
        return SlotConfirmResult(confirmed=False, confirmation_code="")

    async def release_slot(self, external_id: str) -> None:
        """DELETE the tentative event — idempotent (404 = already gone)."""
        token = await self._access_token()
        cal_id = self._calendar_id()
        url = f"{_GCAL_BASE}/calendars/{cal_id}/events/{external_id}"

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.delete(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )

        if resp.status_code not in (200, 204, 404):
            logger.warning(
                "gcal_release_unexpected_status",
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
        """Use Google's freebusy API to check for conflicts."""
        token = await self._access_token()
        cal_id = self._calendar_id()
        tz = self._tz()

        start_dt = datetime.strptime(f"{slot_date}T{slot_time}", "%Y-%m-%dT%H:%M")
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        body = {
            "timeMin": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timeMax": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timeZone": tz,
            "items": [{"id": cal_id}],
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_GCAL_BASE}/freeBusy",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )

        if resp.status_code != 200:
            # Fail open: if we can't check, allow the confirm to proceed
            # (better to double-book than to refuse valid payments)
            logger.warning(
                "gcal_freebusy_failed",
                status=resp.status_code,
            )
            return True

        busy_slots = resp.json().get("calendars", {}).get(cal_id, {}).get("busy", [])
        return len(busy_slots) == 0
