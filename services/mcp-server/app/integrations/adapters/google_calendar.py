"""Google Calendar adapter — Google Calendar REST API via httpx.

Config keys (stored encrypted in tool_metadata):
  access_token  — OAuth 2.0 access token (short-lived)
  refresh_token — OAuth 2.0 refresh token (long-lived)
  client_id     — OAuth app client ID
  client_secret — OAuth app client secret
  calendar_id   — Target calendar ID (default: "primary")

Supported canonical actions:
  CheckCalendarAvailability — Free/busy query for a given date
  CreateCalendarEvent       — Create an event and invite attendees
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import structlog

from app.integrations.base import ACTION_REGISTRY, BaseAdapter
from app.integrations.errors import (
    IntegrationAuthError,
    IntegrationError,
    IntegrationException,
    ErrorCode,
    ProviderError,
    VerifyResult,
)

logger = structlog.get_logger(__name__)

_CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"
_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleCalendarAdapter(BaseAdapter):
    provider_name = "google_calendar"
    supported_actions = {"CheckCalendarAvailability", "CreateCalendarEvent"}

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    async def _auth_headers(self, config: dict) -> dict[str, str]:
        """Return Authorization headers, refreshing the token if needed."""
        token = config.get("access_token", "")
        if not token:
            from app.integrations.errors import IntegrationConfigError
            raise IntegrationConfigError.missing(self.provider_name, "access_token")
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def _refresh_token(self, config: dict) -> Optional[str]:
        """Attempt a token refresh. Returns new access_token or None."""
        refresh_token = config.get("refresh_token")
        client_id = config.get("client_id")
        client_secret = config.get("client_secret")
        if not all([refresh_token, client_id, client_secret]):
            return None
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(_TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            })
        if resp.is_success:
            return resp.json().get("access_token")
        return None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict, config: dict) -> dict:
        if action == "CheckCalendarAvailability":
            return await self._check_availability(params, config)
        if action == "CreateCalendarEvent":
            return await self._create_event(params, config)
        self._unsupported(action)

    async def verify_config(self, config: dict) -> VerifyResult:
        """Fetch calendar list to confirm the access token works."""
        start = time.monotonic()
        try:
            headers = await self._auth_headers(config)
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_CALENDAR_BASE}/users/me/calendarList",
                    headers=headers,
                    params={"maxResults": 1},
                )
            if resp.status_code == 401:
                # Try a token refresh
                new_token = await self._refresh_token(config)
                if new_token:
                    return VerifyResult(
                        ok=True,
                        latency_ms=self._timed_verify(start),
                        details={"note": "Token refreshed — update stored credentials.", "new_access_token": new_token},
                    )
                return VerifyResult(
                    ok=False,
                    latency_ms=self._timed_verify(start),
                    error="Google Calendar access token expired. Please reconnect your account.",
                )
            if not resp.is_success:
                return VerifyResult(ok=False, latency_ms=self._timed_verify(start),
                                    error=f"Google Calendar API error: {resp.status_code}")

            calendars = resp.json().get("items", [])
            primary = next((c for c in calendars if c.get("primary")), {})
            return VerifyResult(
                ok=True,
                latency_ms=self._timed_verify(start),
                details={
                    "email": primary.get("id", ""),
                    "summary": primary.get("summary", ""),
                    "calendar_count": len(calendars),
                },
            )
        except Exception as exc:
            return VerifyResult(ok=False, latency_ms=self._timed_verify(start), error=str(exc))

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    async def _check_availability(self, params: dict, config: dict) -> dict:
        """CheckCalendarAvailability → Google Calendar FreeBusy query."""
        headers = await self._auth_headers(config)
        calendar_id = config.get("calendar_id", "primary")

        date_str = params["date"]
        duration_min = int(params.get("duration_minutes", 60))
        tz_str = params.get("timezone", "UTC")

        try:
            day_start = datetime.fromisoformat(f"{date_str}T00:00:00+00:00")
            day_end = datetime.fromisoformat(f"{date_str}T23:59:59+00:00")
        except ValueError:
            raise IntegrationException(IntegrationError(
                code=ErrorCode.INVALID_INPUT,
                message=f"Invalid date format '{date_str}'. Use YYYY-MM-DD.",
                provider=self.provider_name,
                retryable=False,
            ))

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_CALENDAR_BASE}/freeBusy",
                headers=headers,
                json={
                    "timeMin": day_start.isoformat(),
                    "timeMax": day_end.isoformat(),
                    "items": [{"id": calendar_id}],
                },
            )

        if resp.status_code == 401:
            raise IntegrationAuthError.from_provider(self.provider_name)
        if not resp.is_success:
            raise ProviderError.from_http(self.provider_name, resp.status_code, resp.text[:300])

        busy_times = resp.json().get("calendars", {}).get(calendar_id, {}).get("busy", [])

        # Generate candidate slots by stepping through the day
        available_slots = []
        current = day_start
        step = timedelta(minutes=max(duration_min, 30))
        slot_duration = timedelta(minutes=duration_min)

        while current + slot_duration <= day_end:
            slot_end = current + slot_duration
            is_free = all(
                not (current < datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
                     and slot_end > datetime.fromisoformat(b["start"].replace("Z", "+00:00")))
                for b in busy_times
            )
            if is_free:
                available_slots.append({
                    "start": current.isoformat(),
                    "end": slot_end.isoformat(),
                })
            current += step

        return self._tag({
            "available_slots": available_slots,
            "total_available": len(available_slots),
            "date": date_str,
            "duration_minutes": duration_min,
        })

    async def _create_event(self, params: dict, config: dict) -> dict:
        """CreateCalendarEvent → Google Calendar events.insert."""
        headers = await self._auth_headers(config)
        calendar_id = config.get("calendar_id", "primary")

        event_body: dict[str, Any] = {
            "summary": params["title"],
            "start": {"dateTime": params["start_datetime"]},
            "end": {"dateTime": params["end_datetime"]},
        }
        if params.get("description"):
            event_body["description"] = params["description"]
        if params.get("location"):
            event_body["location"] = params["location"]

        emails = params.get("attendee_emails", [])
        if isinstance(emails, list) and emails:
            event_body["attendees"] = [{"email": e} for e in emails]

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_CALENDAR_BASE}/calendars/{calendar_id}/events",
                headers=headers,
                json=event_body,
            )

        if resp.status_code == 401:
            raise IntegrationAuthError.from_provider(self.provider_name)
        if not resp.is_success:
            raise ProviderError.from_http(self.provider_name, resp.status_code, resp.text[:300])

        event = resp.json()
        return self._tag({
            "event_id": event.get("id"),
            "status": event.get("status", "confirmed"),
            "calendar_link": event.get("htmlLink"),
            "start_datetime": (event.get("start") or {}).get("dateTime"),
            "end_datetime": (event.get("end") or {}).get("dateTime"),
        })


# Self-register
ACTION_REGISTRY.register(GoogleCalendarAdapter())
