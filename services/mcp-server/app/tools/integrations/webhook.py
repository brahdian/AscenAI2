"""Custom webhook integration handler — generic HTTP POST to any endpoint."""
from __future__ import annotations

import httpx

CUSTOM_WEBHOOK_SCHEMA = {
    "type": "object",
    "required": ["payload"],
    "properties": {
        "payload": {
            "type": "object",
            "description": "JSON payload to POST to the configured webhook URL",
        },
        "event_type": {
            "type": "string",
            "description": "Optional event type label included in the payload",
        },
    },
}


async def handle_custom_webhook(parameters: dict, tenant_config: dict) -> dict:
    """POST a JSON payload to the configured webhook URL."""
    url = tenant_config.get("url", "")
    secret = tenant_config.get("secret", "")

    if not url:
        return {"error": "Webhook not configured. Add your webhook URL."}

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    body = dict(parameters.get("payload", {}))
    if parameters.get("event_type"):
        body["event_type"] = parameters["event_type"]

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(url, headers=headers, json=body)
        except httpx.ConnectError:
            return {"error": f"Could not connect to webhook URL: {url}"}
        except httpx.TimeoutException:
            return {"error": "Webhook request timed out after 15s"}

    return {
        "status_code": resp.status_code,
        "success": resp.is_success,
        "response": resp.text[:500] if resp.text else None,
    }
