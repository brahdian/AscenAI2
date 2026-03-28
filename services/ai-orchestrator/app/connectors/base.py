"""Abstract base class for live-agent escalation connectors."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


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

    async def validate_credentials(self) -> tuple[bool, str]:
        """
        Test connectivity with configured credentials.
        Returns (True, "") on success or (False, error_message) on failure.
        Default implementation checks required config keys are present (non-empty).
        Subclasses may override to make an actual API call.
        """
        missing = [k for k in self._required_config_keys() if not self.config.get(k)]
        if missing:
            return False, f"Missing required config keys: {', '.join(missing)}"
        return True, ""

    def _required_config_keys(self) -> list[str]:
        """Return list of required config key names. Override in each connector."""
        return []

    @staticmethod
    def _scrub_pii(text: str) -> str:
        """Remove phone numbers and emails from strings before logging."""
        # Phone numbers (various formats)
        text = re.sub(r'\+?[\d\s\-\(\)]{7,}', '[PHONE]', text)
        # Email addresses
        text = re.sub(r'[\w.+-]+@[\w-]+\.[\w.-]+', '[EMAIL]', text)
        return text[:500]  # hard cap length

    def _format_history(self, history: list[dict], max_messages: int = 20) -> str:
        """Render the last N conversation turns as plain text for ticket bodies."""
        lines = []
        for msg in history[-max_messages:]:
            role = "User" if msg.get("role") == "user" else "Bot"
            content = msg.get("content", "").strip()
            if content:
                lines.append(f"{role}: {content}")
        return "\n".join(lines)

    async def _http_post(
        self,
        url: str,
        *,
        headers: dict,
        json: dict | None = None,
        auth=None,
        timeout: float = 15.0,
    ) -> httpx.Response:
        """POST with 3-attempt exponential-backoff retry on transient errors."""
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type(
                (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError)
            ),
            reraise=True,
        )
        async def _inner() -> httpx.Response:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=5.0)
            ) as client:
                if auth:
                    return await client.post(url, headers=headers, json=json, auth=auth)
                return await client.post(url, headers=headers, json=json)

        return await _inner()

    async def _http_post_content(
        self,
        url: str,
        *,
        headers: dict,
        content: str,
        timeout: float = 15.0,
    ) -> httpx.Response:
        """POST raw content with retry (used by webhook connector)."""
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type(
                (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError)
            ),
            reraise=True,
        )
        async def _inner() -> httpx.Response:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=5.0)
            ) as client:
                return await client.post(url, headers=headers, content=content)

        return await _inner()

    async def _http_post_form(
        self,
        url: str,
        *,
        headers: dict,
        data: dict,
        timeout: float = 15.0,
    ) -> httpx.Response:
        """POST form-encoded data with retry (used by helpscout token fetch)."""
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type(
                (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError)
            ),
            reraise=True,
        )
        async def _inner() -> httpx.Response:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=5.0)
            ) as client:
                return await client.post(url, headers=headers, data=data)

        return await _inner()

    async def _http_get(
        self,
        url: str,
        *,
        headers: dict,
        params: dict | None = None,
        auth=None,
        timeout: float = 15.0,
    ) -> httpx.Response:
        """GET with retry."""
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type(
                (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError)
            ),
            reraise=True,
        )
        async def _inner() -> httpx.Response:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=5.0)
            ) as client:
                if auth:
                    return await client.get(url, headers=headers, params=params, auth=auth)
                return await client.get(url, headers=headers, params=params)

        return await _inner()

    async def _http_patch(
        self,
        url: str,
        *,
        headers: dict,
        json: dict | None = None,
        auth=None,
        timeout: float = 15.0,
    ) -> httpx.Response:
        """PATCH with retry."""
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type(
                (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError)
            ),
            reraise=True,
        )
        async def _inner() -> httpx.Response:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=5.0)
            ) as client:
                if auth:
                    return await client.patch(url, headers=headers, json=json, auth=auth)
                return await client.patch(url, headers=headers, json=json)

        return await _inner()

    async def _http_put(
        self,
        url: str,
        *,
        headers: dict,
        json: dict | None = None,
        auth=None,
        timeout: float = 15.0,
    ) -> httpx.Response:
        """PUT with retry."""
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type(
                (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError)
            ),
            reraise=True,
        )
        async def _inner() -> httpx.Response:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=5.0)
            ) as client:
                if auth:
                    return await client.put(url, headers=headers, json=json, auth=auth)
                return await client.put(url, headers=headers, json=json)

        return await _inner()
