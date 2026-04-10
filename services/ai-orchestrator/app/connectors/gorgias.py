"""
Gorgias live-agent escalation connector.
Popular with Canadian Shopify merchants (Shopify = Canadian company).

Creates a Gorgias ticket with the full conversation transcript.

Required connector_config keys:
  domain        — your Gorgias subdomain (e.g. "acme" for acme.gorgias.com)
  email         — agent email for Basic Auth
  api_key       — Gorgias API key (from REST API settings)

Optional connector_config keys:
  assignee_user_id  — assign to a specific agent user ID
  team_id           — assign to a specific team ID
  tags              — list[str]: ticket tags
  channel           — "email" | "chat" | "api" (default: "api")
"""
from __future__ import annotations

import structlog

from app.connectors.base import BaseConnector, ConnectorResult, EscalationPayload

logger = structlog.get_logger(__name__)


class GorgiasConnector(BaseConnector):

    def _required_config_keys(self) -> list[str]:
        return ["domain", "email", "api_key"]

    async def handoff(self, payload: EscalationPayload) -> ConnectorResult:
        domain = self.config.get("domain", "")
        email = self.config.get("email", "")
        api_key = self.config.get("api_key", "")
        if not all([domain, email, api_key]):
            return ConnectorResult(success=False, error="Gorgias domain, email, and api_key are required")

        base = f"https://{domain}.gorgias.com/api"
        auth = (email, api_key)

        transcript = self._format_history(payload.history)
        channel = self.config.get("channel", "api")

        # Gorgias structures tickets with messages
        body_text = (
            f"Escalation from AscenAI bot '{payload.agent_name}'.\n\n"
            f"Contact: {payload.contact_name or 'Unknown'}"
            + (f" | Phone: {payload.contact_phone}" if payload.contact_phone else "")
            + (f" | Email: {payload.contact_email}" if payload.contact_email else "")
            + f"\nTrigger: {payload.trigger_message}\n\n"
            f"Conversation Transcript:\n{transcript}"
        )

        ticket: dict = {
            "channel": channel,
            "via": channel,
            "subject": f"Live agent request — {payload.contact_name or 'visitor'} ({payload.agent_name})",
            "messages": [{
                "channel": channel,
                "via": channel,
                "from_agent": False,
                "body_text": body_text,
                "body_html": f"<pre>{body_text}</pre>",
                "sender": {
                    "name": payload.contact_name or "Visitor",
                    "email": payload.contact_email or f"visitor+{payload.session_id[:8]}@ascenai.noreply",
                },
            }],
        }

        if payload.contact_email:
            ticket["requester_email"] = payload.contact_email

        if self.config.get("assignee_user_id"):
            ticket["assignee_user"] = {"id": int(self.config["assignee_user_id"])}
        if self.config.get("team_id"):
            ticket["assignee_team"] = {"id": int(self.config["team_id"])}

        tags = self.config.get("tags", [])
        if tags:
            ticket["tags"] = [{"name": t} for t in tags]

        resp = await self._http_post(f"{base}/tickets", headers={}, json=ticket, auth=auth)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            logger.warning("connector_rate_limited", connector=self.__class__.__name__, retry_after=retry_after)
            return ConnectorResult(success=False, error=f"Rate limited. Retry after {retry_after}s")

        if resp.status_code not in (200, 201):
            logger.error("gorgias_create_ticket_failed", status=resp.status_code, body=self._scrub_pii(resp.text))
            return ConnectorResult(success=False, error=f"Gorgias API {resp.status_code}: {self._scrub_pii(resp.text)}")

        data = resp.json()
        ticket_id = str(data.get("id", ""))
        url = f"https://{domain}.gorgias.com/app/ticket/{ticket_id}"

        logger.info("gorgias_handoff_success", ticket_id=ticket_id, session_id=payload.session_id)
        return ConnectorResult(success=True, ticket_id=ticket_id, conversation_url=url, raw=data)
