"""
Help Scout live-agent escalation connector.

Creates a Help Scout conversation in a mailbox.

Required connector_config keys:
  app_id      — Help Scout OAuth app ID (Client ID)
  app_secret  — Help Scout OAuth app secret (Client Secret)
  mailbox_id  — integer mailbox ID to route the conversation to

Optional connector_config keys:
  assigned_to — user ID of the agent to assign to
  tags        — list[str]: conversation tags
  status      — "active" | "pending" (default: "active")
"""
from __future__ import annotations

import structlog
import httpx

from app.connectors.base import BaseConnector, ConnectorResult, EscalationPayload

logger = structlog.get_logger(__name__)
_BASE = "https://api.helpscout.net/v2"
_TOKEN_URL = "https://api.helpscout.net/v2/auth/token"


class HelpScoutConnector(BaseConnector):
    _token: str | None = None

    async def handoff(self, payload: EscalationPayload) -> ConnectorResult:
        app_id = self.config.get("app_id", "")
        app_secret = self.config.get("app_secret", "")
        mailbox_id = self.config.get("mailbox_id")
        if not app_id or not app_secret or not mailbox_id:
            return ConnectorResult(success=False, error="Help Scout app_id, app_secret, and mailbox_id are required")

        async with httpx.AsyncClient(timeout=15.0) as client:
            token = await self._get_token(client, app_id, app_secret)
            if not token:
                return ConnectorResult(success=False, error="Failed to obtain Help Scout access token")

            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

            transcript = self._format_history(payload.history)
            body_text = (
                f"Escalation from AscenAI bot '{payload.agent_name}'.\n\n"
                f"Contact: {payload.contact_name or 'Unknown'}"
                + (f" | Phone: {payload.contact_phone}" if payload.contact_phone else "")
                + f"\nTrigger: {payload.trigger_message}\n\n"
                f"Conversation Transcript:\n{transcript}"
            )

            convo: dict = {
                "subject": f"Live agent request — {payload.contact_name or 'visitor'} ({payload.agent_name})",
                "mailboxId": int(mailbox_id),
                "type": "email",
                "status": self.config.get("status", "active"),
                "customer": {},
                "threads": [{
                    "type": "customer",
                    "customer": {},
                    "text": body_text,
                }],
            }

            # Customer
            if payload.contact_email:
                convo["customer"]["email"] = payload.contact_email
                convo["threads"][0]["customer"]["email"] = payload.contact_email
            if payload.contact_name:
                convo["customer"]["firstName"] = payload.contact_name.split(" ")[0]
                convo["threads"][0]["customer"]["firstName"] = payload.contact_name.split(" ")[0]

            if self.config.get("assigned_to"):
                convo["assignTo"] = int(self.config["assigned_to"])
            if self.config.get("tags"):
                convo["tags"] = self.config["tags"]

            resp = await client.post(f"{_BASE}/conversations", json=convo, headers=headers)
            if resp.status_code not in (200, 201):
                logger.error("helpscout_create_convo_failed", status=resp.status_code, body=resp.text[:300])
                return ConnectorResult(success=False, error=f"Help Scout API {resp.status_code}: {resp.text[:200]}")

            # Help Scout returns Location header with the conversation URL
            location = resp.headers.get("Location", "")
            convo_id = location.split("/")[-1] if location else ""
            url = f"https://secure.helpscout.net/conversation/{convo_id}" if convo_id else ""

            logger.info("helpscout_handoff_success", convo_id=convo_id, session_id=payload.session_id)
            return ConnectorResult(success=True, ticket_id=convo_id, conversation_url=url)

    async def _get_token(self, client: httpx.AsyncClient, app_id: str, app_secret: str) -> str:
        resp = await client.post(
            _TOKEN_URL,
            data={"grant_type": "client_credentials", "client_id": app_id, "client_secret": app_secret},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code == 200:
            return resp.json().get("access_token", "")
        logger.error("helpscout_token_failed", status=resp.status_code, body=resp.text[:200])
        return ""
