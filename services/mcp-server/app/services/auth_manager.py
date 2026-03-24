from __future__ import annotations

from app.models.tool import Tool


class AuthManager:
    """Resolves authentication headers for HTTP-based tools."""

    async def resolve_tool_auth(self, tool: Tool) -> dict[str, str]:
        """Return HTTP headers required to authenticate with the tool endpoint."""
        if not tool.auth_config:
            return {}

        auth_type = tool.auth_config.get("type", "none")

        if auth_type == "none":
            return {}

        if auth_type in ("api_key", "bearer"):
            header = tool.auth_config.get("header", "Authorization")
            value = tool.auth_config.get("value", "")
            # Decrypt if stored encrypted (placeholder — integrate with KMS in production)
            if tool.auth_config.get("value_encrypted"):
                value = self._decrypt(tool.auth_config["value_encrypted"])
            return {header: value}

        if auth_type == "basic":
            import base64
            username = tool.auth_config.get("username", "")
            password = tool.auth_config.get("password", "")
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
            return {"Authorization": f"Basic {encoded}"}

        return {}

    @staticmethod
    def _decrypt(encrypted: str) -> str:
        """Decrypt a stored secret. Placeholder — use Fernet/KMS in production."""
        return encrypted
