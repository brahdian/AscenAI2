from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ascenai"
    REDIS_URL: str = "redis://localhost:6379/0"
    MCP_SERVER_URL: str = "http://mcp-server:8001"
    MCP_WS_URL: str = "ws://mcp-server:8001"

    # LLM config - Gemini Flash Lite or OpenAI compatible
    LLM_PROVIDER: str = "gemini"  # "gemini" | "openai"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash-lite"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Embedding model
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    SECRET_KEY: str = "change-this-secret-key-in-production"
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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
