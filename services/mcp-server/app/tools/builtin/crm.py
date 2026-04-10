"""Built-in CRM tool handlers — stub implementations awaiting real CRM integration."""
from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

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
    """CRM lookup — stub awaiting real CRM integration."""
    identifier = (
        parameters.get("customer_id")
        or parameters.get("phone")
        or parameters.get("email")
    )
    if not identifier:
        return {"found": False, "customer": None}

    logger.warning("crm_stub_lookup", identifier=identifier, note="Real CRM integration not yet implemented")
    return {
        "found": False,
        "error": "CRM integration is not yet active. Customer data is not available.",
        "status": "stub_not_implemented",
    }


async def handle_crm_update(parameters: dict, tenant_config: dict) -> dict:
    """CRM update — stub awaiting real CRM integration."""
    customer_id = parameters.get("customer_id", "UNKNOWN")
    logger.warning("crm_stub_update", customer_id=customer_id, note="Real CRM integration not yet implemented")
    return {
        "success": False,
        "error": "CRM integration is not yet active. Cannot update customer records.",
        "status": "stub_not_implemented",
    }
