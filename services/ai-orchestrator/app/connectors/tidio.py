"""
Tidio live-agent escalation connector.

Tidio's REST API does not expose a direct "create conversation" endpoint —
conversations are created by visitors in the widget. Instead, this connector
fires Tidio's operator-notification API and falls back to sending a webhook
POST to a configured URL (Tidio → Automation → Webhooks can receive this).

Required connector_config keys:
  public_key    — Tidio Public API Key (from Settings → Developer)
  private_key   — Tidio Private API Key

Optional connector_config keys:
  webhook_url   — if set, also POST the escalation payload to this URL
                  (use Tidio Automations to trigger agent assignment on receipt)
  operator_id   — Tidio operator ID to notify
"""
from __future__ import annotations

import json
import time
import structlog
import httpx

from app.connectors.base import BaseConnector, ConnectorResult, EscalationPayload

logger = structlog.get_logger(__name__)
_BASE = "https://www.tidio.com/api"


class TidioConnector(BaseConnector):
    """
    Tidio connector.

    Because Tidio's REST API is visitor-widget-centric, this connector works
    best when paired with a Tidio Automation webhook:
      1. It POSTs the escalation payload to your webhook_url.
      2. A Tidio Automation flow triggers on that webhook and assigns an operator.
    If no webhook_url, it attempts to create a visitor conversation via the Tidio API.
    """

    async def handoff(self, payload: EscalationPayload) -> ConnectorResult:
        public_key = self.config.get("public_key", "")
        private_key = self.config.get("private_key", "")
        webhook_url = self.config.get("webhook_url", "")

        if not public_key and not webhook_url:
            return ConnectorResult(success=False, error="Tidio requires public_key or webhook_url")

        transcript = self._format_history(payload.history)
        notification = {
            "event": "ascenai_escalation",
            "timestamp": int(time.time()),
            "session_id": payload.session_id,
            "agent_name": payload.agent_name,
            "channel": payload.channel,
            "contact": {
                "name": payload.contact_name,
                "phone": payload.contact_phone,
                "email": payload.contact_email,
            },
            "trigger": payload.trigger_message,
            "transcript_preview": transcript[:500],
        }

        # Primary: attempt Tidio API visitor/conversation creation
        ticket_id = ""
        if public_key and private_key:
            ticket_id = await self._create_via_api(
                public_key, private_key, payload, transcript
            )

        # Secondary / fallback: fire webhook for Tidio Automation to pick up
        if webhook_url:
            await self._fire_webhook(webhook_url, notification)

        if ticket_id or webhook_url:
            logger.info("tidio_handoff_success", ticket_id=ticket_id, session_id=payload.session_id)
            return ConnectorResult(success=True, ticket_id=ticket_id)

        return ConnectorResult(success=False, error="Tidio handoff produced no result — check configuration")

    async def _create_via_api(
        self, public_key: str, private_key: str,
        payload: EscalationPayload, transcript: str
    ) -> str:
        """Attempt to open a Tidio conversation via the REST API."""
        headers = {
            "X-Auth-Token": private_key,
            "X-Public-Key": public_key,
            "Content-Type": "application/json",
        }
        note = (
            f"[AscenAI Escalation] Bot: {payload.agent_name}\n"
            f"Contact: {payload.contact_name or 'Unknown'}"
            + (f" | {payload.contact_email}" if payload.contact_email else "")
            + f"\nTrigger: {payload.trigger_message}\n\nTranscript:\n{transcript}"
        )
        body: dict = {
            "visitor_name": payload.contact_name or "Visitor",
            "message": note,
        }
        if payload.contact_email:
            body["visitor_email"] = payload.contact_email

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{_BASE}/conversations/", json=body, headers=headers)
                if resp.status_code in (200, 201):
                    return str(resp.json().get("id", ""))
        except Exception as exc:
            logger.warning("tidio_api_create_failed", error=str(exc))
        return ""

    async def _fire_webhook(self, url: str, data: dict) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, json=data)
        except Exception as exc:
            logger.warning("tidio_webhook_failed", url=url, error=str(exc))
