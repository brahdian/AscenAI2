"""Built-in CRM tool handlers."""
from __future__ import annotations

CRM_LOOKUP_SCHEMA = {
    "type": "object",
    "properties": {
        "phone": {"type": "string"},
        "email": {"type": "string"},
        "customer_id": {"type": "string"},
    },
}

CRM_LOOKUP_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "customer": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "visit_count": {"type": "integer"},
                "last_visit": {"type": "string"},
                "notes": {"type": "string"},
            },
        },
    },
}

CRM_UPDATE_SCHEMA = {
    "type": "object",
    "required": ["customer_id"],
    "properties": {
        "customer_id": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "phone": {"type": "string"},
        "notes": {"type": "string"},
    },
}


async def handle_crm_lookup(parameters: dict, tenant_config: dict) -> dict:
    """Return a simulated CRM lookup result."""
    identifier = (
        parameters.get("customer_id")
        or parameters.get("phone")
        or parameters.get("email")
    )
    if not identifier:
        return {"found": False, "customer": None}

    # Simulated customer data
    return {
        "found": True,
        "customer": {
            "id": "CUST-001",
            "name": "Alex Johnson",
            "email": parameters.get("email", "alex@example.com"),
            "phone": parameters.get("phone", "+15551234567"),
            "visit_count": 5,
            "last_visit": "2025-03-15",
            "notes": "Prefers pepperoni pizza, no mushrooms.",
        },
    }


async def handle_crm_update(parameters: dict, tenant_config: dict) -> dict:
    """Simulate updating a CRM record."""
    customer_id = parameters.get("customer_id", "UNKNOWN")
    return {
        "success": True,
        "customer_id": customer_id,
        "updated_fields": [k for k in parameters if k != "customer_id"],
        "message": f"Customer {customer_id} updated successfully.",
    }
