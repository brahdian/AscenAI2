"""
Crisp live-agent escalation connector.

Opens a Crisp conversation in a website inbox.

Required connector_config keys:
  website_id    — Crisp website ID (UUID)
  identifier    — Crisp Plugin/API identifier (from dashboard → API)
  key           — Crisp Plugin/API key

Optional connector_config keys:
  assign_to     — operator ID to assign the conversation to
  segment       — conversation segment / tag string
"""
from __future__ import annotations

import structlog
import httpx

from app.connectors.base import BaseConnector, ConnectorResult, EscalationPayload

logger = structlog.get_logger(__name__)
_BASE = "https://api.crisp.chat/v1"


class CrispConnector(BaseConnector):
    async def handoff(self, payload: EscalationPayload) -> ConnectorResult:
        website_id = self.config.get("website_id", "")
        identifier = self.config.get("identifier", "")
        key = self.config.get("key", "")
        if not all([website_id, identifier, key]):
            return ConnectorResult(success=False, error="Crisp website_id, identifier, and key are required")

        # Crisp uses Basic Auth with identifier:key
        auth = (identifier, key)
        headers = {
            "X-Crisp-Tier": "plugin",
            "Content-Type": "application/json",
        }

        transcript = self._format_history(payload.history)

        async with httpx.AsyncClient(timeout=15.0) as client:
            # 1. Create conversation
            resp = await client.post(
                f"{_BASE}/website/{website_id}/conversation",
                json={},
                auth=auth,
                headers=headers,
            )
            if resp.status_code not in (200, 201):
                logger.error("crisp_create_convo_failed", status=resp.status_code, body=resp.text[:300])
                return ConnectorResult(success=False, error=f"Crisp API {resp.status_code}: {resp.text[:200]}")

            convo_id = resp.json().get("data", {}).get("session_id", "")
            if not convo_id:
                return ConnectorResult(success=False, error="Crisp did not return a session_id")

            # 2. Update meta (contact info)
            meta: dict = {}
            if payload.contact_name:
                meta["nickname"] = payload.contact_name
            if payload.contact_email:
                meta["email"] = payload.contact_email
            if payload.contact_phone:
                meta["phone"] = payload.contact_phone

            if meta:
                await client.patch(
                    f"{_BASE}/website/{website_id}/conversation/{convo_id}/meta",
                    json=meta, auth=auth, headers=headers,
                )

            # 3. Post transcript as note
            note = (
                f"Escalation from AscenAI bot '{payload.agent_name}'.\n"
                f"Trigger: {payload.trigger_message}\n\n"
                f"Transcript:\n{transcript}"
            )
            await client.post(
                f"{_BASE}/website/{website_id}/conversation/{convo_id}/message",
                json={"type": "note", "from": "operator", "origin": "chat", "content": note},
                auth=auth, headers=headers,
            )

            # 4. Assign operator if configured
            if self.config.get("assign_to"):
                await client.patch(
                    f"{_BASE}/website/{website_id}/conversation/{convo_id}/routing",
                    json={"assigned": {"operator_id": self.config["assign_to"]}},
                    auth=auth, headers=headers,
                )

            url = f"https://app.crisp.chat/website/{website_id}/inbox/{convo_id}/"
            logger.info("crisp_handoff_success", convo_id=convo_id, session_id=payload.session_id)
            return ConnectorResult(success=True, ticket_id=convo_id, conversation_url=url)
