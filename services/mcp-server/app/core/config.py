from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

_WEAK_KEYS = frozenset({
    "change-this-secret-key-in-production-min-32-chars",
    "change-this-secret-key-in-production",
    "secret",
    "password",
    "dev",
    "test",
})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "MCP Server"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Security
    SECRET_KEY: str = "change-this-secret-key-in-production-min-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # CORS
    ALLOWED_ORIGINS: any = ["http://lvh.me:3000", "http://admin.lvh.me:3000"]
    ALLOWED_METHODS: str = "GET,POST,PUT,DELETE,OPTIONS"
    ALLOWED_HEADERS: str = "*"

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def validate_allowed_origins(cls, v: any) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        if v in _WEAK_KEYS:
            raise ValueError(
                "SECRET_KEY is a known weak default. "
                "Generate a strong key: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return v

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/mcp_db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Embeddings — Google Gemini text-embedding-004 (768-dim)
    GEMINI_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-004"
    EMBEDDING_DIMENSION: int = 768

    # External Services
    OPENAI_API_KEY: Optional[str] = None
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_FROM_NUMBER: Optional[str] = None

    # Webhook signing secrets — required in production to verify payload authenticity
    STRIPE_WEBHOOK_SECRET: Optional[str] = None      # whsec_... from Stripe dashboard
    CALENDLY_WEBHOOK_SECRET: Optional[str] = None    # signing secret from Calendly webhooks page

    # Encryption
    ENCRYPTION_KEY: Optional[str] = None  # Fernet key for encrypting stored secrets

    @field_validator("ENCRYPTION_KEY")
    @classmethod
    def validate_encryption_key(cls, v: Optional[str]) -> Optional[str]:
        import os
        if os.getenv("ENVIRONMENT", "production") == "production" and not v:
            raise ValueError(
                "ENCRYPTION_KEY must be set in production to encrypt stored tool secrets. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        return v

    # Observability
    PROMETHEUS_ENABLED: bool = True
    SENTRY_DSN: Optional[str] = None
    ENVIRONMENT: str = "production"
    OTEL_ENABLED: bool = False
    OTEL_ENDPOINT: str = ""


settings = Settings()
