"""Moneris payment integration (Canada).

Moneris uses a custom XML-based gateway API.
API reference: https://developer.moneris.com/Documentation/NA/E-Commerce%20Solutions/API

Per-agent config keys required:
  - store_id     : Moneris store ID
  - api_token    : Moneris API token
  - environment  : "production" | "sandbox" (default "sandbox")
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

_MONERIS_URLS = {
    "production": "https://www3.moneris.com/gateway2/servlet/MpgRequest",
    "sandbox": "https://esqa.moneris.com/gateway2/servlet/MpgRequest",
}


def _build_purchase_xml(store_id: str, api_token: str, order_id: str, amount: str, pan: str, expdate: str, crypt_type: str = "7") -> str:
    """Build the Moneris Purchase XML request body."""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<request>
  <store_id>{store_id}</store_id>
  <api_token>{api_token}</api_token>
  <purchase>
    <store_id>{store_id}</store_id>
    <api_token>{api_token}</api_token>
    <order_id>{order_id}</order_id>
    <amount>{amount}</amount>
    <pan>{pan}</pan>
    <expdate>{expdate}</expdate>
    <crypt_type>{crypt_type}</crypt_type>
  </purchase>
</request>"""


def _parse_moneris_response(xml_text: str) -> dict[str, Any]:
    """Parse Moneris XML response into a dict."""
    try:
        root = ET.fromstring(xml_text)
        receipt = root.find("receipt")
        if receipt is None:
            return {"success": False, "error": "No receipt in response", "raw": xml_text}

        response_code = receipt.findtext("ResponseCode", "")
        message = receipt.findtext("Message", "")
        trans_id = receipt.findtext("TransID", "")
        receipt_id = receipt.findtext("ReceiptId", "")
        complete = receipt.findtext("Complete", "false").lower() == "true"

        # Moneris: ResponseCode < 50 and not "null" means approved
        approved = False
        try:
            if response_code and response_code != "null":
                approved = int(response_code) < 50
        except ValueError:
            approved = False

        return {
            "success": approved,
            "approved": approved,
            "response_code": response_code,
            "message": message,
            "transaction_id": trans_id,
            "receipt_id": receipt_id,
            "complete": complete,
        }
    except ET.ParseError as exc:
        logger.error("moneris_xml_parse_error", error=str(exc))
        return {"success": False, "error": f"Failed to parse Moneris response: {exc}"}


async def handle_moneris_process_payment(parameters: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """
    Process a payment via Moneris (Canada).

    Required config: store_id, api_token
    Optional config: environment (production|sandbox, default sandbox)

    Required parameters: amount, pan, expdate, order_id
    Optional parameters: crypt_type (default "7" = SSL)
    """
    store_id = config.get("store_id", "").strip()
    api_token = config.get("api_token", "").strip()
    environment = config.get("environment", "sandbox").lower()

    if not store_id or not api_token:
        return {"success": False, "error": "Moneris not configured. Add your store_id and api_token."}

    amount = str(parameters.get("amount", ""))
    pan = str(parameters.get("pan", ""))
    expdate = str(parameters.get("expdate", ""))
    order_id = str(parameters.get("order_id", ""))
    crypt_type = str(parameters.get("crypt_type", "7"))

    if not amount or not pan or not expdate or not order_id:
        return {"success": False, "error": "Missing required parameters: amount, pan, expdate, order_id"}

    url = _MONERIS_URLS.get(environment, _MONERIS_URLS["sandbox"])
    xml_body = _build_purchase_xml(store_id, api_token, order_id, amount, pan, expdate, crypt_type)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                content=xml_body.encode("utf-8"),
                headers={"Content-Type": "application/xml; charset=utf-8"},
            )
            resp.raise_for_status()
            result = _parse_moneris_response(resp.text)
            logger.info(
                "moneris_payment_processed",
                order_id=order_id,
                approved=result.get("approved"),
                response_code=result.get("response_code"),
                environment=environment,
            )
            return result
    except httpx.HTTPStatusError as exc:
        logger.error("moneris_http_error", status=exc.response.status_code, error=str(exc))
        return {"success": False, "error": f"Moneris gateway returned HTTP {exc.response.status_code}"}
    except httpx.RequestError as exc:
        logger.error("moneris_request_error", error=str(exc))
        return {"success": False, "error": f"Failed to connect to Moneris gateway: {exc}"}
