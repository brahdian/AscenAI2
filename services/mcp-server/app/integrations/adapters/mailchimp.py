"""Mailchimp adapter — Mailchimp Marketing API v3 via httpx.

Config keys (stored encrypted in tool_metadata):
  api_key       — Mailchimp API key (format: key-us6)
  server_prefix — Data center prefix extracted from api_key (e.g. "us6")
                  If omitted, parsed automatically from api_key.

Supported canonical actions:
  AddContactToList — Add or update a subscriber in an Audience (list)
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx
import structlog

from app.integrations.base import ACTION_REGISTRY, BaseAdapter
from app.integrations.errors import (
    IntegrationAuthError,
    IntegrationConfigError,
    IntegrationError,
    IntegrationException,
    ErrorCode,
    ProviderError,
    VerifyResult,
)

logger = structlog.get_logger(__name__)


def _base_url(server_prefix: str) -> str:
    return f"https://{server_prefix}.api.mailchimp.com/3.0"


def _parse_server(api_key: str) -> str:
    """Extract the data center prefix from a Mailchimp API key."""
    # Format: <key>-<server_prefix>
    if "-" in api_key:
        return api_key.rsplit("-", 1)[-1]
    return "us1"


class MailchimpAdapter(BaseAdapter):
    provider_name = "mailchimp"
    supported_actions = {"AddContactToList"}

    def _auth(self, config: dict) -> tuple[str, str]:
        api_key = config.get("api_key") or config.get("value")
        if not api_key:
            raise IntegrationConfigError.missing(self.provider_name, "api_key")
        server = config.get("server_prefix") or _parse_server(api_key)
        return api_key, server

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict, config: dict) -> dict:
        if action == "AddContactToList":
            return await self._add_contact(params, config)
        self._unsupported(action)

    async def verify_config(self, config: dict) -> VerifyResult:
        """Fetch the Mailchimp account info to confirm the API key works."""
        start = time.monotonic()
        try:
            api_key, server = self._auth(config)
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_base_url(server)}/",
                    auth=("anystring", api_key),
                )
            if resp.status_code == 401:
                return VerifyResult(ok=False, latency_ms=self._timed_verify(start),
                                    error="Mailchimp API key is invalid.")
            if not resp.is_success:
                return VerifyResult(ok=False, latency_ms=self._timed_verify(start),
                                    error=f"Mailchimp error {resp.status_code}")

            data = resp.json()
            return VerifyResult(
                ok=True,
                latency_ms=self._timed_verify(start),
                details={
                    "account_id": data.get("account_id", ""),
                    "account_name": data.get("account_name", ""),
                    "email": data.get("email", ""),
                    "server": server,
                },
            )
        except IntegrationConfigError as exc:
            return VerifyResult(ok=False, latency_ms=self._timed_verify(start), error=str(exc))
        except Exception as exc:
            return VerifyResult(ok=False, latency_ms=self._timed_verify(start), error=str(exc))

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    async def _add_contact(self, params: dict, config: dict) -> dict:
        """AddContactToList → Mailchimp PUT /lists/{list_id}/members/{hash}."""
        api_key, server = self._auth(config)
        list_id = params["list_id"]
        email = params["email"].lower().strip()

        # Mailchimp uses MD5 hash of lowercase email as the member ID
        email_hash = hashlib.md5(email.encode()).hexdigest()

        merge_fields: dict[str, Any] = {}
        if params.get("first_name"):
            merge_fields["FNAME"] = params["first_name"]
        if params.get("last_name"):
            merge_fields["LNAME"] = params["last_name"]

        body: dict[str, Any] = {
            "email_address": email,
            "status_if_new": params.get("status", "subscribed"),
            "status": params.get("status", "subscribed"),
        }
        if merge_fields:
            body["merge_fields"] = merge_fields
        if params.get("tags"):
            body["tags"] = [{"name": t, "status": "active"} for t in params["tags"]]

        async with httpx.AsyncClient(timeout=15) as client:
            # PUT is idempotent — safe to use even for updates
            resp = await client.put(
                f"{_base_url(server)}/lists/{list_id}/members/{email_hash}",
                auth=("anystring", api_key),
                json=body,
            )

        if resp.status_code == 401:
            raise IntegrationAuthError.from_provider(self.provider_name)
        if not resp.is_success:
            data = resp.json()
            detail = data.get("detail") or data.get("title") or f"error {resp.status_code}"
            raise IntegrationException(IntegrationError(
                code=ErrorCode.PROVIDER_ERROR,
                message=f"Mailchimp: {detail}",
                provider=self.provider_name,
                http_status=resp.status_code,
                retryable=resp.status_code >= 500,
            ))

        member = resp.json()
        return self._tag({
            "contact_id": member.get("id", email_hash),
            "email": email,
            "status": member.get("status", params.get("status", "subscribed")),
        })


# Self-register
ACTION_REGISTRY.register(MailchimpAdapter())
