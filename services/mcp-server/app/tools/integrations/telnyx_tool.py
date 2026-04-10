import httpx
from typing import Any

async def handle_telnyx_send_bulk_sms(parameters: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """
    Send bulk SMS via Telnyx.
    """
    api_key = config.get("api_key")
    from_number = config.get("from_number")
    to_numbers = parameters.get("to", [])
    text = parameters.get("text")

    if not api_key:
        return {"success": False, "error": "Telnyx api_key missing in config"}

    url = "https://api.telnyx.com/v2/messages"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    results = []
    async with httpx.AsyncClient() as client:
        # For bulk, Telnyx supports batching but here we do it simply for the stub
        for to in to_numbers:
            payload = {
                "from": from_number,
                "to": to,
                "text": text
            }
            try:
                response = await client.post(url, json=payload, headers=headers)
                results.append({"to": to, "status": response.status_code, "data": response.json()})
            except Exception as e:
                results.append({"to": to, "status": "error", "error": str(e)})

    return {"success": True, "results": results}
