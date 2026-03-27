"""
Zoho Desk live-agent escalation connector.

Creates a Zoho Desk ticket with the conversation transcript.

Required connector_config keys:
  access_token  — Zoho OAuth 2.0 access token
  org_id        — your Zoho Desk organization ID

Optional connector_config keys:
  department_id — route to a specific department
  assignee_id   — assign to a specific agent ID
  priority      — "Low" | "Medium" | "High" | "Urgent" (default: "Medium")
  tld           — Zoho TLD: "com" | "eu" | "com.au" | "in" (default: "com")
  category      — ticket category string
"""
from __future__ import annotations

import structlog
import httpx

from app.connectors.base import BaseConnector, ConnectorResult, EscalationPayload

logger = structlog.get_logger(__name__)


class ZohoDeskConnector(BaseConnector):
    async def handoff(self, payload: EscalationPayload) -> ConnectorResult:
        token = self.config.get("access_token", "")
        org_id = self.config.get("org_id", "")
        if not token or not org_id:
            return ConnectorResult(success=False, error="Zoho Desk access_token and org_id are required")

        tld = self.config.get("tld", "com")
        base = f"https://desk.zoho.{tld}/api/v1"
        headers = {
            "Authorization": f"Zoho-oauthtoken {token}",
            "orgId": str(org_id),
            "Content-Type": "application/json",
        }

        transcript = self._format_history(payload.history)
        description = (
            f"Escalation from AscenAI bot '{payload.agent_name}'.\n\n"
            f"Contact: {payload.contact_name or 'Unknown'}"
            + (f" | Phone: {payload.contact_phone}" if payload.contact_phone else "")
            + (f" | Email: {payload.contact_email}" if payload.contact_email else "")
            + f"\n\nTrigger: {payload.trigger_message}\n\n"
            f"Conversation Transcript:\n{transcript}"
        )

        ticket: dict = {
            "subject": f"Live agent request — {payload.contact_name or 'visitor'} ({payload.agent_name})",
            "description": description,
            "priority": self.config.get("priority", "Medium"),
            "status": "Open",
            "channel": "Web",
        }

        if payload.contact_email:
            ticket["contactId"] = await self._get_or_create_contact(
                httpx.AsyncClient(timeout=15.0), headers, base, payload
            )
        if payload.contact_name and not payload.contact_email:
            ticket["contactId"] = ""

        if self.config.get("department_id"):
            ticket["departmentId"] = str(self.config["department_id"])
        if self.config.get("assignee_id"):
            ticket["assigneeId"] = str(self.config["assignee_id"])
        if self.config.get("category"):
            ticket["category"] = self.config["category"]

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{base}/tickets", json=ticket, headers=headers)
            if resp.status_code not in (200, 201):
                logger.error("zoho_desk_create_ticket_failed", status=resp.status_code, body=resp.text[:300])
                return ConnectorResult(success=False, error=f"Zoho Desk API {resp.status_code}: {resp.text[:200]}")

            data = resp.json()
            ticket_id = str(data.get("id", ""))
            url = f"https://desk.zoho.{tld}/agent/ascenai/tickets/{ticket_id}"

            logger.info("zoho_desk_handoff_success", ticket_id=ticket_id, session_id=payload.session_id)
            return ConnectorResult(success=True, ticket_id=ticket_id, conversation_url=url, raw=data)

    async def _get_or_create_contact(
        self, client: httpx.AsyncClient, headers: dict, base: str, payload: EscalationPayload
    ) -> str:
        try:
            resp = await client.get(
                f"{base}/contacts/search",
                params={"email": payload.contact_email},
                headers=headers,
            )
            if resp.status_code == 200:
                items = resp.json().get("data", [])
                if items:
                    return items[0]["id"]

            # Create new contact
            contact: dict = {"email": payload.contact_email}
            if payload.contact_name:
                parts = payload.contact_name.split(" ", 1)
                contact["firstName"] = parts[0]
                if len(parts) > 1:
                    contact["lastName"] = parts[1]
            if payload.contact_phone:
                contact["phone"] = payload.contact_phone

            r = await client.post(f"{base}/contacts", json=contact, headers=headers)
            r.raise_for_status()
            return r.json().get("id", "")
        except Exception as exc:
            logger.warning("zoho_desk_contact_upsert_failed", error=str(exc))
            return ""
