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
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        if v in _WEAK_KEYS:
            raise ValueError(
                "SECRET_KEY is a known weak default. "
                "Set a strong random value (e.g. openssl rand -hex 32)."
            )
        return v
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30         # 30 min — short-lived; refresh via cookie
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Internal service URLs
    MCP_SERVER_URL: str = "http://mcp-server:8001"
    AI_ORCHESTRATOR_URL: str = "http://ai-orchestrator:8002"
    VOICE_PIPELINE_URL: str = "http://voice-pipeline:8003"

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

    # Twilio
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""

    # CORS
    FRONTEND_URL: str = "http://lvh.me:3000"
    ALLOWED_ORIGINS: any = [
        "http://lvh.me:3000", 
        "http://admin.lvh.me:3000", 
        "http://app.lvh.me:3000",
        "http://localhost:3000"
    ]
    COOKIE_DOMAIN: str | None = ".lvh.me"
    DYNAMIC_COOKIE_DOMAIN: bool = True  # If true, skips setting domain for 'localhost'

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def validate_allowed_origins(cls, v: any) -> list[str]:
        if isinstance(v, str):
            return [i.strip() for i in v.split(",")]
        return v

    # Observability
    SENTRY_DSN: str = ""
    OTEL_ENDPOINT: str = ""      # e.g. "http://otel-collector:4317"
    OTEL_ENABLED: bool = False
    ENVIRONMENT: str = "production"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
