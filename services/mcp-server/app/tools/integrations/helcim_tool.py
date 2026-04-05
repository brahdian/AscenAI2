"""Helcim payment integration.

Helcim Commerce API v2 — REST/JSON.
API reference: https://devdocs.helcim.com/reference

Per-agent config keys required:
  - api_token    : Helcim API token (from Helcim dashboard → API Access)
"""
from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

_HELCIM_API_BASE = "https://api.helcim.com/v2"


async def handle_helcim_process_payment(parameters: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """
    Process a card payment via Helcim Commerce API v2.

    Required config: api_token
    Required parameters: amount, card_number, card_expiry (MMYY), card_cvv
    Optional parameters: currency (default USD), invoice_number
    """
    api_token = config.get("api_token", "").strip()
    if not api_token:
        return {"success": False, "error": "Helcim not configured. Add your api_token."}

    amount = parameters.get("amount")
    card_number = str(parameters.get("card_number", ""))
    card_expiry = str(parameters.get("card_expiry", ""))  # MMYY
    card_cvv = str(parameters.get("card_cvv", ""))
    currency = str(parameters.get("currency", "USD")).upper()
    invoice_number = str(parameters.get("invoice_number", ""))

    if not amount or not card_number or not card_expiry or not card_cvv:
        return {"success": False, "error": "Missing required parameters: amount, card_number, card_expiry, card_cvv"}

    payload: dict[str, Any] = {
        "amount": float(amount),
        "currency": currency,
        "cardData": {
            "cardNumber": card_number,
            "cardExpiry": card_expiry,
            "cardCVV": card_cvv,
        },
    }
    if invoice_number:
        payload["invoiceNumber"] = invoice_number

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_HELCIM_API_BASE}/payment/purchase",
                json=payload,
                headers={
                    "api-token": api_token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            data = resp.json()

            if resp.status_code in (200, 201):
                approved = data.get("approved") == 1 or str(data.get("response", "")).startswith("1")
                logger.info(
                    "helcim_payment_processed",
                    approved=approved,
                    transaction_id=data.get("transactionId"),
                    amount=amount,
                )
                return {
                    "success": approved,
                    "approved": approved,
                    "transaction_id": data.get("transactionId"),
                    "approval_code": data.get("approvalCode"),
                    "message": data.get("message", ""),
                    "amount": amount,
                    "currency": currency,
                }
            else:
                logger.warning("helcim_payment_declined", status=resp.status_code, data=data)
                return {
                    "success": False,
                    "error": data.get("errors") or data.get("message") or f"Helcim returned HTTP {resp.status_code}",
                }
    except httpx.RequestError as exc:
        logger.error("helcim_request_error", error=str(exc))
        return {"success": False, "error": f"Failed to connect to Helcim API: {exc}"}
