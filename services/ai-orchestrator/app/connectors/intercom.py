"""
Intercom live-agent escalation connector.

Required connector_config keys:
  access_token  — Intercom access token (workspace or app token)

Optional connector_config keys:
  inbox_id      — Route to a specific Intercom inbox/team
  admin_id      — Assign to a specific admin ID
  tag_ids       — list[str] of tag IDs to apply to the conversation
"""
from __future__ import annotations

import structlog
import httpx

from app.connectors.base import BaseConnector, ConnectorResult, EscalationPayload

logger = structlog.get_logger(__name__)

_BASE = "https://api.intercom.io"
_HEADERS_BASE = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Intercom-Version": "2.11",
}


class IntercomConnector(BaseConnector):
    """
    Creates an Intercom conversation when a user is escalated.

    Flow:
      1. Upsert contact (by email or phone)
      2. Create conversation with transcript as first message
      3. Optionally assign to inbox / admin / tag
    """

    async def handoff(self, payload: EscalationPayload) -> ConnectorResult:
        token = self.config.get("access_token", "")
        if not token:
            return ConnectorResult(success=False, error="Intercom access_token not configured")

        headers = {**_HEADERS_BASE, "Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=15.0) as client:
            # 1. Upsert contact
            contact_id = await self._upsert_contact(client, headers, payload)

            # 2. Create conversation
            transcript = self._format_history(payload.history)
            body = (
                f"Escalation from AscenAI bot '{payload.agent_name}'.\n\n"
                f"**Conversation transcript:**\n{transcript}\n\n"
                f"**Trigger:** {payload.trigger_message}"
            )

            create_payload: dict = {
                "from": {"type": "contact", "id": contact_id},
                "body": body,
            }
            if self.config.get("inbox_id"):
                create_payload["inbox_id"] = self.config["inbox_id"]

            resp = await client.post(f"{_BASE}/conversations", json=create_payload, headers=headers)
            if resp.status_code not in (200, 201):
                logger.error("intercom_create_convo_failed", status=resp.status_code, body=resp.text[:300])
                return ConnectorResult(success=False, error=f"Intercom API {resp.status_code}: {resp.text[:200]}")

            data = resp.json()
            convo_id = data.get("id", "")

            # 3. Assign to admin if specified
            if self.config.get("admin_id") and convo_id:
                await self._assign(client, headers, convo_id)

            # 4. Apply tags if specified
            for tag_id in self.config.get("tag_ids", []):
                await self._tag(client, headers, convo_id, tag_id)

            url = f"https://app.intercom.com/a/inbox/{convo_id}"
            logger.info("intercom_handoff_success", conversation_id=convo_id, session_id=payload.session_id)
            return ConnectorResult(success=True, ticket_id=convo_id, conversation_url=url, raw=data)

    async def _upsert_contact(self, client: httpx.AsyncClient, headers: dict, payload: EscalationPayload) -> str:
        """Find or create an Intercom contact; returns the contact ID."""
        # Search by email first, then phone
        for field_type, value in [("email", payload.contact_email), ("phone", payload.contact_phone)]:
            if not value:
                continue
            resp = await client.post(
                f"{_BASE}/contacts/search",
                json={"query": {"field": field_type, "operator": "=", "value": value}},
                headers=headers,
            )
            if resp.status_code == 200:
                results = resp.json().get("data", [])
                if results:
                    return results[0]["id"]

        # Create new contact
        contact_data: dict = {"role": "lead", "name": payload.contact_name or "Unknown"}
        if payload.contact_email:
            contact_data["email"] = payload.contact_email
        if payload.contact_phone:
            contact_data["phone"] = payload.contact_phone

        resp = await client.post(f"{_BASE}/contacts", json=contact_data, headers=headers)
        resp.raise_for_status()
        return resp.json()["id"]

    async def _assign(self, client: httpx.AsyncClient, headers: dict, convo_id: str) -> None:
        admin_id = self.config.get("admin_id")
        await client.post(
            f"{_BASE}/conversations/{convo_id}/parts",
            json={"message_type": "assignment", "type": "admin", "assignee_id": admin_id},
            headers=headers,
        )

    async def _tag(self, client: httpx.AsyncClient, headers: dict, convo_id: str, tag_id: str) -> None:
        await client.post(
            f"{_BASE}/conversations/{convo_id}/tags",
            json={"id": tag_id},
            headers=headers,
        )
