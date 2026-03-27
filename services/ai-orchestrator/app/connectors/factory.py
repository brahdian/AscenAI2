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

logger = structlog.get_logger(__name__)

_REGISTRY: dict[str, type] = {}


def _register():
    """Lazily import connectors to avoid hard failures at startup if a
    dependency is missing for an unused provider."""
    global _REGISTRY
    if _REGISTRY:
        return
    from app.connectors.intercom import IntercomConnector
    from app.connectors.zendesk import ZendeskConnector
    from app.connectors.freshchat import FreshchatConnector
    from app.connectors.webhook import WebhookConnector
    _REGISTRY = {
        "intercom": IntercomConnector,
        "zendesk": ZendeskConnector,
        "freshchat": FreshchatConnector,
        "webhook": WebhookConnector,
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

    try:
        result = await connector.handoff(payload)
        if not result.success:
            logger.warning(
                "connector_handoff_failed",
                connector_type=escalation_config.get("connector_type"),
                error=result.error,
                session_id=payload.session_id,
            )
        return result
    except Exception as exc:
        logger.error(
            "connector_handoff_exception",
            connector_type=escalation_config.get("connector_type"),
            error=str(exc),
            session_id=payload.session_id,
        )
        return ConnectorResult(success=False, error=str(exc))
