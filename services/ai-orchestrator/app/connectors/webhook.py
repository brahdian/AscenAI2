"""
Generic webhook escalation connector.

Required connector_config keys:
  url     — HTTPS endpoint to POST to

Optional connector_config keys:
  secret  — if set, adds X-AscenAI-Signature header (HMAC-SHA256 of body)
  headers — dict of extra headers to include
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import structlog
import httpx

from app.connectors.base import BaseConnector, ConnectorResult, EscalationPayload

logger = structlog.get_logger(__name__)


class WebhookConnector(BaseConnector):
    """
    POSTs a JSON escalation payload to any HTTPS webhook URL.
    Useful for custom integrations, internal ticketing, Slack, etc.
    """

    async def handoff(self, payload: EscalationPayload) -> ConnectorResult:
        url = self.config.get("url", "").strip()
        if not url:
            return ConnectorResult(success=False, error="Webhook url is required")
        if not url.startswith("https://"):
            return ConnectorResult(success=False, error="Webhook url must use HTTPS")

        body = {
            "event": "escalation",
            "timestamp": int(time.time()),
            "session_id": payload.session_id,
            "tenant_id": payload.tenant_id,
            "agent_name": payload.agent_name,
            "channel": payload.channel,
            "contact": {
                "name": payload.contact_name,
                "phone": payload.contact_phone,
                "email": payload.contact_email,
            },
            "trigger_message": payload.trigger_message,
            "history": payload.history[-20:],  # cap at last 20 turns
        }
        raw_body = json.dumps(body, separators=(",", ":"))

        headers: dict = {"Content-Type": "application/json"}

        # HMAC signature
        secret = self.config.get("secret", "")
        if secret:
            sig = hmac.new(secret.encode(), raw_body.encode(), hashlib.sha256).hexdigest()
            headers["X-AscenAI-Signature"] = f"sha256={sig}"

        # Extra headers from config
        for k, v in (self.config.get("headers") or {}).items():
            headers[k] = str(v)

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, content=raw_body, headers=headers)
            if resp.status_code >= 400:
                logger.error("webhook_escalation_failed", status=resp.status_code, url=url, body=resp.text[:200])
                return ConnectorResult(success=False, error=f"Webhook {resp.status_code}: {resp.text[:200]}")

        logger.info("webhook_escalation_sent", url=url, session_id=payload.session_id)
        return ConnectorResult(success=True, raw={"status": resp.status_code})
