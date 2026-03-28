"""
Zendesk live-agent escalation connector.

Required connector_config keys:
  subdomain   — your Zendesk subdomain (e.g. "acme" for acme.zendesk.com)
  email       — agent/admin email for basic auth
  api_token   — Zendesk API token

Optional connector_config keys:
  group_id    — int: assign ticket to this group
  assignee_id — int: assign to a specific agent
  tags        — list[str]: ticket tags
  priority    — "low" | "normal" | "high" | "urgent"  (default: "normal")
"""
from __future__ import annotations

import structlog

from app.connectors.base import BaseConnector, ConnectorResult, EscalationPayload

logger = structlog.get_logger(__name__)


class ZendeskConnector(BaseConnector):
    """
    Creates a Zendesk ticket on escalation, including the full conversation
    transcript as the ticket body and requester info.
    """

    def _required_config_keys(self) -> list[str]:
        return ["subdomain", "email", "api_token"]

    async def handoff(self, payload: EscalationPayload) -> ConnectorResult:
        subdomain = self.config.get("subdomain", "")
        email = self.config.get("email", "")
        token = self.config.get("api_token", "")
        if not all([subdomain, email, token]):
            return ConnectorResult(success=False, error="Zendesk subdomain, email, and api_token are required")

        base = f"https://{subdomain}.zendesk.com/api/v2"
        auth = (f"{email}/token", token)

        transcript = self._format_history(payload.history)
        body = (
            f"This conversation was escalated from the AscenAI bot '{payload.agent_name}'.\n\n"
            f"**Conversation transcript:**\n\n{transcript}\n\n"
            f"**Escalation trigger:**\n{payload.trigger_message}"
        )

        ticket: dict = {
            "subject": f"Live agent request — {payload.contact_name or 'visitor'}",
            "comment": {"body": body},
            "priority": self.config.get("priority", "normal"),
            "tags": self.config.get("tags", ["ascenai-escalation"]),
        }

        # Requester
        requester: dict = {"name": payload.contact_name or "Visitor"}
        if payload.contact_email:
            requester["email"] = payload.contact_email
        ticket["requester"] = requester

        if self.config.get("group_id"):
            ticket["group_id"] = int(self.config["group_id"])
        if self.config.get("assignee_id"):
            ticket["assignee_id"] = int(self.config["assignee_id"])

        resp = await self._http_post(
            f"{base}/tickets.json",
            headers={},
            json={"ticket": ticket},
            auth=auth,
        )

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            logger.warning("connector_rate_limited", connector=self.__class__.__name__, retry_after=retry_after)
            return ConnectorResult(success=False, error=f"Rate limited. Retry after {retry_after}s")

        if resp.status_code not in (200, 201):
            logger.error("zendesk_create_ticket_failed", status=resp.status_code, body=self._scrub_pii(resp.text))
            return ConnectorResult(success=False, error=f"Zendesk API {resp.status_code}: {self._scrub_pii(resp.text)}")

        data = resp.json().get("ticket", {})
        ticket_id = str(data.get("id", ""))
        url = f"https://{subdomain}.zendesk.com/agent/tickets/{ticket_id}"

        logger.info("zendesk_handoff_success", ticket_id=ticket_id, session_id=payload.session_id)
        return ConnectorResult(success=True, ticket_id=ticket_id, conversation_url=url, raw=data)
