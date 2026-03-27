"""
Front live-agent escalation connector.

Imports a message into a Front inbox as a new conversation.

Required connector_config keys:
  api_token   — Front API token (from Settings → API → Tokens)
  inbox_id    — inbox ID to import into (format: "inb_xxxxxxxx")

Optional connector_config keys:
  assignee_id — teammate ID to assign to (format: "tea_xxxxxxxx")
  tags        — list[str]: tag names to apply
"""
from __future__ import annotations

import structlog
import httpx

from app.connectors.base import BaseConnector, ConnectorResult, EscalationPayload

logger = structlog.get_logger(__name__)
_BASE = "https://api2.frontapp.com"


class FrontConnector(BaseConnector):
    async def handoff(self, payload: EscalationPayload) -> ConnectorResult:
        token = self.config.get("api_token", "")
        inbox_id = self.config.get("inbox_id", "")
        if not token or not inbox_id:
            return ConnectorResult(success=False, error="Front api_token and inbox_id are required")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        transcript = self._format_history(payload.history)
        body = (
            f"Escalation from AscenAI bot '{payload.agent_name}'.\n\n"
            f"Contact: {payload.contact_name or 'Unknown'}"
            + (f" | Phone: {payload.contact_phone}" if payload.contact_phone else "")
            + f"\nTrigger: {payload.trigger_message}\n\n"
            f"Transcript:\n{transcript}"
        )

        import_payload: dict = {
            "sender": {
                "name": payload.contact_name or "Visitor",
                "handle": payload.contact_email or f"visitor+{payload.session_id[:8]}@ascenai.noreply",
            },
            "to": [inbox_id],
            "subject": f"Live agent request — {payload.contact_name or 'visitor'} ({payload.agent_name})",
            "body": body,
            "type": "email",
            "created_at": None,  # now
            "metadata": {
                "is_inbound": True,
                "should_skip_rules": False,
            },
        }

        if self.config.get("assignee_id"):
            import_payload["assignee_id"] = self.config["assignee_id"]
        if self.config.get("tags"):
            import_payload["tags"] = self.config["tags"]

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_BASE}/inboxes/{inbox_id}/imported_messages",
                json=import_payload,
                headers=headers,
            )
            if resp.status_code not in (200, 201, 202):
                logger.error("front_import_message_failed", status=resp.status_code, body=resp.text[:300])
                return ConnectorResult(success=False, error=f"Front API {resp.status_code}: {resp.text[:200]}")

            data = resp.json()
            convo_id = data.get("conversation_reference", "")
            url = f"https://app.frontapp.com/open/{convo_id}" if convo_id else "https://app.frontapp.com"

            logger.info("front_handoff_success", convo_id=convo_id, session_id=payload.session_id)
            return ConnectorResult(success=True, ticket_id=convo_id, conversation_url=url, raw=data)
