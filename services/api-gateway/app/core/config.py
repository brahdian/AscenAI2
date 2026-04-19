from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_WEAK_KEYS = {
    "change-this-secret-key-in-production-min-32-chars",
    "secret",
    "supersecret",
    "your-secret-key",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "API Gateway"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ascenai"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Security
    SECRET_KEY: str = "change-this-secret-key-in-production-min-32-chars"

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        import os
        import warnings
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        if v in _WEAK_KEYS:
            env = os.getenv("ENVIRONMENT", "production")
            if env == "production":
                raise ValueError(
                    "SECRET_KEY is a known weak default. "
                    "Set a strong random value (e.g. openssl rand -hex 32)."
                )
            # In development/staging, emit a warning instead of failing so the
            # service still starts with the default key.
            warnings.warn(
                "SECRET_KEY is a known weak default — do NOT use this in production. "
                "Generate a strong key with: openssl rand -hex 32",
                UserWarning,
                stacklevel=2,
            )
        return v
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60         # 60 min — access token lifetime; refresh via cookie
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Internal service URLs
    MCP_SERVER_URL: str = "http://mcp-server:8001"
    AI_ORCHESTRATOR_URL: str = "http://ai-orchestrator:8002"
    VOICE_PIPELINE_URL: str = "http://voice-pipeline:8003"

    # Shared secret for internal service-to-service authentication.
    # Must match INTERNAL_API_KEY in the ai-orchestrator service.
    # PRODUCTION: set via env var (e.g. openssl rand -hex 32).
    INTERNAL_API_KEY: str = ""

    @field_validator("INTERNAL_API_KEY")
    @classmethod
    def validate_internal_api_key(cls, v: str) -> str:
        import os
        if os.getenv("ENVIRONMENT", "production") == "production" and not v:
            raise ValueError(
                "INTERNAL_API_KEY must be set in production. "
                "Generate one with: openssl rand -hex 32"
            )
        return v

    # SMTP / email
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_TLS: bool = True
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    FROM_EMAIL: str = "noreply@ascenai.com"

    # SendGrid / email provider
    SENDGRID_API_KEY: str = ""
    EMAIL_PROVIDER: str = "smtp"  # "smtp" | "sendgrid"

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    
    # Stripe Price IDs
    STRIPE_TEXT_GROWTH_PRICE_ID: str = ""
    STRIPE_VOICE_GROWTH_PRICE_ID: str = ""
    STRIPE_VOICE_BUSINESS_PRICE_ID: str = ""

    # WhatsApp (Meta Business API)
    WHATSAPP_VERIFY_TOKEN: str = ""     # Webhook verification challenge token
    WHATSAPP_APP_SECRET: str = ""       # App secret for X-Hub-Signature-256 verification

    # Twilio
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""

    # Public base URL used to construct canonical webhook URLs for Twilio
    # signature verification.  Must match the URL configured in Twilio console.
    # Example: https://api.yourdomain.com
    PUBLIC_BASE_URL: str = ""

    # SendGrid inbound webhook ECDSA public key (from SendGrid dashboard →
    # Settings → Mail Settings → Event Webhook → Signature Verification).
    # When set, all inbound parse webhook requests are verified.
    SENDGRID_WEBHOOK_VERIFICATION_KEY: str = ""

    # CORS — override with comma-separated list via ALLOWED_ORIGINS env var in production
    # Example: ALLOWED_ORIGINS="https://app.yourdomain.com,https://admin.yourdomain.com"
    FRONTEND_URL: str = "http://lvh.me:3000"
    ALLOWED_ORIGINS: any = [
        "http://lvh.me:3000",
        "http://admin.lvh.me:3000",
        "http://app.lvh.me:3000",
        "http://localhost:3000",
    ]
    COOKIE_DOMAIN: str | None = ".lvh.me"
    DYNAMIC_COOKIE_DOMAIN: bool = True  # Skips cookie domain for 'localhost'

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def validate_allowed_origins(cls, v: any) -> list[str]:
        if isinstance(v, str):
            return [i.strip() for i in v.split(",")]
        return v

    # Request size & timeout limits — override via env vars for large-file tenants
    MAX_BODY_BYTES: int = 10 * 1024 * 1024      # 10 MB default
    PROXY_TIMEOUT_SECONDS: float = 60.0          # Total request timeout
    PROXY_CONNECT_TIMEOUT_SECONDS: float = 5.0   # Connect-phase timeout

    # Usage quota soft-warning threshold (percent of plan limit)
    QUOTA_SOFT_WARNING_PCT: int = 80

    # Observability
    SENTRY_DSN: str = ""
    OTEL_ENDPOINT: str = ""      # e.g. "http://otel-collector:4317"
    OTEL_ENABLED: bool = False
    ENVIRONMENT: str = "production"
    
    # Trusted Proxies (for X-Forwarded-For validation)
    TRUSTED_PROXY_IPS: List[str] = []


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
