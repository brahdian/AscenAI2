"""Square adapter — Square Payments API v2 via httpx.

Config keys (stored encrypted in tool_metadata):
  access_token  — Square OAuth access token or personal access token
  location_id   — Square Location ID (required for payments)
  environment   — "production" or "sandbox" (default: production)

Supported canonical actions:
  CreatePaymentLink — Generate a Square checkout link
"""
from __future__ import annotations

import time
import uuid

import httpx
import structlog

from app.integrations.base import ACTION_REGISTRY, BaseAdapter
from app.integrations.errors import (
    IntegrationAuthError,
    IntegrationConfigError,
    IntegrationError,
    IntegrationException,
    ErrorCode,
    PaymentError,
    ProviderError,
    VerifyResult,
)

logger = structlog.get_logger(__name__)

_API_BASE = {
    "production": "https://connect.squareup.com",
    "sandbox":    "https://connect.squareupsandbox.com",
}
_SQUARE_VERSION = "2024-01-18"


class SquareAdapter(BaseAdapter):
    provider_name = "square"
    supported_actions = {"CreatePaymentLink"}

    def _headers(self, config: dict) -> dict[str, str]:
        token = config.get("access_token") or config.get("value")
        if not token:
            raise IntegrationConfigError.missing(self.provider_name, "access_token")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Square-Version": _SQUARE_VERSION,
        }

    def _base(self, config: dict) -> str:
        env = config.get("environment", "production").lower()
        return _API_BASE.get(env, _API_BASE["production"])

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict, config: dict) -> dict:
        if action == "CreatePaymentLink":
            return await self._create_payment_link(params, config)
        self._unsupported(action)

    async def verify_config(self, config: dict) -> VerifyResult:
        """Fetch location info to confirm the token works."""
        start = time.monotonic()
        try:
            headers = self._headers(config)
            base = self._base(config)
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{base}/v2/locations", headers=headers)
            if resp.status_code == 401:
                return VerifyResult(ok=False, latency_ms=self._timed_verify(start),
                                    error="Square access token is invalid.")
            if not resp.is_success:
                return VerifyResult(ok=False, latency_ms=self._timed_verify(start),
                                    error=f"Square error {resp.status_code}")

            locations = resp.json().get("locations", [])
            loc_names = [loc.get("name", "") for loc in locations[:3]]
            return VerifyResult(
                ok=True,
                latency_ms=self._timed_verify(start),
                details={
                    "location_count": len(locations),
                    "locations": loc_names,
                    "environment": config.get("environment", "production"),
                },
            )
        except IntegrationConfigError as exc:
            return VerifyResult(ok=False, latency_ms=self._timed_verify(start), error=str(exc))
        except Exception as exc:
            return VerifyResult(ok=False, latency_ms=self._timed_verify(start), error=str(exc))

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    async def _create_payment_link(self, params: dict, config: dict) -> dict:
        """CreatePaymentLink → Square Checkout payment link.

        Square expects amounts in the smallest currency unit (cents for USD/CAD).
        Canonical input uses major units (dollars), so we multiply by 100.
        """
        headers = self._headers(config)
        base = self._base(config)
        location_id = config.get("location_id")
        if not location_id:
            raise IntegrationConfigError.missing(self.provider_name, "location_id")

        # Canonical → Square: convert dollars to cents
        amount_cents = int(round(params["amount"] * 100))
        currency = params["currency"].upper()

        idempotency_key = params.get("idempotency_key") or str(uuid.uuid4())

        body = {
            "idempotency_key": idempotency_key,
            "quick_pay": {
                "name": params["description"],
                "price_money": {
                    "amount": amount_cents,
                    "currency": currency,
                },
                "location_id": location_id,
            },
        }
        if params.get("customer_email"):
            body["pre_populated_data"] = {"buyer_email": params["customer_email"]}

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{base}/v2/online-checkout/payment-links",
                                     headers=headers, json=body)

        if resp.status_code == 401:
            raise IntegrationAuthError.from_provider(self.provider_name)
        if not resp.is_success:
            errors = resp.json().get("errors", [])
            msg = errors[0].get("detail", f"Square error {resp.status_code}") if errors else f"error {resp.status_code}"
            # Check for payment decline codes
            if any(e.get("category") == "PAYMENT_METHOD_ERROR" for e in errors):
                raise PaymentError.generic(self.provider_name, msg)
            raise ProviderError.from_http(self.provider_name, resp.status_code, msg)

        data = resp.json().get("payment_link", {})
        return self._tag({
            "payment_link_id": data.get("id"),
            "url": data.get("url"),
            "amount": params["amount"],
            "currency": currency,
        })


# Self-register
ACTION_REGISTRY.register(SquareAdapter())
