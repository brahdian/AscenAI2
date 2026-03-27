"""
Freshchat live-agent escalation connector.

Required connector_config keys:
  api_key    — Freshchat API key
  domain     — your Freshchat domain (e.g. "acme.freshchat.com")

Optional connector_config keys:
  channel_id — assign conversation to a specific channel/inbox
  group_id   — route to a specific agent group
"""
from __future__ import annotations

import structlog
import httpx

from app.connectors.base import BaseConnector, ConnectorResult, EscalationPayload

logger = structlog.get_logger(__name__)


class FreshchatConnector(BaseConnector):
    """
    Opens a Freshchat conversation when a user is escalated.

    Flow:
      1. Create user (or lookup by email)
      2. Create conversation with transcript as initial message
    """

    async def handoff(self, payload: EscalationPayload) -> ConnectorResult:
        api_key = self.config.get("api_key", "")
        domain = self.config.get("domain", "")
        if not api_key or not domain:
            return ConnectorResult(success=False, error="Freshchat api_key and domain are required")

        base = f"https://{domain.rstrip('/')}/v2"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            # 1. Create or find user
            user_id = await self._get_or_create_user(client, headers, base, payload)

            # 2. Create conversation
            transcript = self._format_history(payload.history)
            first_message = (
                f"Escalated from AscenAI bot '{payload.agent_name}'.\n\n"
                f"Conversation transcript:\n{transcript}\n\n"
                f"Trigger: {payload.trigger_message}"
            )

            convo_payload: dict = {
                "channel_id": self.config.get("channel_id", ""),
                "users": [{"id": user_id}],
                "messages": [{
                    "message_type": "normal",
                    "message_parts": [{"text": {"content": first_message}}],
                    "actor_type": "system",
                }],
            }
            if self.config.get("group_id"):
                convo_payload["assigned_group_id"] = self.config["group_id"]

            resp = await client.post(f"{base}/conversations", json=convo_payload, headers=headers)
            if resp.status_code not in (200, 201):
                logger.error("freshchat_create_convo_failed", status=resp.status_code, body=resp.text[:300])
                return ConnectorResult(success=False, error=f"Freshchat API {resp.status_code}: {resp.text[:200]}")

            data = resp.json()
            convo_id = data.get("id", "")
            url = f"https://{domain}/a/conversations/{convo_id}"

            logger.info("freshchat_handoff_success", conversation_id=convo_id, session_id=payload.session_id)
            return ConnectorResult(success=True, ticket_id=convo_id, conversation_url=url, raw=data)

    async def _get_or_create_user(
        self,
        client: httpx.AsyncClient,
        headers: dict,
        base: str,
        payload: EscalationPayload,
    ) -> str:
        """Look up user by email or create a new one; returns user ID."""
        if payload.contact_email:
            resp = await client.get(
                f"{base}/users",
                params={"email": payload.contact_email},
                headers=headers,
            )
            if resp.status_code == 200:
                users = resp.json().get("users", [])
                if users:
                    return users[0]["id"]

        # Create
        user_data: dict = {
            "first_name": payload.contact_name or "Visitor",
            "phone": payload.contact_phone or "",
        }
        if payload.contact_email:
            user_data["email"] = payload.contact_email

        resp = await client.post(f"{base}/users", json=user_data, headers=headers)
        resp.raise_for_status()
        return resp.json()["id"]
