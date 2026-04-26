from pydantic import field_validator
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Any

_WEAK_KEYS = {
    "change-this-secret-key-in-production",
    "change-this-secret-key-in-production-min-32-chars",
    "secret",
    "supersecret",
    "your-secret-key",
}


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ascenai"
    REDIS_URL: str = "redis://localhost:6379/0"
    MCP_SERVER_URL: str = "http://mcp-server:8001"
    MCP_WS_URL: str = "ws://mcp-server:8001"
    MCP_SERVER_URL_US: str = "http://mcp-server-us:8001"
    MCP_SERVER_URL_EU: str = "http://mcp-server-eu:8001"
    # Voice pipeline service URL — used for pre-generating greeting / IVR audio
    VOICE_PIPELINE_URL: str = "http://voice-pipeline:8003"

    # LLM config
    LLM_PROVIDER: str = "gemini"  # "gemini" | "openai" | "vertex"
    GEMINI_API_KEY: str = ""

    # Gemini model selection — change GEMINI_MODEL to upgrade to newer releases:
    #   gemini-2.5-flash-lite-preview-06-17  ← default (cheapest, fastest)
    #   gemini-2.5-flash                     ← better quality, ~3× cost
    #   gemini-2.5-pro                       ← highest quality, ~10× cost
    #   gemini-3.1-flash                     ← future — update string when released
    GEMINI_MODEL: str = "gemini-2.5-flash-lite-preview-06-17"

    # Vertex AI (set LLM_PROVIDER=vertex to use Gemini via Google Cloud IAM auth)
    VERTEX_PROJECT_ID: str = ""
    VERTEX_LOCATION: str = "us-central1"
    # API-key based auth for Vertex AI (simpler than service-account IAM)
    VERTEX_API_KEY: str = ""
    # Base URL for Vertex AI REST API — override for private endpoints or VPC-SC
    VERTEX_API_ENDPOINT: str = "https://aiplatform.googleapis.com/v1/publishers/google/models"

    # OpenAI (fallback)
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Embedding model
    EMBEDDING_MODEL: str = "text-embedding-004"
    EMBEDDING_DIMENSION: int = 768

    # Shared secret for internal service-to-service calls (api-gateway → ai-orchestrator).
    # Set via INTERNAL_API_KEY env var.  When empty, the internal key check logs a
    # warning but does NOT block requests (backwards-compatible for local dev).
    # PRODUCTION: always set a strong random value (e.g. openssl rand -hex 32).
    INTERNAL_API_KEY: str = ""

    SECRET_KEY: str = "change-this-secret-key-in-production"

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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    MAX_CONTEXT_TOKENS: int = 8000
    MAX_RESPONSE_TOKENS: int = 1000
    MEMORY_WINDOW_SIZE: int = 20

    # Document storage — mount a persistent volume and set this path
    DOCUMENT_STORAGE_PATH: str = "/data/documents"  # override in prod with volume mount

    # Orchestration limits
    MAX_TOOL_ITERATIONS: int = 3
    TOOL_TIMEOUT_SECONDS: int = 30
    LLM_TIMEOUT_SECONDS: int = 30  # TC-F02: hard timeout per LLM call

    # Session auto-close
    SESSION_EXPIRY_MINUTES: int = 30  # Inactivity timeout before auto-close
    SESSION_EXPIRY_WARNING_MINUTES: int = 5  # Warning threshold before expiry

    # Service settings
    APP_NAME: str = "AI Orchestrator"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # CORS — default to localhost for dev; set ALLOWED_ORIGINS in prod
    ALLOWED_ORIGINS: Any = ["http://lvh.me:3000", "http://admin.lvh.me:3000"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def validate_allowed_origins(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    # Observability
    SENTRY_DSN: str = ""
    ENVIRONMENT: str = "production"
    OTEL_ENDPOINT: str = ""
    OTEL_ENABLED: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
