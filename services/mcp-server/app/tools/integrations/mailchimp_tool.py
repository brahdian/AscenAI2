import httpx
from typing import Any

async def handle_mailchimp_add_subscriber(parameters: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """
    Add a subscriber to a Mailchimp list.
    """
    api_key = config.get("api_key")
    server_prefix = config.get("server_prefix")
    list_id = parameters.get("list_id")
    email = parameters.get("email")
    status = parameters.get("status", "subscribed")

    if not api_key or not server_prefix:
        return {"success": False, "error": "Mailchimp api_key or server_prefix missing in config"}

    url = f"https://{server_prefix}.api.mailchimp.com/3.0/lists/{list_id}/members"
    auth = ("user", api_key)
    payload = {
        "email_address": email,
        "status": status
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, auth=auth)
            response.raise_for_status()
            return {"success": True, "data": response.json()}
        except Exception as e:
            return {"success": False, "error": str(e)}
