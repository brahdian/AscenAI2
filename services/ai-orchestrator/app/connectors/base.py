"""Abstract base class for live-agent escalation connectors."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EscalationPayload:
    """Everything a connector needs to open a live-agent conversation."""
    # Conversation metadata
    tenant_id: str
    session_id: str
    agent_name: str          # AI agent that was serving the user

    # Contact info collected during escalation flow
    contact_name: str = ""
    contact_phone: str = ""
    contact_email: str = ""

    # Full message history: [{"role": "user"|"assistant", "content": "..."}]
    history: list[dict] = field(default_factory=list)

    # The final user message that triggered escalation
    trigger_message: str = ""

    # Channel: "text", "web", "voice"
    channel: str = "web"


@dataclass
class ConnectorResult:
    """Outcome returned by a connector after handoff attempt."""
    success: bool
    ticket_id: str = ""
    conversation_url: str = ""
    error: str = ""
    raw: dict = field(default_factory=dict)


class BaseConnector(ABC):
    """
    Abstract connector.  Subclasses implement `handoff()` for a specific
    live-chat / ticketing platform.
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config

    @abstractmethod
    async def handoff(self, payload: EscalationPayload) -> ConnectorResult:
        """
        Perform the handoff: create a ticket/conversation on the target
        platform and return a ConnectorResult.
        """

    def _format_history(self, history: list[dict], max_messages: int = 20) -> str:
        """Render the last N conversation turns as plain text for ticket bodies."""
        lines = []
        for msg in history[-max_messages:]:
            role = "User" if msg.get("role") == "user" else "Bot"
            content = msg.get("content", "").strip()
            if content:
                lines.append(f"{role}: {content}")
        return "\n".join(lines)
