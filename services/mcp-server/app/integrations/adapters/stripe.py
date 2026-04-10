"""Stripe adapter — uses the official stripe-python SDK.

Config keys (stored encrypted in tool_metadata):
  secret_key   — Stripe secret key (sk_live_... or sk_test_...)

Supported canonical actions:
  CreatePaymentLink   — Creates a Stripe Price + Payment Link
  GetPaymentStatus    — Retrieves a PaymentIntent by ID
"""
from __future__ import annotations

import time
from typing import Any

import structlog

from app.integrations.base import ACTION_REGISTRY, BaseAdapter
from app.integrations.errors import (
    IntegrationAuthError,
    IntegrationConfigError,
    IntegrationRateLimitError,
    PaymentError,
    ProviderError,
    VerifyResult,
)

logger = structlog.get_logger(__name__)


class StripeAdapter(BaseAdapter):
    provider_name = "stripe"
    supported_actions = {"CreatePaymentLink", "GetPaymentStatus"}

    # ------------------------------------------------------------------
    # SDK client factory
    # ------------------------------------------------------------------

    def _get_client(self, config: dict):
        """Return a configured stripe.StripeClient instance."""
        try:
            import stripe as _stripe
        except ImportError:
            raise ImportError("stripe package not installed. Run: pip install stripe")

        api_key = (
            config.get("secret_key")
            or config.get("api_key")
            or config.get("value")  # ToolAuthConfig bearer/api_key path
        )
        if not api_key:
            raise IntegrationConfigError.missing(self.provider_name, "secret_key")
        return _stripe.StripeClient(api_key=api_key)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict, config: dict) -> dict:
        if action == "CreatePaymentLink":
            return await self._create_payment_link(params, config)
        if action == "GetPaymentStatus":
            return await self._get_payment_status(params, config)
        self._unsupported(action)

    async def verify_config(self, config: dict) -> VerifyResult:
        """Retrieve the Stripe account to confirm the key is valid."""
        start = time.monotonic()
        try:
            import stripe as _stripe
            client = self._get_client(config)
            # Use asyncio executor so Stripe SDK (sync) doesn't block the event loop
            import asyncio
            account = await asyncio.get_event_loop().run_in_executor(
                None, lambda: client.accounts.retrieve()
            )
            return VerifyResult(
                ok=True,
                latency_ms=self._timed_verify(start),
                details={
                    "account_id": account.get("id", ""),
                    "business_name": (account.get("business_profile") or {}).get("name", ""),
                    "mode": "test" if (config.get("secret_key") or "").startswith("sk_test_") else "live",
                    "country": account.get("country", ""),
                },
            )
        except IntegrationConfigError as exc:
            return VerifyResult(ok=False, latency_ms=self._timed_verify(start),
                                error=str(exc))
        except Exception as exc:
            msg = _stripe_error_message(exc) if "stripe" in str(type(exc).__module__) else str(exc)
            return VerifyResult(ok=False, latency_ms=self._timed_verify(start), error=msg)

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    async def _create_payment_link(self, params: dict, config: dict) -> dict:
        """Canonical CreatePaymentLink → Stripe Price + PaymentLink."""
        import asyncio
        import stripe as _stripe

        client = self._get_client(config)

        # Canonical: amount is dollars (float). Stripe: smallest unit (int).
        amount_cents = _to_cents(params["amount"], params["currency"])
        currency = params["currency"].lower()
        description = params["description"]
        idempotency_key = params.get("idempotency_key")

        try:
            # 1. Create an inline Price via a Product
            price: dict = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.prices.create(
                    params={
                        "unit_amount": amount_cents,
                        "currency": currency,
                        "product_data": {"name": description},
                    },
                    **({"stripe_version": "2024-06-20"} if idempotency_key else {}),
                ),
            )

            # 2. Create Payment Link
            link_params: dict[str, Any] = {
                "line_items": [{"price": price["id"], "quantity": 1}],
            }
            if params.get("customer_email"):
                # pre-fill customer email on checkout
                link_params["customer_creation"] = "always"

            payment_link: dict = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.payment_links.create(
                    params=link_params,
                ),
            )

        except Exception as exc:
            raise _normalize_stripe_error(exc, self.provider_name)

        return self._tag({
            "payment_link_id": payment_link["id"],
            "url": payment_link["url"],
            "amount": params["amount"],
            "currency": currency,
        })

    async def _get_payment_status(self, params: dict, config: dict) -> dict:
        """Canonical GetPaymentStatus → Stripe PaymentIntent retrieve."""
        import asyncio
        import stripe as _stripe

        client = self._get_client(config)
        payment_id = params["payment_id"]

        try:
            pi: dict = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.payment_intents.retrieve(payment_id),
            )
        except Exception as exc:
            raise _normalize_stripe_error(exc, self.provider_name)

        # Normalize Stripe status → canonical status
        status_map = {
            "succeeded": "completed",
            "requires_payment_method": "pending",
            "requires_confirmation": "pending",
            "requires_action": "pending",
            "processing": "pending",
            "requires_capture": "pending",
            "canceled": "cancelled",
        }
        canonical_status = status_map.get(pi.get("status", ""), "pending")

        return self._tag({
            "payment_id": pi["id"],
            "status": canonical_status,
            "amount": pi.get("amount", 0) / 100.0,
            "currency": pi.get("currency", ""),
            "paid": pi.get("status") == "succeeded",
        })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_cents(amount: float, currency: str) -> int:
    """Convert major-unit amount to smallest currency unit.

    Most currencies use 2 decimal places (cents).
    Zero-decimal currencies (JPY, KRW …) skip the multiplication.
    """
    _ZERO_DECIMAL = {"bif", "clp", "gnf", "jpy", "kmf", "krw", "mga",
                     "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf"}
    if currency.lower() in _ZERO_DECIMAL:
        return int(amount)
    return int(round(amount * 100))


def _stripe_error_message(exc: Exception) -> str:
    """Extract a clean message from a Stripe exception."""
    # stripe.StripeError has a user_message attribute
    return getattr(exc, "user_message", None) or getattr(exc, "message", None) or str(exc)


def _normalize_stripe_error(exc: Exception, provider: str) -> Exception:
    """Convert a Stripe SDK exception to a normalized IntegrationException."""
    try:
        import stripe as _stripe
        if isinstance(exc, _stripe.AuthenticationError):
            return IntegrationAuthError.from_provider(provider, provider_code="authentication_error")
        if isinstance(exc, _stripe.RateLimitError):
            return IntegrationRateLimitError.from_provider(provider)
        if isinstance(exc, _stripe.CardError):
            decline_code = getattr(exc, "decline_code", None)
            return PaymentError.card_declined(provider, decline_code)
        if isinstance(exc, _stripe.InvalidRequestError):
            from app.integrations.errors import IntegrationError, IntegrationException, ErrorCode
            return IntegrationException(IntegrationError(
                code=ErrorCode.INVALID_INPUT,
                message=_stripe_error_message(exc),
                provider=provider,
                provider_code=getattr(exc, "code", None),
                retryable=False,
            ))
        if isinstance(exc, _stripe.StripeError):
            http_status = getattr(exc, "http_status", None)
            return ProviderError.from_http(provider, http_status or 500, _stripe_error_message(exc))
    except ImportError:
        pass
    return ProviderError.from_http(provider, 500, str(exc))


# Self-register
ACTION_REGISTRY.register(StripeAdapter())
