"""Square Checkout Link integration.

Square Online Checkout provides a secure, hosted checkout page.
API reference: https://developer.squareup.com/reference/square/checkout-api/create-payment-link
"""
import httpx
import uuid
import structlog
from typing import Any

logger = structlog.get_logger(__name__)

async def handle_square_create_checkout(parameters: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """
    Generate a Square Checkout link for a payment.

    Required config: access_token, location_id
    Required parameters: amount
    Optional parameters: description, currency (default USD)
    """
    access_token = config.get("access_token")
    location_id = config.get("location_id")
    
    if not access_token or not location_id:
        return {"success": False, "error": "Square access_token and location_id are required in config"}

    amount = parameters.get("amount")
    currency = parameters.get("currency", "USD").upper()
    description = parameters.get("description", "Payment Request")

    if not amount:
        return {"success": False, "error": "Missing required parameter: amount"}

    url = "https://connect.squareup.com/v2/online-checkout/payment-links"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Square-Version": "2023-12-13"
    }
    
    idempotency_key = parameters.get("idempotency_key") or uuid.uuid4().hex

    payload = {
        "idempotency_key": idempotency_key,
        "quick_pay": {
            "name": description,
            "price_money": {
                "amount": int(float(amount) * 100), # Square expects cents
                "currency": currency
            },
            "location_id": location_id
        }
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            link = data.get("payment_link", {})
            checkout_url = link.get("url")
            
            if not checkout_url:
                return {"success": False, "error": "Square did not return a checkout URL"}

            logger.info(
                "square_link_created",
                amount=amount,
                currency=currency,
                location_id=location_id
            )
            
            return {
                "success": True,
                "checkout_url": checkout_url,
                "payment_link_id": link.get("id"),
                "amount": amount,
                "currency": currency
            }
    except httpx.HTTPStatusError as exc:
        data = exc.response.json()
        error_msg = data.get("errors", [{}])[0].get("detail", str(exc))
        logger.error("square_api_error", status=exc.response.status_code, error=error_msg)
        return {"success": False, "error": f"Square API Error: {error_msg}"}
    except Exception as e:
        logger.error("square_unexpected_error", error=str(e))
        return {"success": False, "error": str(e)}
