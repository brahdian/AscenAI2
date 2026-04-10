"""
tawk.to live-agent escalation connector.
World's most-used live chat (~35% of all sites with live chat).

tawk.to does not expose a REST API for creating conversations from outside
the widget. This connector works by:
  1. Firing a webhook notification (if configured via tawk.to Property Settings
     → Integrations → Webhooks → add a "chat started" action webhook)
  2. Notifying via email if smtp is configured on the tenant

To use:
  - In tawk.to dashboard: Settings → Account → REST API to get your API key
  - In tawk.to dashboard: Property Settings → Notifications → Email to set up
    agent email notifications (tawk.to will email your team automatically)

Required connector_config keys:
  webhook_url   — URL to POST the escalation payload to; set this to any
                  HTTPS endpoint your team monitors, or use tawk.to's Zapier
                  integration as a bridge

Optional connector_config keys:
  property_id   — tawk.to property ID (for reference / logging)
"""
from __future__ import annotations

import json
import time
import structlog
import httpx

from app.connectors.base import BaseConnector, ConnectorResult, EscalationPayload

logger = structlog.get_logger(__name__)


class TawkToConnector(BaseConnector):
    """
    tawk.to connector — fires a webhook POST with the escalation details.

    Since tawk.to has no inbound conversation creation API, the recommended
    integration is:
      Option A: Set webhook_url to your own endpoint, which triggers a
                tawk.to "start conversation" via the JS API on page load.
      Option B: Use Zapier/Make.com bridge — set webhook_url to a Zap that
                creates a tawk.to conversation via automation.
      Option C: Use the tawk.to REST API (read-only) + monitor via email
                notification (tawk.to handles agent notification natively).
    """

    async def handoff(self, payload: EscalationPayload) -> ConnectorResult:
        webhook_url = self.config.get("webhook_url", "")
        if not webhook_url:
            return ConnectorResult(
                success=False,
                error=(
                    "tawk.to does not support creating conversations via API. "
                    "Provide a webhook_url (your own endpoint or Zapier bridge) "
                    "to receive the escalation payload."
                )
            )

        transcript = self._format_history(payload.history)
        escalation_data = {
            "event": "ascenai_escalation",
            "timestamp": int(time.time()),
            "property_id": self.config.get("property_id", ""),
            "session_id": payload.session_id,
            "agent_name": payload.agent_name,
            "channel": payload.channel,
            "contact": {
                "name": payload.contact_name,
                "phone": payload.contact_phone,
                "email": payload.contact_email,
            },
            "trigger": payload.trigger_message,
            "transcript": transcript,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(webhook_url, json=escalation_data)
                if resp.status_code >= 400:
                    logger.error("tawkto_webhook_failed", status=resp.status_code, url=webhook_url)
                    return ConnectorResult(success=False, error=f"tawk.to webhook {resp.status_code}")

            logger.info("tawkto_handoff_success", session_id=payload.session_id)
            return ConnectorResult(success=True)
        except Exception as exc:
            logger.error("tawkto_webhook_exception", error=str(exc))
            return ConnectorResult(success=False, error=str(exc))
