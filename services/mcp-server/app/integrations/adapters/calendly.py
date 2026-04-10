"""Calendly adapter — Calendly API v2 via httpx.

Config keys (stored encrypted in tool_metadata):
  api_token        — Personal Access Token
  event_type_uuid  — UUID of the event type to book / check

Supported canonical actions:
  CheckCalendarAvailability — List available time slots
  ScheduleMeeting           — Create an invitee (book a slot)
"""
from __future__ import annotations

import time

import httpx
import structlog

from app.integrations.base import ACTION_REGISTRY, BaseAdapter
from app.integrations.errors import (
    IntegrationAuthError,
    IntegrationConfigError,
    IntegrationError,
    IntegrationException,
    ErrorCode,
    ProviderError,
    VerifyResult,
)

logger = structlog.get_logger(__name__)

_BASE = "https://api.calendly.com"


class CalendlyAdapter(BaseAdapter):
    provider_name = "calendly"
    supported_actions = {"CheckCalendarAvailability", "ScheduleMeeting"}

    def _headers(self, config: dict) -> dict[str, str]:
        token = config.get("api_token") or config.get("value")
        if not token:
            raise IntegrationConfigError.missing(self.provider_name, "api_token")
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _event_type_uri(self, config: dict) -> str:
        uuid = config.get("event_type_uuid")
        if not uuid:
            raise IntegrationConfigError.missing(self.provider_name, "event_type_uuid")
        return f"{_BASE}/event_types/{uuid}"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict, config: dict) -> dict:
        if action == "CheckCalendarAvailability":
            return await self._check_availability(params, config)
        if action == "ScheduleMeeting":
            return await self._schedule_meeting(params, config)
        self._unsupported(action)

    async def verify_config(self, config: dict) -> VerifyResult:
        """Get the current user to confirm the token is valid."""
        start = time.monotonic()
        try:
            headers = self._headers(config)
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{_BASE}/users/me", headers=headers)
            if resp.status_code == 401:
                return VerifyResult(ok=False, latency_ms=self._timed_verify(start),
                                    error="Calendly token is invalid or expired.")
            if not resp.is_success:
                return VerifyResult(ok=False, latency_ms=self._timed_verify(start),
                                    error=f"Calendly API error {resp.status_code}")

            resource = resp.json().get("resource", {})
            details = {
                "name": resource.get("name", ""),
                "email": resource.get("email", ""),
                "slug": resource.get("slug", ""),
            }
            # Also verify the event_type_uuid if provided
            if config.get("event_type_uuid"):
                et_resp = None
                async with httpx.AsyncClient(timeout=10) as client:
                    et_resp = await client.get(self._event_type_uri(config), headers=headers)
                if et_resp and et_resp.is_success:
                    details["event_type"] = et_resp.json().get("resource", {}).get("name", "")
                elif et_resp:
                    details["event_type_warning"] = f"Event type not found ({et_resp.status_code})"

            return VerifyResult(ok=True, latency_ms=self._timed_verify(start), details=details)
        except IntegrationConfigError as exc:
            return VerifyResult(ok=False, latency_ms=self._timed_verify(start), error=str(exc))
        except Exception as exc:
            return VerifyResult(ok=False, latency_ms=self._timed_verify(start), error=str(exc))

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    async def _check_availability(self, params: dict, config: dict) -> dict:
        """CheckCalendarAvailability → Calendly event_type_available_times."""
        headers = self._headers(config)
        event_type_uri = self._event_type_uri(config)

        date = params["date"]
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_BASE}/event_type_available_times",
                headers=headers,
                params={
                    "event_type": event_type_uri,
                    "start_time": f"{date}T00:00:00.000000Z",
                    "end_time": f"{date}T23:59:59.000000Z",
                },
            )

        if resp.status_code == 401:
            raise IntegrationAuthError.from_provider(self.provider_name)
        if not resp.is_success:
            raise ProviderError.from_http(self.provider_name, resp.status_code, resp.text[:300])

        slots = [
            {"start": item["start_time"], "end": item.get("end_time", "")}
            for item in resp.json().get("collection", [])
        ]
        return self._tag({
            "available_slots": slots,
            "total_available": len(slots),
            "date": date,
        })

    async def _schedule_meeting(self, params: dict, config: dict) -> dict:
        """ScheduleMeeting → Calendly scheduled_events create."""
        headers = self._headers(config)
        event_type_uri = self._event_type_uri(config)

        body = {
            "event_type_uuid": config["event_type_uuid"],
            "start_time": params["start_datetime"],
            "invitee": {
                "name": params["attendee_name"],
                "email": params["attendee_email"],
            },
        }
        if params.get("notes"):
            body["questions_and_answers"] = [
                {"question": "Additional notes", "answer": params["notes"]}
            ]

        # Calendly's scheduling endpoint is a one-time scheduling link
        # We use the event_type available_times + invitee creation pattern
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_BASE}/scheduling_links",
                headers=headers,
                json={
                    "max_event_count": 1,
                    "owner": event_type_uri,
                    "owner_type": "EventType",
                },
            )

        if resp.status_code == 401:
            raise IntegrationAuthError.from_provider(self.provider_name)
        if not resp.is_success:
            data = resp.json()
            msg = (data.get("message") or data.get("title")
                   or f"Calendly error {resp.status_code}")
            raise IntegrationException(IntegrationError(
                code=ErrorCode.PROVIDER_ERROR,
                message=msg,
                provider=self.provider_name,
                http_status=resp.status_code,
                retryable=resp.status_code >= 500,
            ))

        resource = resp.json().get("resource", {})
        return self._tag({
            "meeting_id": resource.get("booking_url", "").rsplit("/", 1)[-1],
            "status": "scheduled",
            "start_datetime": params["start_datetime"],
            "end_datetime": "",
            "join_url": resource.get("booking_url", ""),
        })


# Self-register
ACTION_REGISTRY.register(CalendlyAdapter())
