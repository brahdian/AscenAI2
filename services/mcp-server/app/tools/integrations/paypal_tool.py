"""PayPal Checkout integration.

PayPal Orders API v2 — REST/JSON.
API reference: https://developer.paypal.com/docs/api/orders/v2/

Per-agent config keys required:
  - client_id    : PayPal application Client ID
  - secret       : PayPal application Secret
  - environment  : "production" | "sandbox" (default "sandbox")
"""
from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

_PAYPAL_URLS = {
    "production": "https://api-m.paypal.com",
    "sandbox": "https://api-m.sandbox.paypal.com",
}


async def _get_paypal_access_token(client_id: str, secret: str, base_url: str) -> str | None:
    """Exchange client credentials for a PayPal OAuth2 access token."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{base_url}/v1/oauth2/token",
                data={"grant_type": "client_credentials"},
                auth=(client_id, secret),
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            return resp.json().get("access_token")
    except Exception as exc:
        logger.error("paypal_auth_error", error=str(exc))
        return None


async def handle_paypal_create_order(parameters: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """
    Create a PayPal order and return an approval URL.

    Required config: client_id, secret
    Optional config: environment (production|sandbox, default sandbox)

    Required parameters: amount, currency (default USD)
    Optional parameters: description, return_url, cancel_url
    """
    client_id = config.get("client_id", "").strip()
    secret = config.get("secret", "").strip()
    environment = config.get("environment", "sandbox").lower()

    if not client_id or not secret:
        return {"success": False, "error": "PayPal not configured. Add your client_id and secret."}

    amount = parameters.get("amount")
    currency = str(parameters.get("currency", "USD")).upper()
    description = str(parameters.get("description", "Order"))
    return_url = str(parameters.get("return_url", "https://example.com/return"))
    cancel_url = str(parameters.get("cancel_url", "https://example.com/cancel"))

    if not amount:
        return {"success": False, "error": "Missing required parameter: amount"}

    base_url = _PAYPAL_URLS.get(environment, _PAYPAL_URLS["sandbox"])

    access_token = await _get_paypal_access_token(client_id, secret, base_url)
    if not access_token:
        return {"success": False, "error": "Failed to authenticate with PayPal. Check your client_id and secret."}

    order_payload = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "amount": {
                    "currency_code": currency,
                    "value": f"{float(amount):.2f}",
                },
                "description": description,
            }
        ],
        "application_context": {
            "return_url": return_url,
            "cancel_url": cancel_url,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/v2/checkout/orders",
                json=order_payload,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        order_id = data.get("id")
        status = data.get("status")
        approval_url = next(
            (link["href"] for link in data.get("links", []) if link.get("rel") == "approve"),
            None,
        )

        logger.info("paypal_order_created", order_id=order_id, status=status, environment=environment)
        return {
            "success": True,
            "order_id": order_id,
            "status": status,
            "approval_url": approval_url,
            "currency": currency,
            "amount": f"{float(amount):.2f}",
        }
    except httpx.HTTPStatusError as exc:
        error_body = exc.response.text
        logger.error("paypal_order_error", status=exc.response.status_code, body=error_body)
        return {"success": False, "error": f"PayPal returned HTTP {exc.response.status_code}: {error_body[:200]}"}
    except httpx.RequestError as exc:
        logger.error("paypal_request_error", error=str(exc))
        return {"success": False, "error": f"Failed to connect to PayPal API: {exc}"}
