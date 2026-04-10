"""Twilio adapter — uses the official twilio-python SDK.

Config keys (stored encrypted in tool_metadata):
  account_sid  — Twilio Account SID (ACxxxx)
  auth_token   — Twilio Auth Token
  from_number  — Sender number in E.164 format (+1...)

Supported canonical actions:
  SendSMS — Send a text message via Twilio Messaging API
"""
from __future__ import annotations

import asyncio
import time

import structlog

from app.integrations.base import ACTION_REGISTRY, BaseAdapter
from app.integrations.errors import (
    IntegrationAuthError,
    IntegrationConfigError,
    IntegrationError,
    IntegrationException,
    IntegrationRateLimitError,
    ErrorCode,
    ProviderError,
    VerifyResult,
)

logger = structlog.get_logger(__name__)


class TwilioAdapter(BaseAdapter):
    provider_name = "twilio"
    supported_actions = {"SendSMS"}

    # ------------------------------------------------------------------
    # SDK client factory
    # ------------------------------------------------------------------

    def _get_client(self, config: dict):
        """Return a configured Twilio REST Client."""
        try:
            from twilio.rest import Client as TwilioClient
        except ImportError:
            raise ImportError("twilio package not installed. Run: pip install twilio")

        account_sid = config.get("account_sid") or config.get("username")
        auth_token = config.get("auth_token") or config.get("password")

        if not account_sid:
            raise IntegrationConfigError.missing(self.provider_name, "account_sid")
        if not auth_token:
            raise IntegrationConfigError.missing(self.provider_name, "auth_token")

        return TwilioClient(account_sid, auth_token)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict, config: dict) -> dict:
        if action == "SendSMS":
            return await self._send_sms(params, config)
        self._unsupported(action)

    async def verify_config(self, config: dict) -> VerifyResult:
        """Fetch the Twilio account resource to confirm credentials."""
        start = time.monotonic()
        try:
            client = self._get_client(config)
            # Twilio SDK is sync — run in thread executor
            account = await asyncio.get_event_loop().run_in_executor(
                None, lambda: client.api.accounts(config.get("account_sid") or config.get("username")).fetch()
            )
            return VerifyResult(
                ok=True,
                latency_ms=self._timed_verify(start),
                details={
                    "account_sid": account.sid,
                    "friendly_name": account.friendly_name,
                    "status": account.status,
                },
            )
        except IntegrationConfigError as exc:
            return VerifyResult(ok=False, latency_ms=self._timed_verify(start), error=str(exc))
        except Exception as exc:
            return VerifyResult(ok=False, latency_ms=self._timed_verify(start),
                                error=_twilio_error_message(exc))

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    async def _send_sms(self, params: dict, config: dict) -> dict:
        """Canonical SendSMS → Twilio Message create."""
        from twilio.base.exceptions import TwilioRestException

        client = self._get_client(config)
        from_number = (
            params.get("from_number")
            or config.get("from_number")
            or config.get("from")
        )
        if not from_number:
            raise IntegrationConfigError.missing(self.provider_name, "from_number")

        to = params["to"]
        body = params["body"][:1600]  # Twilio hard limit

        try:
            message = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.messages.create(to=to, from_=from_number, body=body),
            )
        except Exception as exc:
            raise _normalize_twilio_error(exc, self.provider_name)

        return self._tag({
            "message_id": message.sid,
            "status": message.status,         # queued | sent | delivered | failed
            "to": message.to,
        })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _twilio_error_message(exc: Exception) -> str:
    """Extract a clean error message from a Twilio exception."""
    # TwilioRestException has .msg and .code
    msg = getattr(exc, "msg", None) or str(exc)
    code = getattr(exc, "code", None)
    return f"{msg} (code {code})" if code else msg


def _normalize_twilio_error(exc: Exception, provider: str) -> Exception:
    """Convert a Twilio SDK exception to a normalized IntegrationException."""
    try:
        from twilio.base.exceptions import TwilioRestException
        if isinstance(exc, TwilioRestException):
            status = getattr(exc, "status", 500)
            code = getattr(exc, "code", None)
            msg = getattr(exc, "msg", str(exc))

            if status in (401, 403):
                return IntegrationAuthError.from_provider(provider, provider_code=str(code))
            if status == 429:
                return IntegrationRateLimitError.from_provider(provider)
            # Code 21211 = invalid To phone number
            if code in (21211, 21214, 21217):
                return IntegrationException(IntegrationError(
                    code=ErrorCode.INVALID_INPUT,
                    message=f"Invalid phone number: {msg}",
                    provider=provider,
                    provider_code=str(code),
                    retryable=False,
                ))
            return ProviderError.from_http(provider, status, msg)
    except ImportError:
        pass
    return ProviderError.from_http(provider, 500, str(exc))


# Self-register
ACTION_REGISTRY.register(TwilioAdapter())
