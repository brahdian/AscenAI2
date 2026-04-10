"""
LiveChat live-agent escalation connector.

Creates a LiveChat ticket so the support team can see the escalation.

Required connector_config keys:
  login       — LiveChat agent login (email)
  api_key     — LiveChat API key (from Agent API settings)

Optional connector_config keys:
  group_id    — route to a specific group (integer)
  tags        — list[str]: ticket tags
"""
from __future__ import annotations

import structlog

from app.connectors.base import BaseConnector, ConnectorResult, EscalationPayload

logger = structlog.get_logger(__name__)
_BASE = "https://api.livechatinc.com"


class LiveChatConnector(BaseConnector):

    def _required_config_keys(self) -> list[str]:
        return ["login", "api_key"]

    async def handoff(self, payload: EscalationPayload) -> ConnectorResult:
        login = self.config.get("login", "")
        api_key = self.config.get("api_key", "")
        if not login or not api_key:
            return ConnectorResult(success=False, error="LiveChat login and api_key are required")

        auth = (login, api_key)
        headers = {
            "Content-Type": "application/json",
            "X-API-Version": "2",
        }

        transcript = self._format_history(payload.history)
        message = (
            f"Escalation from AscenAI bot '{payload.agent_name}'.\n\n"
            f"Contact: {payload.contact_name or 'Unknown'}"
            + (f"  |  Phone: {payload.contact_phone}" if payload.contact_phone else "")
            + (f"  |  Email: {payload.contact_email}" if payload.contact_email else "")
            + f"\nTrigger: {payload.trigger_message}\n\n"
            f"Transcript:\n{transcript}"
        )

        ticket: dict = {
            "subject": f"Escalation: {payload.contact_name or 'visitor'} via {payload.agent_name}",
            "message": message,
        }
        if payload.contact_email:
            ticket["requester_mail"] = payload.contact_email
        if payload.contact_name:
            ticket["requester_name"] = payload.contact_name

        tags = self.config.get("tags", [])
        if tags:
            ticket["tags"] = tags

        resp = await self._http_post(f"{_BASE}/tickets", headers=headers, json=ticket, auth=auth)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            logger.warning("connector_rate_limited", connector=self.__class__.__name__, retry_after=retry_after)
            return ConnectorResult(success=False, error=f"Rate limited. Retry after {retry_after}s")

        if resp.status_code not in (200, 201):
            logger.error("livechat_create_ticket_failed", status=resp.status_code, body=self._scrub_pii(resp.text))
            return ConnectorResult(success=False, error=f"LiveChat API {resp.status_code}: {self._scrub_pii(resp.text)}")

        data = resp.json()
        ticket_id = str(data.get("id", ""))
        url = f"https://my.livechat.com/tickets/{ticket_id}"

        logger.info("livechat_handoff_success", ticket_id=ticket_id, session_id=payload.session_id)
        return ConnectorResult(success=True, ticket_id=ticket_id, conversation_url=url, raw=data)
