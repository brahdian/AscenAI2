from __future__ import annotations

import base64
import structlog

import httpx

from app.core.crypto import decrypt_sensitive_fields
from app.models.tool import Tool

logger = structlog.get_logger(__name__)


class AuthManager:
    """Resolves authentication headers for HTTP-based tools."""

    async def resolve_tool_auth(self, tool: Tool) -> dict[str, str]:
        """Return HTTP headers required to authenticate with the tool endpoint."""
        if not tool.auth_config:
            return {}

        # Decrypt any encrypted fields before processing
        auth = decrypt_sensitive_fields(tool.auth_config)
        auth_type = auth.get("type", "none")

        if auth_type == "none":
            return {}

        if auth_type in ("api_key", "bearer"):
            header = auth.get("header", "Authorization")
            value = auth.get("value", "")
            if auth.get("value_encrypted"):
                value = self._decrypt(auth["value_encrypted"])
            return {header: value}

        if auth_type == "basic":
            username = auth.get("username", "")
            password = auth.get("password", "")
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
            return {"Authorization": f"Basic {encoded}"}

        if auth_type == "oauth2_cc":
            # OAuth2 Client Credentials flow — fetches a fresh access token at runtime
            token = await self._fetch_oauth2_cc_token(auth)
            return {"Authorization": f"Bearer {token}"}

        return {}

    async def _fetch_oauth2_cc_token(self, auth: dict) -> str:
        """
        Perform an OAuth2 client_credentials grant and return the access_token.

        Expected auth fields:
          - token_url: str      — e.g. https://auth.example.com/oauth/token
          - client_id: str
          - client_secret: str
          - scope: str (optional)
          - audience: str (optional)  — used by Auth0 / some providers
        """
        token_url = auth.get("token_url", "")
        if not token_url:
            raise ValueError("oauth2_cc auth requires 'token_url'")

        payload = {
            "grant_type": "client_credentials",
            "client_id": auth.get("client_id", ""),
            "client_secret": auth.get("client_secret", ""),
        }
        if auth.get("scope"):
            payload["scope"] = auth["scope"]
        if auth.get("audience"):
            payload["audience"] = auth["audience"]

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(token_url, data=payload)
            resp.raise_for_status()
            data = resp.json()

        token = data.get("access_token") or data.get("token")
        if not token:
            raise ValueError(f"OAuth2 response did not contain access_token: {list(data.keys())}")

        logger.info("oauth2_cc_token_fetched", token_url=token_url, expires_in=data.get("expires_in"))
        return token

    @staticmethod
    def _decrypt(encrypted: str) -> str:
        """Decrypt a Fernet-encrypted stored secret."""
        from app.core.crypto import decrypt_value
        return decrypt_value(encrypted)
