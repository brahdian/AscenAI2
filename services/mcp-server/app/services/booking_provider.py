"""Abstract booking provider interface and registry.

Every external CRM (Calendly, Square, Google Calendar, custom) implements
BookingProvider.  The registry maps provider name strings to concrete classes.

Providers are registered with @BookingProviderRegistry.register("name").
The appointment tool selects a provider via tenant_config["booking_provider"].

Hold semantics per provider
---------------------------
Calendly     — Creates an invitee immediately (Calendly has no "pending" state).
               Confirmation is a no-op; cancellation deletes the invitee.
Square       — Creates a booking with status PENDING; confirm → ACCEPTED.
Google Cal   — Creates an event with status tentative; confirm → confirmed.
Custom       — Calls configurable endpoints from tenant_config; falls back to
               storing slot locally and calling confirm_endpoint on payment.
Builtin      — Stores slot directly in booking_workflows (no external CRM).
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------

@dataclass
class SlotHoldResult:
    """Result returned by BookingProvider.hold_slot()."""
    external_id: str          # Calendly invitee UUID, Square booking ID, etc.
    external_url: Optional[str]  # e.g., Calendly reschedule/cancel URL
    held_until: datetime      # When the hold expires (computed from ttl_minutes)


@dataclass
class SlotConfirmResult:
    """Result returned by BookingProvider.confirm_slot()."""
    confirmed: bool
    confirmation_code: str    # Human-readable code shown to customer
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class SlotUnavailableError(Exception):
    """Raised when the requested slot is no longer available."""


class ProviderCallError(Exception):
    """Raised when an external CRM API call fails unexpectedly."""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class BookingProvider(ABC):
    """Abstract interface for external booking CRM providers."""

    def __init__(self, tenant_config: dict) -> None:
        self._config = tenant_config

    # ------------------------------------------------------------------
    # Required interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def hold_slot(
        self,
        *,
        workflow_id: uuid.UUID,
        service: str,
        slot_date: str,      # "YYYY-MM-DD"
        slot_time: str,      # "HH:MM"
        duration_minutes: int,
        customer_name: str,
        customer_email: str,
        customer_phone: str,
        ttl_minutes: int,
    ) -> SlotHoldResult:
        """Tentatively reserve the slot.

        MUST be idempotent: if called twice with the same workflow_id and the
        slot is already held by this workflow, return the same result.

        Raises SlotUnavailableError if the slot is taken by someone else.
        """

    @abstractmethod
    async def confirm_slot(
        self,
        external_id: str,
    ) -> SlotConfirmResult:
        """Finalize the booking after payment.

        MUST be idempotent: confirming an already-confirmed booking returns
        the existing confirmation_code without error.
        """

    @abstractmethod
    async def release_slot(
        self,
        external_id: str,
    ) -> None:
        """Cancel / release the tentative hold.

        MUST be idempotent: releasing an already-released booking is a no-op.
        """

    @abstractmethod
    async def check_slot_available(
        self,
        service: str,
        slot_date: str,
        slot_time: str,
        duration_minutes: int,
    ) -> bool:
        """Re-verify that the slot is still available.

        Called immediately before confirm_slot() to guard against race
        conditions where another booking landed between hold and payment.
        """


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class BookingProviderRegistry:
    """Maps provider name → BookingProvider class."""

    _providers: dict[str, type[BookingProvider]] = {}

    @classmethod
    def register(cls, name: str):
        """Class decorator to register a provider under a name."""
        def decorator(provider_cls: type[BookingProvider]) -> type[BookingProvider]:
            cls._providers[name] = provider_cls
            return provider_cls
        return decorator

    @classmethod
    def get(cls, provider_name: str, tenant_config: dict) -> BookingProvider:
        """Instantiate and return a provider for the given name.

        Falls back to "builtin" if the provider is unknown — never throws,
        so misconfigured tenants still get a working (if limited) experience.
        """
        provider_cls = cls._providers.get(provider_name)
        if provider_cls is None:
            logger.warning(
                "booking_provider_unknown",
                provider=provider_name,
                fallback="builtin",
            )
            provider_cls = cls._providers.get("builtin")
            if provider_cls is None:
                raise ValueError(
                    "No booking provider registered — "
                    "ensure providers are imported before use."
                )
        return provider_cls(tenant_config)

    @classmethod
    def registered_names(cls) -> list[str]:
        return list(cls._providers.keys())


# ---------------------------------------------------------------------------
# Ensure all providers are imported when this module is first loaded.
# Import order: providers register themselves via @BookingProviderRegistry.register
# ---------------------------------------------------------------------------

def _load_providers() -> None:
    from app.services.providers import (  # noqa: F401
        builtin_booking,
        calendly_booking,
        custom_booking,
        google_calendar_booking,
        square_booking,
    )


_load_providers()
