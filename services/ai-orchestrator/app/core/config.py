from pydantic import field_validator
from pydantic_settings import BaseSettings
from functools import lru_cache

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

    # OpenAI (fallback)
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Embedding model
    EMBEDDING_MODEL: str = "text-embedding-3-small"

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

    # Orchestration limits
    MAX_TOOL_ITERATIONS: int = 3
    TOOL_TIMEOUT_SECONDS: int = 30

    # Service settings
    APP_NAME: str = "AI Orchestrator"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # CORS
    ALLOWED_ORIGINS: list[str] = ["*"]

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
