"""
LiveAgent live-agent escalation connector.

Creates a LiveAgent ticket.

Required connector_config keys:
  account       — your LiveAgent subdomain (e.g. "acme" for acme.ladesk.com)
  api_key       — LiveAgent API key (from Configuration → API)

Optional connector_config keys:
  department_id — route to a specific department
  owner_id      — assign to a specific agent
  tags          — list[str]: ticket tags
  priority      — "normal" | "high" | "low" (default: "normal")
"""
from __future__ import annotations

import structlog
import httpx

from app.connectors.base import BaseConnector, ConnectorResult, EscalationPayload

logger = structlog.get_logger(__name__)


class LiveAgentConnector(BaseConnector):
    async def handoff(self, payload: EscalationPayload) -> ConnectorResult:
        account = self.config.get("account", "")
        api_key = self.config.get("api_key", "")
        if not account or not api_key:
            return ConnectorResult(success=False, error="LiveAgent account and api_key are required")

        base = f"https://{account}.ladesk.com/api/v3"
        headers = {
            "apikey": api_key,
            "Content-Type": "application/json",
        }

        transcript = self._format_history(payload.history)
        message = (
            f"Escalation from AscenAI bot '{payload.agent_name}'.\n\n"
            f"Contact: {payload.contact_name or 'Unknown'}"
            + (f" | Phone: {payload.contact_phone}" if payload.contact_phone else "")
            + (f" | Email: {payload.contact_email}" if payload.contact_email else "")
            + f"\nTrigger: {payload.trigger_message}\n\n"
            f"Transcript:\n{transcript}"
        )

        ticket: dict = {
            "subject": f"Live agent request — {payload.contact_name or 'visitor'} ({payload.agent_name})",
            "status": "I",  # Incoming/New
            "priority": self.config.get("priority", "normal"),
            "messages": [{"type": "I", "message": message}],
        }

        if payload.contact_email:
            ticket["useridentifier"] = payload.contact_email
        if self.config.get("department_id"):
            ticket["departmentid"] = self.config["department_id"]
        if self.config.get("owner_id"):
            ticket["ownerid"] = self.config["owner_id"]

        tags = self.config.get("tags", [])
        if tags:
            ticket["tags"] = tags

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{base}/tickets", json=ticket, headers=headers)
            if resp.status_code not in (200, 201):
                logger.error("liveagent_create_ticket_failed", status=resp.status_code, body=resp.text[:300])
                return ConnectorResult(success=False, error=f"LiveAgent API {resp.status_code}: {resp.text[:200]}")

            data = resp.json()
            ticket_id = str(data.get("id", ""))
            url = f"https://{account}.ladesk.com/tickets/detail/{ticket_id}"

            logger.info("liveagent_handoff_success", ticket_id=ticket_id, session_id=payload.session_id)
            return ConnectorResult(success=True, ticket_id=ticket_id, conversation_url=url, raw=data)
