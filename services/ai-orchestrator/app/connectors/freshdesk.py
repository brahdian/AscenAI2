"""
Freshdesk live-agent escalation connector.

Creates a Freshdesk ticket with the full conversation transcript.
Note: separate from Freshchat (freshchat.py) — Freshdesk is the ticketing product.

Required connector_config keys:
  domain      — your Freshdesk subdomain (e.g. "acme" for acme.freshdesk.com)
  api_key     — Freshdesk API key (from Profile Settings)

Optional connector_config keys:
  priority    — 1=Low 2=Medium 3=High 4=Urgent  (default: 2)
  status      — 2=Open 3=Pending 4=Resolved 5=Closed  (default: 2)
  group_id    — assign to a specific support group ID
  type        — "Question" | "Incident" | "Problem" | "Feature Request" (default: "Question")
  tags        — list[str]: ticket tags
"""
from __future__ import annotations

import structlog

from app.connectors.base import BaseConnector, ConnectorResult, EscalationPayload

logger = structlog.get_logger(__name__)


class FreshdeskConnector(BaseConnector):

    def _required_config_keys(self) -> list[str]:
        return ["domain", "api_key"]

    async def handoff(self, payload: EscalationPayload) -> ConnectorResult:
        domain = self.config.get("domain", "")
        api_key = self.config.get("api_key", "")
        if not domain or not api_key:
            return ConnectorResult(success=False, error="Freshdesk domain and api_key are required")

        base = f"https://{domain}.freshdesk.com/api/v2"
        # Freshdesk uses Basic Auth with API key as username, "X" as password
        auth = (api_key, "X")

        transcript = self._format_history(payload.history)
        description = (
            f"<p><strong>Escalation from AscenAI bot '{payload.agent_name}'</strong></p>"
            f"<p>Contact: {payload.contact_name or 'Unknown'}"
            + (f" | {payload.contact_phone}" if payload.contact_phone else "")
            + f"</p>"
            f"<p><strong>Trigger:</strong> {payload.trigger_message}</p>"
            f"<hr/><p><strong>Conversation Transcript:</strong></p>"
            f"<pre>{transcript}</pre>"
        )

        ticket: dict = {
            "subject": f"Live agent request — {payload.contact_name or 'visitor'} via {payload.agent_name}",
            "description": description,
            "priority": int(self.config.get("priority", 2)),
            "status": int(self.config.get("status", 2)),
            "type": self.config.get("type", "Question"),
            "tags": self.config.get("tags", ["ascenai-escalation"]),
            "source": 2,  # Portal (web)
        }

        # Requester — email required by Freshdesk
        if payload.contact_email:
            ticket["email"] = payload.contact_email
        elif payload.contact_phone:
            ticket["phone"] = payload.contact_phone
        else:
            ticket["name"] = payload.contact_name or "AscenAI Escalation"

        if payload.contact_name:
            ticket["name"] = payload.contact_name

        if self.config.get("group_id"):
            ticket["group_id"] = int(self.config["group_id"])

        resp = await self._http_post(f"{base}/tickets", headers={}, json=ticket, auth=auth)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            logger.warning("connector_rate_limited", connector=self.__class__.__name__, retry_after=retry_after)
            return ConnectorResult(success=False, error=f"Rate limited. Retry after {retry_after}s")

        if resp.status_code not in (200, 201):
            logger.error("freshdesk_create_ticket_failed", status=resp.status_code, body=self._scrub_pii(resp.text))
            return ConnectorResult(success=False, error=f"Freshdesk API {resp.status_code}: {self._scrub_pii(resp.text)}")

        data = resp.json()
        ticket_id = str(data.get("id", ""))
        url = f"https://{domain}.freshdesk.com/helpdesk/tickets/{ticket_id}"

        logger.info("freshdesk_handoff_success", ticket_id=ticket_id, session_id=payload.session_id)
        return ConnectorResult(success=True, ticket_id=ticket_id, conversation_url=url, raw=data)
