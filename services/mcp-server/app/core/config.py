from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


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

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/mcp_db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Qdrant
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION_NAME: str = "knowledge_base"
    QDRANT_COLLECTION_PREFIX: str = "kb_"
    QDRANT_VECTOR_SIZE: int = 384  # all-MiniLM-L6-v2 size

    # Tool Execution
    MAX_TOOL_EXECUTION_TIMEOUT: int = 30
    RATE_LIMIT_PER_MINUTE: int = 100
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    # CORS
    ALLOWED_ORIGINS: list[str] = ["*"]
    ALLOWED_METHODS: list[str] = ["*"]
    ALLOWED_HEADERS: list[str] = ["*"]

    # Embeddings
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSION: int = 1536  # text-embedding-3-small dimension

    # External Services
    OPENAI_API_KEY: Optional[str] = None
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_FROM_NUMBER: Optional[str] = None

    # Encryption
    ENCRYPTION_KEY: Optional[str] = None  # Fernet key for encrypting stored secrets

    # Observability
    PROMETHEUS_ENABLED: bool = True
    SENTRY_DSN: Optional[str] = None
    ENVIRONMENT: str = "production"
    OTEL_ENABLED: bool = False
    OTEL_ENDPOINT: str = ""


settings = Settings()
