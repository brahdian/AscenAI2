from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator


def _validate_password_complexity(v: str) -> str:
    """Enforce: 8+ chars, at least one uppercase, one lowercase, one digit.
    Implemented as a plain validator instead of a regex pattern because
    Pydantic V2 uses the Rust regex engine which does not support lookaheads.
    """
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not any(c.islower() for c in v):
        raise ValueError("Password must contain at least one lowercase letter")
    if not any(c.isupper() for c in v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not any(c.isdigit() for c in v):
        raise ValueError("Password must contain at least one number")
    return v


class UserInfo(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    tenant_id: str
    mfa_enabled: bool = False

    model_config = {"from_attributes": True}


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(
        min_length=8,
        description="Minimum 8 characters with at least one uppercase, lowercase, and number"
    )
    full_name: str = Field(min_length=1, max_length=255)
    business_name: str = Field(min_length=1, max_length=255)
    business_type: str = Field(
        default="other",
        description="One of: pizza_shop, clinic, salon, other",
    )
    plan: str = Field(
        default="voice_growth",
        description="Plan: text_growth, voice_growth, voice_business",
    )

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        return _validate_password_complexity(v)


class RegisterResponse(BaseModel):
    message: str = "Verification code sent. Complete email verification to continue."
    email: str
    requires_verification: bool = True


class VerifyEmailResponse(BaseModel):
    message: str
    email: str
    tenant_id: str


class SubscribeRequest(BaseModel):
    email: EmailStr
    plan: str = Field(default="voice_growth")


class SubscribeResponse(BaseModel):
    payment_url: str
    session_id: str
    plan: str


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=6, max_length=6)


class ResendOTPRequest(BaseModel):
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    tenant_id: str
    user: UserInfo


class RefreshRequest(BaseModel):
    """Body is optional when refresh_token is provided via HttpOnly cookie."""
    refresh_token: str = ""


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(
        min_length=8,
        description="Minimum 8 characters with at least one uppercase, lowercase, and number"
    )

    @field_validator("new_password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        return _validate_password_complexity(v)


class APIKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    scopes: list[str] = Field(default_factory=lambda: ["chat"])
    expires_at: str | None = None  # ISO datetime string, optional
    agent_id: str | None = None  # Optional: restrict key to specific agent
    allowed_origins: list[str] | None = None  # Optional: restrict key to these domains


class APIKeyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    allowed_origins: list[str] | None = None
    is_active: bool | None = None


class APIKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    scopes: list[str]
    rate_limit_per_minute: int
    is_active: bool
    last_used_at: str | None
    expires_at: str | None
    created_at: str
    agent_id: str | None = None
    allowed_origins: list[str] | None = None

    model_config = {"from_attributes": True}


class APIKeyCreatedResponse(APIKeyResponse):
    """Returned only at creation time — includes the raw key."""
    raw_key: str


class WebhookCreateRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    events: list[str] = Field(
        default_factory=list,
        description="e.g. ['session.started', 'session.ended', 'tool.executed']",
    )


class WebhookUpdateRequest(BaseModel):
    url: str | None = Field(default=None, max_length=2048)
    events: list[str] | None = None
    is_active: bool | None = None


class WebhookResponse(BaseModel):
    id: str
    tenant_id: str
    url: str
    events: list[str]
    is_active: bool
    created_at: str

    model_config = {"from_attributes": True}


class WebhookCreatedResponse(WebhookResponse):
    """Returned only at creation time — includes the signing secret (one-time show)."""
    secret: str


class AcceptInviteRequest(BaseModel):
    token: str
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(
        min_length=8,
        description="Minimum 8 characters with at least one uppercase, lowercase, and number"
    )

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        return _validate_password_complexity(v)
