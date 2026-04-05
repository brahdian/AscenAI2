"""PayPal integration handlers."""
import structlog

logger = structlog.get_logger(__name__)

async def handle_paypal_create_order(parameters: dict, tenant_config: dict) -> dict:
    """Create a PayPal order — stub implementation awaiting real integration."""
    client_id = tenant_config.get("client_id")
    secret = tenant_config.get("secret")
    if not client_id or not secret:
        return {"success": False, "error": "PayPal not configured. Add your Client ID and Secret."}

    amount = parameters.get("amount")
    if not amount:
        return {"success": False, "error": "Missing required parameter: amount"}

    logger.warning("paypal_stub_used", amount=amount, note="Real PayPal integration not yet implemented")
    return {
        "success": False,
        "error": "PayPal integration is not yet active. Please use a different payment method or contact support.",
        "status": "stub_not_implemented",
    }
