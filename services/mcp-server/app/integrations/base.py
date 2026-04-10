"""Base adapter interface and central action registry.

Every provider adapter inherits from BaseAdapter and registers itself with
ACTION_REGISTRY so that the tool executor can dispatch to the right
implementation at runtime without provider-specific conditionals.

Usage:
    from app.integrations.base import ACTION_REGISTRY

    adapter = ACTION_REGISTRY.get_adapter("stripe")
    result  = await adapter.execute("CreatePaymentLink", params, config)
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Optional

import structlog

from app.integrations.actions import ALL_ACTIONS, MCPAction, list_actions_for_provider
from app.integrations.errors import (
    ActionNotSupportedError,
    IntegrationError,
    IntegrationException,
    VerifyResult,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# BaseAdapter ABC
# ---------------------------------------------------------------------------

class BaseAdapter(ABC):
    """Abstract base class every provider adapter must implement.

    Subclasses must set:
      provider_name   — snake_case provider identifier, e.g. "stripe"
      supported_actions — set of canonical action names this adapter handles

    Subclasses must implement:
      execute(action, params, config) → dict
      verify_config(config)          → VerifyResult
    """

    provider_name: str = ""
    supported_actions: set[str] = set()

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def execute(self, action: str, params: dict, config: dict) -> dict:
        """Execute a canonical MCP action.

        Parameters
        ----------
        action:
            Canonical action name, e.g. "CreatePaymentLink"
        params:
            Validated parameters conforming to the canonical schema
        config:
            Decrypted tenant credentials from tool_metadata

        Returns
        -------
        dict — Response conforming to the canonical output_schema.
              Always includes ``"provider": self.provider_name``.

        Raises
        ------
        IntegrationException subclasses on all errors.
        """

    @abstractmethod
    async def verify_config(self, config: dict) -> VerifyResult:
        """Verify that the supplied credentials are valid.

        Called by the /tools/verify endpoint *before* saving credentials to
        the database.  Must make a cheap, read-only API call that confirms
        the credentials work (e.g. ``stripe.accounts.retrieve()``).

        Must never raise — catches all exceptions and returns VerifyResult(ok=False).
        """

    # ------------------------------------------------------------------
    # Helpers for subclasses
    # ------------------------------------------------------------------

    def _require_config(self, config: dict, *keys: str) -> None:
        """Raise IntegrationConfigError if any key is missing/empty."""
        from app.integrations.errors import IntegrationConfigError
        for key in keys:
            if not config.get(key):
                raise IntegrationConfigError.missing(self.provider_name, key)

    def _unsupported(self, action: str) -> None:
        raise ActionNotSupportedError(action, self.provider_name)

    def _timed_verify(self, start: float) -> int:
        """Return elapsed ms since start (call time.monotonic() before request)."""
        return int((time.monotonic() - start) * 1000)

    def _tag(self, result: dict) -> dict:
        """Inject provider tag into the canonical response dict."""
        result["provider"] = self.provider_name
        return result


# ---------------------------------------------------------------------------
# AdapterRegistry — maps provider_name → adapter instance
# ---------------------------------------------------------------------------

class AdapterRegistry:
    """Central registry mapping provider names to adapter instances.

    Adapters are registered at import time via register().  The tool executor
    calls get_adapter() to obtain the right instance for a configured tool.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, BaseAdapter] = {}

    def register(self, adapter: BaseAdapter) -> None:
        self._adapters[adapter.provider_name] = adapter
        logger.debug("adapter_registered", provider=adapter.provider_name,
                     actions=sorted(adapter.supported_actions))

    def get_adapter(self, provider: str) -> Optional[BaseAdapter]:
        return self._adapters.get(provider)

    def list_providers(self) -> list[str]:
        return sorted(self._adapters.keys())

    def get_supported_actions(self, provider: str) -> set[str]:
        adapter = self._adapters.get(provider)
        return adapter.supported_actions if adapter else set()

    def provider_for_tool_name(self, tool_name: str) -> Optional[str]:
        """Map a legacy tool_name (e.g. 'stripe_payment_link') to provider.

        Tries a prefix match against registered provider names.  This allows
        the executor to route existing tool names through the new adapter layer
        without renaming every tool in the DB.
        """
        for provider in self._adapters:
            if tool_name.startswith(provider):
                return provider
        return None

    # Resolve which action name to use for a given legacy tool_name
    _TOOL_NAME_TO_ACTION: dict[str, str] = {
        "stripe_payment_link": "CreatePaymentLink",
        "stripe_get_customer": "GetPaymentStatus",
        "stripe_check_payment": "GetPaymentStatus",
        "square_create_payment": "CreatePaymentLink",
        "paypal_create_order": "CreatePaymentLink",
        "twilio_send_sms": "SendSMS",
        "telnyx_send_bulk_sms": "SendSMS",
        "gmail_send_email": "SendEmail",
        "mailchimp_add_subscriber": "AddContactToList",
        "calendar_check_availability": "CheckCalendarAvailability",
        "google_calendar_check": "CheckCalendarAvailability",
        "calendar_book_appointment": "CreateCalendarEvent",
        "google_calendar_book": "CreateCalendarEvent",
        "calendly_availability": "CheckCalendarAvailability",
        "calendly_list_event_types": "CheckCalendarAvailability",
        "calendly_book": "ScheduleMeeting",
    }

    def resolve_action(self, tool_name: str) -> Optional[str]:
        """Return the canonical action name for a legacy tool_name, or None."""
        return self._TOOL_NAME_TO_ACTION.get(tool_name)


# Singleton registry — imported everywhere
ACTION_REGISTRY = AdapterRegistry()


# ---------------------------------------------------------------------------
# Bootstrap: import all adapters so they self-register
# ---------------------------------------------------------------------------

def _bootstrap() -> None:
    """Import adapter modules so their register() calls execute.

    Called once at module import time.  Adding a new provider requires only:
      1. Creating services/mcp-server/app/integrations/adapters/<provider>.py
      2. Calling ACTION_REGISTRY.register(MyAdapter()) at the bottom of that file
      3. Adding the import here
    """
    try:
        from app.integrations.adapters import stripe    # noqa: F401
    except Exception as exc:
        logger.warning("adapter_load_failed", provider="stripe", error=str(exc))
    try:
        from app.integrations.adapters import twilio    # noqa: F401
    except Exception as exc:
        logger.warning("adapter_load_failed", provider="twilio", error=str(exc))
    try:
        from app.integrations.adapters import google_calendar  # noqa: F401
    except Exception as exc:
        logger.warning("adapter_load_failed", provider="google_calendar", error=str(exc))
    try:
        from app.integrations.adapters import mailchimp  # noqa: F401
    except Exception as exc:
        logger.warning("adapter_load_failed", provider="mailchimp", error=str(exc))
    try:
        from app.integrations.adapters import square     # noqa: F401
    except Exception as exc:
        logger.warning("adapter_load_failed", provider="square", error=str(exc))
    try:
        from app.integrations.adapters import calendly   # noqa: F401
    except Exception as exc:
        logger.warning("adapter_load_failed", provider="calendly", error=str(exc))


_bootstrap()
