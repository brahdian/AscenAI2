from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class UserInfo(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    tenant_id: str

    model_config = {"from_attributes": True}


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, description="Minimum 8 characters")
    full_name: str = Field(min_length=1, max_length=255)
    business_name: str = Field(min_length=1, max_length=255)
    business_type: str = Field(
        default="other",
        description="One of: pizza_shop, clinic, salon, other",
    )


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
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class APIKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    scopes: list[str] = Field(default_factory=lambda: ["chat"])
    expires_at: str | None = None  # ISO datetime string, optional
    agent_id: str | None = None  # Optional: restrict key to specific agent


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
