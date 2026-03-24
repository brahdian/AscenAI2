"""Built-in pizza ordering tool handlers."""
from __future__ import annotations

PIZZA_ORDER_SCHEMA = {
    "type": "object",
    "required": ["items", "delivery_address"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "quantity"],
                "properties": {
                    "name": {"type": "string"},
                    "size": {"type": "string", "enum": ["small", "medium", "large"]},
                    "quantity": {"type": "integer", "minimum": 1},
                    "toppings": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "delivery_address": {"type": "string"},
        "customer_name": {"type": "string"},
        "phone": {"type": "string"},
        "special_instructions": {"type": "string"},
    },
}

PIZZA_ORDER_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "order_id": {"type": "string"},
        "status": {"type": "string"},
        "estimated_delivery_minutes": {"type": "integer"},
        "total_price": {"type": "number"},
    },
}

ORDER_STATUS_SCHEMA = {
    "type": "object",
    "required": ["order_id"],
    "properties": {"order_id": {"type": "string"}},
}


async def handle_pizza_order(parameters: dict, tenant_config: dict) -> dict:
    """Simulate placing a pizza order."""
    import uuid, random

    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    items = parameters.get("items", [])
    total = sum(
        (12.99 if item.get("size") == "large" else 9.99 if item.get("size") == "medium" else 7.99)
        * item.get("quantity", 1)
        for item in items
    )

    return {
        "order_id": order_id,
        "status": "confirmed",
        "estimated_delivery_minutes": random.randint(25, 45),
        "total_price": round(total, 2),
        "message": f"Order {order_id} placed successfully!",
    }


async def handle_order_status(parameters: dict, tenant_config: dict) -> dict:
    """Return a simulated order status."""
    order_id = parameters.get("order_id", "UNKNOWN")
    return {
        "order_id": order_id,
        "status": "out_for_delivery",
        "estimated_minutes_remaining": 10,
    }
