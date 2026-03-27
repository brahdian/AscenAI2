"""Custom webhook integration handler — generic HTTP POST to any endpoint."""
from __future__ import annotations

import ipaddress
import urllib.parse

import httpx

_PRIVATE_PREFIXES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _validate_webhook_url(url: str) -> str | None:
    """Return an error message string if the URL is unsafe, else None."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return "Invalid webhook URL."

    if parsed.scheme != "https":
        return "Webhook URL must use HTTPS."

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return "Webhook URL must include a hostname."

    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return "Webhook URL must not target localhost."

    try:
        ip = ipaddress.ip_address(hostname)
        for net in _PRIVATE_PREFIXES:
            if ip in net:
                return "Webhook URL must not target a private or reserved IP address."
    except ValueError:
        pass  # domain name — allowed

    return None

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

    # SSRF guard — prevent requests to internal/private network addresses
    url_error = _validate_webhook_url(url)
    if url_error:
        return {"error": url_error}

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
