"""Live-agent escalation connectors."""
from app.connectors.factory import get_connector, ConnectorResult

__all__ = ["get_connector", "ConnectorResult"]
