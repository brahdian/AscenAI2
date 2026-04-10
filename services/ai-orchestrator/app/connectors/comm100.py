"""
Comm100 live-agent escalation connector.
Canadian company (Vancouver, BC) — popular with Canadian businesses.

Creates a Comm100 ticket via their REST API v3.

Required connector_config keys:
  access_token  — Comm100 JWT access token (from Comm100 → Agent Console → API)
  site_id       — your Comm100 site ID (integer)

Optional connector_config keys:
  department_id — route to a specific department ID
  assignee_id   — assign to a specific agent ID
  tags          — list[str]: ticket tags
  priority      — "urgent" | "high" | "normal" | "low" (default: "normal")
"""
from __future__ import annotations

import structlog
import httpx

from app.connectors.base import BaseConnector, ConnectorResult, EscalationPayload

logger = structlog.get_logger(__name__)
_BASE = "https://api1.comm100.io/api/v3"


class Comm100Connector(BaseConnector):
    async def handoff(self, payload: EscalationPayload) -> ConnectorResult:
        token = self.config.get("access_token", "")
        site_id = self.config.get("site_id")
        if not token or not site_id:
            return ConnectorResult(success=False, error="Comm100 access_token and site_id are required")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "siteId": str(site_id),
        }

        transcript = self._format_history(payload.history)
        message = (
            f"Escalation from AscenAI bot '{payload.agent_name}'.\n\n"
            f"Contact: {payload.contact_name or 'Unknown'}"
            + (f" | Phone: {payload.contact_phone}" if payload.contact_phone else "")
            + (f" | Email: {payload.contact_email}" if payload.contact_email else "")
            + f"\nTrigger: {payload.trigger_message}\n\nTranscript:\n{transcript}"
        )

        ticket: dict = {
            "subject": f"Live agent request — {payload.contact_name or 'visitor'} ({payload.agent_name})",
            "firstMessage": message,
            "source": "API",
            "contactIdentity": {
                "type": payload.contact_email and "email" or "visitor",
                "value": payload.contact_email or payload.session_id,
                "name": payload.contact_name or "Visitor",
            },
            "priority": self.config.get("priority", "normal"),
        }

        if self.config.get("department_id"):
            ticket["departmentId"] = self.config["department_id"]
        if self.config.get("assignee_id"):
            ticket["agentId"] = self.config["assignee_id"]
        if self.config.get("tags"):
            ticket["tagIds"] = self.config["tags"]

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{_BASE}/tickets", json=ticket, headers=headers)
            if resp.status_code not in (200, 201):
                logger.error("comm100_create_ticket_failed", status=resp.status_code, body=resp.text[:300])
                return ConnectorResult(success=False, error=f"Comm100 API {resp.status_code}: {resp.text[:200]}")

            data = resp.json()
            ticket_id = str(data.get("id", ""))
            url = f"https://app.comm100.com/tickets/{ticket_id}"

            logger.info("comm100_handoff_success", ticket_id=ticket_id, session_id=payload.session_id)
            return ConnectorResult(success=True, ticket_id=ticket_id, conversation_url=url, raw=data)
