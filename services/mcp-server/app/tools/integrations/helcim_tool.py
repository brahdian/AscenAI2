"""Helcim Pay integration.

Helcim Pay provides a secure, hosted checkout page.
API reference: https://devdocs.helcim.com/reference/initialize-helcim-pay
"""
from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

_HELCIM_API_BASE = "https://api.helcim.com/v2"


async def handle_helcim_create_link(parameters: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """
    Initialize a Helcim Pay checkout session and return a payment URL.

    Required config: api_token
    Required parameters: amount
    Optional parameters: currency (default CAD), invoice_number
    """
    api_token = config.get("api_token", "").strip()
    if not api_token:
        return {"success": False, "error": "Helcim not configured. Add your api_token."}

    amount = parameters.get("amount")
    currency = str(parameters.get("currency", "CAD")).upper()
    invoice_number = str(parameters.get("invoice_number", ""))

    if not amount:
        return {"success": False, "error": "Missing required parameter: amount"}

    # Helcim Pay Initialization Payload
    payload: dict[str, Any] = {
        "paymentType": "purchase",
        "amount": float(amount),
        "currency": currency,
    }
    if invoice_number:
        payload["invoiceNumber"] = invoice_number

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_HELCIM_API_BASE}/helcim-pay/initialize",
                json=payload,
                headers={
                    "api-token": api_token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            
            if resp.status_code in (200, 201):
                data = resp.json()
                checkout_url = data.get("checkoutUrl")
                if not checkout_url:
                    return {"success": False, "error": "Helcim Pay did not return a checkout URL"}
                
                logger.info(
                    "helcim_link_created",
                    amount=amount,
                    currency=currency,
                )
                return {
                    "success": True,
                    "checkout_url": checkout_url,
                    "amount": amount,
                    "currency": currency,
                }
            else:
                data = resp.json()
                error_msg = data.get("errors") or data.get("message") or f"Helcim returned HTTP {resp.status_code}"
                logger.warning("helcim_pay_init_failed", status=resp.status_code, error=error_msg)
                return {
                    "success": False,
                    "error": error_msg,
                }
                
    except httpx.RequestError as exc:
        logger.error("helcim_request_error", error=str(exc))
        return {"success": False, "error": f"Failed to connect to Helcim API: {exc}"}
    except Exception as exc:
        logger.error("helcim_unexpected_error", error=str(exc))
        return {"success": False, "error": f"Unexpected error: {str(exc)}"}
