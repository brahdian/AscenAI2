import httpx
import uuid
from typing import Any

async def handle_square_create_payment(parameters: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """
    Create a payment via Square.
    """
    access_token = config.get("access_token")
    location_id = config.get("location_id")
    amount = parameters.get("amount")
    currency = parameters.get("currency", "USD")
    source_id = parameters.get("source_id") # e.g. 'cnon:card-nonce-ok'

    if not access_token:
        return {"success": False, "error": "Square access_token missing in config"}

    url = "https://connect.squareup.com/v2/payments"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Square-Version": "2023-12-13"
    }
    
    idempotency_key = parameters.get("idempotency_key")
    if not idempotency_key:
        idempotency_key = uuid.uuid4().hex

    payload = {
        "idempotency_key": idempotency_key,
        "amount_money": {
            "amount": int(amount * 100), # Square expects cents
            "currency": currency
        },
        "source_id": source_id,
        "location_id": location_id
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return {"success": True, "data": response.json()}
        except Exception as e:
            return {"success": False, "error": str(e)}
