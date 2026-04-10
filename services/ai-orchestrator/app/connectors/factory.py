"""
Connector factory — instantiates the right connector based on escalation_config.

escalation_config structure (stored as JSONB on Agent):
  {
    "escalate_to_human": true,
    "escalation_number": "+15551234567",
    "chat_enabled": true,
    "chat_agent_name": "Support Team",
    "connector_type": "intercom",    # one of: intercom | zendesk | freshchat | webhook
    "connector_config": { ... }      # platform-specific credentials
  }
"""
from __future__ import annotations

import structlog
from typing import Any

from app.connectors.base import BaseConnector, ConnectorResult, EscalationPayload
from app.core.metrics import ESCALATION_ATTEMPTS

logger = structlog.get_logger(__name__)

_REGISTRY: dict[str, type] = {}


def _register():
    """Lazily import all connectors.
    Lazy loading avoids import-time failures when a connector's optional
    dependencies are not installed or when it will never be used.
    """
    global _REGISTRY
    if _REGISTRY:
        return

    # Original connectors
    from app.connectors.intercom import IntercomConnector
    from app.connectors.zendesk import ZendeskConnector
    from app.connectors.freshchat import FreshchatConnector
    from app.connectors.webhook import WebhookConnector

    # Canadian SMB connectors
    from app.connectors.hubspot import HubSpotConnector
    from app.connectors.freshdesk import FreshdeskConnector
    from app.connectors.livechat import LiveChatConnector
    from app.connectors.zoho_desk import ZohoDeskConnector
    from app.connectors.helpscout import HelpScoutConnector
    from app.connectors.crisp import CrispConnector
    from app.connectors.gorgias import GorgiasConnector
    from app.connectors.reamaze import ReamazeConnector
    from app.connectors.liveagent import LiveAgentConnector
    from app.connectors.front import FrontConnector
    from app.connectors.tidio import TidioConnector
    from app.connectors.tawkto import TawkToConnector
    from app.connectors.comm100 import Comm100Connector

    _REGISTRY = {
        # ── Original ──────────────────────────────────────────────────────────
        "intercom":   IntercomConnector,
        "zendesk":    ZendeskConnector,
        "freshchat":  FreshchatConnector,   # Freshchat (live chat product)
        "webhook":    WebhookConnector,

        # ── CRM / helpdesk (high Canadian SMB penetration) ───────────────────
        "hubspot":    HubSpotConnector,     # HubSpot Tickets + Contacts CRM
        "freshdesk":  FreshdeskConnector,   # Freshdesk tickets (≠ Freshchat)
        "livechat":   LiveChatConnector,    # LiveChat Inc. tickets
        "zoho_desk":  ZohoDeskConnector,    # Zoho Desk tickets
        "helpscout":  HelpScoutConnector,   # Help Scout conversations
        "crisp":      CrispConnector,       # Crisp conversations
        "gorgias":    GorgiasConnector,     # Gorgias (popular Shopify stores)
        "reamaze":    ReamazeConnector,     # Re:amaze (ecommerce SMBs)
        "liveagent":  LiveAgentConnector,   # LiveAgent tickets
        "front":      FrontConnector,       # Front collaborative inbox
        "tidio":      TidioConnector,       # Tidio (webhook-based)
        "tawkto":     TawkToConnector,      # tawk.to (webhook bridge; Canadian #1 free)
        "comm100":    Comm100Connector,     # Comm100 (Vancouver, BC — Canadian)
    }


def get_connector(escalation_config: dict[str, Any]) -> BaseConnector | None:
    """
    Return an instantiated connector for the given escalation_config,
    or None if no connector_type is configured.
    """
    _register()
    connector_type = (escalation_config.get("connector_type") or "").lower().strip()
    if not connector_type:
        return None

    cls = _REGISTRY.get(connector_type)
    if cls is None:
        logger.warning("unknown_connector_type", connector_type=connector_type, known=list(_REGISTRY))
        return None

    connector_config = escalation_config.get("connector_config") or {}
    return cls(connector_config)


async def trigger_connector(
    escalation_config: dict[str, Any],
    payload: EscalationPayload,
) -> ConnectorResult | None:
    """
    Convenience function: get the connector and call handoff().
    Returns None if no connector is configured.
    Swallows exceptions and returns a failed ConnectorResult so escalation
    proceeds even if the third-party API is down.
    """
    connector = get_connector(escalation_config)
    if connector is None:
        return None

    connector_type = escalation_config.get("connector_type") or "unknown"
    try:
        result = await connector.handoff(payload)
        if result.success:
            ESCALATION_ATTEMPTS.labels(connector_type=connector_type, status="success").inc()
        else:
            ESCALATION_ATTEMPTS.labels(connector_type=connector_type, status="failed").inc()
            logger.warning(
                "connector_handoff_failed",
                connector_type=connector_type,
                error=result.error,
                session_id=payload.session_id,
            )
        return result
    except Exception as exc:
        ESCALATION_ATTEMPTS.labels(connector_type=connector_type, status="failed").inc()
        logger.error(
            "connector_handoff_exception",
            connector_type=connector_type,
            error=str(exc),
            session_id=payload.session_id,
        )
        return ConnectorResult(success=False, error=str(exc))


async def trigger_connector_with_idempotency(
    escalation_config: dict[str, Any],
    payload: EscalationPayload,
    redis=None,
) -> ConnectorResult | None:
    """
    Like trigger_connector(), but uses a Redis SET NX guard to prevent
    duplicate escalations for the same session within a 10-minute window.

    If redis is None, falls through to trigger_connector() with no dedup.
    Returns None if no connector is configured.
    """
    if redis is not None:
        idem_key = f"escalation:fired:{payload.session_id}"
        was_set = await redis.set(idem_key, "1", nx=True, ex=600)
        if not was_set:
            logger.info("escalation_deduplicated", session_id=payload.session_id)
            connector_type = escalation_config.get("connector_type") or "unknown"
            ESCALATION_ATTEMPTS.labels(connector_type=connector_type, status="deduplicated").inc()
            return ConnectorResult(success=True, ticket_id="deduplicated", error="")
    return await trigger_connector(escalation_config, payload)
