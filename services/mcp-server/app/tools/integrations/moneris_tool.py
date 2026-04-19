"""Moneris Checkout (MCO) integration (Canada).

Moneris Checkout (MCO) provides a secure, hosted payment page.
API reference: https://developer.moneris.com/Documentation/NA/Moneris%20Checkout/

Per-agent config keys required:
  - store_id      : Moneris store ID
  - api_token     : Moneris API token
  - checkout_id   : Moneris Checkout ID (MCO-xxxxxx)
  - environment   : "production" | "qa" (default "qa")
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

# Moneris Checkout Preload Endpoints
_MCO_PRELOAD_URLS = {
    "production": "https://gateway.moneris.com/chkt/request/request.php",
    "qa": "https://esqa.moneris.com/chkt/request/request.php",
}

# Moneris Checkout Redirect Endpoints
_MCO_CHKT_URLS = {
    "production": "https://gateway.moneris.com/chkt/index.php",
    "qa": "https://esqa.moneris.com/chkt/index.php",
}


async def handle_moneris_create_checkout(parameters: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """
    Initialize a Moneris Checkout session and return a payment URL.

    Required config: store_id, api_token, checkout_id
    Optional config: environment (production|qa, default qa)

    Required parameters: amount
    Optional parameters: cart_id (order reference), description
    """
    store_id = config.get("store_id", "").strip()
    api_token = config.get("api_token", "").strip()
    checkout_id = config.get("checkout_id", "").strip()
    environment = config.get("environment", "qa").lower()

    if not all([store_id, api_token, checkout_id]):
        return {"success": False, "error": "Moneris Checkout not fully configured. store_id, api_token, and checkout_id are required."}

    amount = str(parameters.get("amount", ""))
    cart_id = str(parameters.get("cart_id") or parameters.get("order_id", "order_link"))
    description = str(parameters.get("description", "Payment Request"))

    if not amount:
        return {"success": False, "error": "Missing required parameter: amount"}

    preload_url = _MCO_PRELOAD_URLS.get(environment, _MCO_PRELOAD_URLS["qa"])
    
    # MCO Preload Request (JSON)
    payload = {
        "store_id": store_id,
        "api_token": api_token,
        "checkout_id": checkout_id,
        "action": "preload",
        "txn_total": f"{float(amount):.2f}",
        "cart_id": cart_id,
        "environment": environment,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                preload_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

            # MCO returns a 'ticket' which is used to build the checkout URL
            ticket = data.get("response", {}).get("ticket")
            if not ticket:
                error_msg = data.get("response", {}).get("error_msg", "Failed to initialize checkout session")
                logger.error("moneris_mco_preload_failed", error=error_msg, raw=data)
                return {"success": False, "error": error_msg}

            # Construct the final checkout link
            base_chkt_url = _MCO_CHKT_URLS.get(environment, _MCO_CHKT_URLS["qa"])
            full_checkout_url = f"{base_chkt_url}?ticket={ticket}"

            logger.info(
                "moneris_checkout_initialized",
                cart_id=cart_id,
                amount=amount,
                environment=environment,
            )
            
            return {
                "success": True,
                "checkout_url": full_checkout_url,
                "ticket": ticket,
                "amount": amount,
                "cart_id": cart_id,
            }
            
    except httpx.HTTPStatusError as exc:
        logger.error("moneris_mco_http_error", status=exc.response.status_code, error=str(exc))
        return {"success": False, "error": f"Moneris gateway returned HTTP {exc.response.status_code}"}
    except Exception as exc:
        logger.error("moneris_mco_unexpected_error", error=str(exc))
        return {"success": False, "error": f"Failed to initialize Moneris Checkout: {str(exc)}"}
