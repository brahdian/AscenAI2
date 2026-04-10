"""Unified error types for the MCP integration layer.

All provider-specific exceptions are caught inside adapters and re-raised as
one of these normalized types.  The AI layer and tool executor only ever see
the normalized form — never a Stripe StripeError or Twilio TwilioRestException.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Error codes (canonical, provider-neutral)
# ---------------------------------------------------------------------------

class ErrorCode:
    # Auth / config
    AUTH_FAILED       = "AUTH_FAILED"
    CONFIG_MISSING    = "CONFIG_MISSING"
    CONFIG_INVALID    = "CONFIG_INVALID"
    PERMISSION_DENIED = "PERMISSION_DENIED"

    # Request
    INVALID_INPUT     = "INVALID_INPUT"
    NOT_FOUND         = "NOT_FOUND"
    CONFLICT          = "CONFLICT"

    # Payment-specific
    PAYMENT_FAILED    = "PAYMENT_FAILED"
    CARD_DECLINED     = "CARD_DECLINED"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    EXPIRED_CARD      = "EXPIRED_CARD"

    # Provider / infra
    RATE_LIMITED      = "RATE_LIMITED"
    PROVIDER_ERROR    = "PROVIDER_ERROR"
    NETWORK_ERROR     = "NETWORK_ERROR"
    TIMEOUT           = "TIMEOUT"

    # Feature
    ACTION_NOT_SUPPORTED = "ACTION_NOT_SUPPORTED"


# ---------------------------------------------------------------------------
# Normalized error dataclass (returned to AI + tool executor)
# ---------------------------------------------------------------------------

@dataclass
class IntegrationError:
    """Normalized integration error — provider details hidden from AI layer."""
    code: str                            # One of ErrorCode.*
    message: str                         # Human-readable, safe for AI context
    provider: str                        # e.g. "stripe", "twilio"
    provider_code: Optional[str] = None  # Provider's own error code, for logs
    retryable: bool = False
    http_status: Optional[int] = None
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "provider": self.provider,
            "retryable": self.retryable,
        }

    def __str__(self) -> str:
        return f"[{self.provider.upper()}:{self.code}] {self.message}"


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class IntegrationException(Exception):
    """Base exception for all integration layer errors."""
    def __init__(self, error: IntegrationError) -> None:
        super().__init__(str(error))
        self.error = error


class IntegrationConfigError(IntegrationException):
    """Credentials or configuration missing/invalid."""
    @classmethod
    def missing(cls, provider: str, field: str) -> "IntegrationConfigError":
        return cls(IntegrationError(
            code=ErrorCode.CONFIG_MISSING,
            message=f"{provider.title()} is not configured — add your {field} in the tool settings.",
            provider=provider,
            retryable=False,
        ))

    @classmethod
    def invalid(cls, provider: str, reason: str) -> "IntegrationConfigError":
        return cls(IntegrationError(
            code=ErrorCode.CONFIG_INVALID,
            message=f"{provider.title()} configuration is invalid: {reason}",
            provider=provider,
            retryable=False,
        ))


class IntegrationAuthError(IntegrationException):
    """Provider rejected credentials (401/403)."""
    @classmethod
    def from_provider(cls, provider: str, provider_code: Optional[str] = None) -> "IntegrationAuthError":
        return cls(IntegrationError(
            code=ErrorCode.AUTH_FAILED,
            message=f"{provider.title()} credentials are invalid or expired. Please update your API keys.",
            provider=provider,
            provider_code=provider_code,
            retryable=False,
            http_status=401,
        ))


class IntegrationRateLimitError(IntegrationException):
    """Provider rate-limited the request."""
    @classmethod
    def from_provider(cls, provider: str, retry_after: Optional[int] = None) -> "IntegrationRateLimitError":
        msg = f"{provider.title()} rate limit exceeded."
        if retry_after:
            msg += f" Retry after {retry_after}s."
        return cls(IntegrationError(
            code=ErrorCode.RATE_LIMITED,
            message=msg,
            provider=provider,
            retryable=True,
            http_status=429,
        ))


class PaymentError(IntegrationException):
    """Payment processing failure."""
    @classmethod
    def card_declined(cls, provider: str, decline_code: Optional[str] = None) -> "PaymentError":
        return cls(IntegrationError(
            code=ErrorCode.CARD_DECLINED,
            message="The card was declined. Please ask the customer to use a different payment method.",
            provider=provider,
            provider_code=decline_code,
            retryable=False,
            http_status=402,
        ))

    @classmethod
    def generic(cls, provider: str, message: str, provider_code: Optional[str] = None) -> "PaymentError":
        return cls(IntegrationError(
            code=ErrorCode.PAYMENT_FAILED,
            message=message,
            provider=provider,
            provider_code=provider_code,
            retryable=False,
        ))


class ActionNotSupportedError(IntegrationException):
    """Adapter does not implement this action."""
    def __init__(self, action: str, provider: str) -> None:
        super().__init__(IntegrationError(
            code=ErrorCode.ACTION_NOT_SUPPORTED,
            message=f"Provider '{provider}' does not support action '{action}'.",
            provider=provider,
            retryable=False,
        ))


class ProviderError(IntegrationException):
    """Unclassified provider-side error (5xx, malformed response)."""
    @classmethod
    def from_http(cls, provider: str, status: int, body: str) -> "ProviderError":
        return cls(IntegrationError(
            code=ErrorCode.PROVIDER_ERROR,
            message=f"{provider.title()} returned an unexpected error ({status}). Try again shortly.",
            provider=provider,
            http_status=status,
            retryable=status >= 500,
            details={"response_preview": body[:300]},
        ))


# ---------------------------------------------------------------------------
# Verify result (used by BaseAdapter.verify_config)
# ---------------------------------------------------------------------------

@dataclass
class VerifyResult:
    """Result of a pre-save credential verification."""
    ok: bool
    latency_ms: int
    error: Optional[str] = None
    details: dict = field(default_factory=dict)   # e.g. {"account": "Acme Corp", "mode": "test"}

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "details": self.details,
        }
