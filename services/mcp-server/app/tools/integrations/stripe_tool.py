"""Stripe integration handlers."""
from __future__ import annotations

import httpx

STRIPE_PAYMENT_LINK_SCHEMA = {
    "type": "object",
    "required": ["amount_cents", "currency", "description"],
    "properties": {
        "amount_cents": {
            "type": "integer",
            "description": "Amount in smallest currency unit (e.g. 5000 = $50.00 CAD)",
        },
        "currency": {
            "type": "string",
            "description": "ISO currency code, e.g. cad, usd",
            "default": "cad",
        },
        "description": {"type": "string", "description": "Product or service description"},
        "customer_email": {"type": "string", "description": "Pre-fill customer email (optional)"},
    },
}

STRIPE_CHECK_PAYMENT_SCHEMA = {
    "type": "object",
    "required": ["payment_intent_id"],
    "properties": {
        "payment_intent_id": {
            "type": "string",
            "description": "Stripe PaymentIntent ID (pi_...)",
        },
    },
}

_BASE = "https://api.stripe.com/v1"


async def handle_stripe_payment_link(parameters: dict, tenant_config: dict) -> dict:
    """Create a Stripe payment link."""
    secret_key = tenant_config.get("secret_key", "")
    if not secret_key:
        return {"error": "Stripe not configured. Add your secret key."}

    auth = (secret_key, "")

    # 1. Create a Price object
    async with httpx.AsyncClient(timeout=15, auth=auth) as client:
        price_resp = await client.post(
            f"{_BASE}/prices",
            data={
                "unit_amount": str(parameters["amount_cents"]),
                "currency": parameters.get("currency", "cad"),
                "product_data[name]": parameters["description"],
            },
        )

    if not price_resp.is_success:
        err = price_resp.json().get("error", {})
        return {"error": err.get("message", f"Stripe error {price_resp.status_code}")}

    price_id = price_resp.json()["id"]

    # 2. Create Payment Link
    link_data = {"line_items[0][price]": price_id, "line_items[0][quantity]": "1"}
    if parameters.get("customer_email"):
        link_data["after_completion[hosted_confirmation][custom_message]"] = "Thank you!"

    async with httpx.AsyncClient(timeout=15, auth=auth) as client:
        link_resp = await client.post(f"{_BASE}/payment_links", data=link_data)

    if not link_resp.is_success:
        err = link_resp.json().get("error", {})
        return {"error": err.get("message", f"Stripe error {link_resp.status_code}")}

    link = link_resp.json()
    return {
        "payment_link_id": link["id"],
        "url": link["url"],
        "amount_cents": parameters["amount_cents"],
        "currency": parameters.get("currency", "cad"),
        "description": parameters["description"],
        "active": link.get("active", True),
    }


async def handle_stripe_check_payment(parameters: dict, tenant_config: dict) -> dict:
    """Check the status of a Stripe PaymentIntent."""
    secret_key = tenant_config.get("secret_key", "")
    if not secret_key:
        return {"error": "Stripe not configured. Add your secret key."}

    pi_id = parameters["payment_intent_id"]

    async with httpx.AsyncClient(timeout=10, auth=(secret_key, "")) as client:
        resp = await client.get(f"{_BASE}/payment_intents/{pi_id}")

    if not resp.is_success:
        err = resp.json().get("error", {})
        return {"error": err.get("message", f"Stripe error {resp.status_code}")}

    pi = resp.json()
    return {
        "id": pi["id"],
        "status": pi["status"],
        "amount_cents": pi["amount"],
        "currency": pi["currency"],
        "paid": pi["status"] == "succeeded",
    }
