"""
Re:amaze live-agent escalation connector.
Popular with Canadian ecommerce SMBs.

Creates a Re:amaze conversation with the transcript.

Required connector_config keys:
  brand         — your Re:amaze brand/subdomain (e.g. "acme" for acme.reamaze.com)
  email         — agent email
  api_token     — Re:amaze API token (from Settings → API)

Optional connector_config keys:
  channel_slug  — channel identifier to route to (default: first available)
  assignee_id   — assign to a specific staff member ID
  tags          — list[str]: conversation tags
"""
from __future__ import annotations

import structlog
import httpx

from app.connectors.base import BaseConnector, ConnectorResult, EscalationPayload

logger = structlog.get_logger(__name__)


class ReamazeConnector(BaseConnector):
    async def handoff(self, payload: EscalationPayload) -> ConnectorResult:
        brand = self.config.get("brand", "")
        email = self.config.get("email", "")
        token = self.config.get("api_token", "")
        if not all([brand, email, token]):
            return ConnectorResult(success=False, error="Re:amaze brand, email, and api_token are required")

        base = f"https://{brand}.reamaze.com/api/v1"
        auth = (email, token)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        transcript = self._format_history(payload.history)
        message_body = (
            f"Escalation from AscenAI bot '{payload.agent_name}'.\n\n"
            f"Trigger: {payload.trigger_message}\n\n"
            f"Transcript:\n{transcript}"
        )

        convo: dict = {
            "conversation": {
                "subject": f"Live agent request — {payload.contact_name or 'visitor'} ({payload.agent_name})",
                "message": {"body": message_body},
                "contact": {
                    "name": payload.contact_name or "Visitor",
                },
            }
        }

        if payload.contact_email:
            convo["conversation"]["contact"]["email"] = payload.contact_email
        else:
            convo["conversation"]["contact"]["email"] = (
                f"visitor+{payload.session_id[:8]}@ascenai.noreply"
            )

        if self.config.get("channel_slug"):
            convo["conversation"]["channel_slug"] = self.config["channel_slug"]
        if self.config.get("assignee_id"):
            convo["conversation"]["user_id"] = self.config["assignee_id"]
        if self.config.get("tags"):
            convo["conversation"]["tag_list"] = ",".join(self.config["tags"])

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{base}/conversations", json=convo, auth=auth, headers=headers)
            if resp.status_code not in (200, 201):
                logger.error("reamaze_create_convo_failed", status=resp.status_code, body=resp.text[:300])
                return ConnectorResult(success=False, error=f"Re:amaze API {resp.status_code}: {resp.text[:200]}")

            data = resp.json()
            slug = data.get("slug", "")
            url = f"https://{brand}.reamaze.com/conversations/{slug}" if slug else ""

            logger.info("reamaze_handoff_success", slug=slug, session_id=payload.session_id)
            return ConnectorResult(success=True, ticket_id=slug, conversation_url=url, raw=data)
