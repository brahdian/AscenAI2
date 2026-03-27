"""
HubSpot live-agent escalation connector.

Creates a HubSpot Ticket and optionally a Contact, then opens a Conversation
so a sales/support rep sees the escalation immediately in their inbox.

Required connector_config keys:
  access_token   — HubSpot Private App access token

Optional connector_config keys:
  pipeline_id    — ticket pipeline ID (default: "0" = Support Pipeline)
  stage_id       — pipeline stage ID (default: "1" = New)
  owner_id       — assign to a specific HubSpot user ID
  priority       — "LOW" | "MEDIUM" | "HIGH" | "URGENT" (default: "MEDIUM")
"""
from __future__ import annotations

import structlog
import httpx

from app.connectors.base import BaseConnector, ConnectorResult, EscalationPayload

logger = structlog.get_logger(__name__)
_BASE = "https://api.hubapi.com"


class HubSpotConnector(BaseConnector):
    """
    Creates a HubSpot Ticket (CRM object) on escalation with the full
    conversation transcript as the ticket body.
    """

    async def handoff(self, payload: EscalationPayload) -> ConnectorResult:
        token = self.config.get("access_token", "")
        if not token:
            return ConnectorResult(success=False, error="HubSpot access_token not configured")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        transcript = self._format_history(payload.history)
        body_text = (
            f"Escalation from AscenAI bot '{payload.agent_name}'.\n\n"
            f"Contact: {payload.contact_name or 'Unknown'}"
            + (f"  |  {payload.contact_phone}" if payload.contact_phone else "")
            + (f"  |  {payload.contact_email}" if payload.contact_email else "")
            + f"\n\nTrigger: {payload.trigger_message}\n\n"
            f"Conversation transcript:\n{transcript}"
        )

        ticket_props: dict = {
            "subject": f"Live agent request — {payload.contact_name or 'visitor'} ({payload.agent_name})",
            "content": body_text,
            "hs_ticket_priority": self.config.get("priority", "MEDIUM"),
            "hs_pipeline": self.config.get("pipeline_id", "0"),
            "hs_pipeline_stage": self.config.get("stage_id", "1"),
        }
        if self.config.get("owner_id"):
            ticket_props["hubspot_owner_id"] = self.config["owner_id"]

        async with httpx.AsyncClient(timeout=15.0) as client:
            # 1. Create ticket
            resp = await client.post(
                f"{_BASE}/crm/v3/objects/tickets",
                json={"properties": ticket_props},
                headers=headers,
            )
            if resp.status_code not in (200, 201):
                logger.error("hubspot_create_ticket_failed", status=resp.status_code, body=resp.text[:300])
                return ConnectorResult(success=False, error=f"HubSpot API {resp.status_code}: {resp.text[:200]}")

            ticket = resp.json()
            ticket_id = ticket.get("id", "")

            # 2. Associate contact if email provided
            if payload.contact_email and ticket_id:
                contact_id = await self._upsert_contact(client, headers, payload)
                if contact_id:
                    await client.put(
                        f"{_BASE}/crm/v3/objects/tickets/{ticket_id}/associations/contacts/{contact_id}/ticket_to_contact",
                        headers=headers,
                    )

        url = f"https://app.hubspot.com/contacts/tickets/{ticket_id}"
        logger.info("hubspot_handoff_success", ticket_id=ticket_id, session_id=payload.session_id)
        return ConnectorResult(success=True, ticket_id=ticket_id, conversation_url=url, raw=ticket)

    async def _upsert_contact(
        self, client: httpx.AsyncClient, headers: dict, payload: EscalationPayload
    ) -> str:
        """Find or create a HubSpot contact by email; return contact ID."""
        if not payload.contact_email:
            return ""
        try:
            resp = await client.post(
                f"{_BASE}/crm/v3/objects/contacts/search",
                json={"filterGroups": [{"filters": [
                    {"propertyName": "email", "operator": "EQ", "value": payload.contact_email}
                ]}]},
                headers=headers,
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    return results[0]["id"]

            # Create
            props: dict = {"email": payload.contact_email}
            if payload.contact_name:
                parts = payload.contact_name.split(" ", 1)
                props["firstname"] = parts[0]
                if len(parts) > 1:
                    props["lastname"] = parts[1]
            if payload.contact_phone:
                props["phone"] = payload.contact_phone

            r = await client.post(
                f"{_BASE}/crm/v3/objects/contacts",
                json={"properties": props},
                headers=headers,
            )
            r.raise_for_status()
            return r.json().get("id", "")
        except Exception as exc:
            logger.warning("hubspot_contact_upsert_failed", error=str(exc))
            return ""
