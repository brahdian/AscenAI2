"""Helcim integration handlers."""

async def handle_helcim_process_payment(parameters: dict, tenant_config: dict) -> dict:
    """Process a payment via Helcim."""
    account_id = tenant_config.get("account_id")
    api_token = tenant_config.get("api_token")
    if not account_id or not api_token:
        return {"error": "Helcim not configured. Add your account ID and API token."}
    
    # Stub implementation
    amount = parameters.get("amount")
    return {
        "status": "success",
        "message": f"Helcim payment of {amount} processed simulated.",
        "transaction_id": "helcim_sim_12345"
    }
