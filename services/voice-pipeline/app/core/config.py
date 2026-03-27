from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings

_WEAK_KEYS = frozenset({
    "change-this-secret-key-in-production-min-32-chars",
    "change-this-secret-key-in-production",
    "secret",
    "password",
    "dev",
    "test",
})


class Settings(BaseSettings):
    # STT config
    STT_PROVIDER: str = "gemini"  # "gemini" | "openai" | "deepgram"
    OPENAI_API_KEY: str = ""
    DEEPGRAM_API_KEY: str = ""

    # Gemini STT / LLM
    # Change GEMINI_STT_MODEL to upgrade — same model string as ai-orchestrator:
    #   gemini-2.5-flash-lite-preview-06-17  ← default ($1.00/1M audio tokens)
    #   gemini-2.5-flash                     ← better accuracy, ~2× cost
    #   gemini-3.1-flash                     ← future — update string when released
    GEMINI_API_KEY: str = ""
    GEMINI_STT_MODEL: str = "gemini-2.5-flash-lite-preview-06-17"

    # TTS config
    # "cartesia" is the recommended default: cheapest ($0.065/1M chars) + <100ms latency
    TTS_PROVIDER: str = "cartesia"  # "cartesia" | "google" | "elevenlabs" | "openai"
    CARTESIA_API_KEY: str = ""
    CARTESIA_VOICE_ID: str = "a0e99841-438c-4a64-b679-ae501e7d6091"  # neutral English
    ELEVENLABS_API_KEY: str = ""
    GOOGLE_TTS_VOICE: str = "en-US-Neural2-D"
    GOOGLE_APPLICATION_CREDENTIALS: str = ""  # Path to GCP service account JSON

    # AI Orchestrator
    AI_ORCHESTRATOR_WS_URL: str = "ws://ai-orchestrator:8002"
    AI_ORCHESTRATOR_URL: str = "http://ai-orchestrator:8002"

    # Twilio
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""

    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = "change-this-secret-key-in-production"

    # JWT
    JWT_ALGORITHM: str = "HS256"

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

    # Audio settings
    SAMPLE_RATE: int = 16000
    CHUNK_SIZE_MS: int = 100
    VAD_SILENCE_THRESHOLD_MS: int = 800  # Voice Activity Detection silence timeout
    MAX_UTTERANCE_DURATION_S: int = 30

    # VAD energy threshold (0.0 - 1.0, fraction of int16 max)
    VAD_ENERGY_THRESHOLD: float = 0.01

    # Storage for audio files
    AUDIO_STORAGE_PATH: str = "/tmp/audio"
    AUDIO_CDN_BASE_URL: str = "http://localhost:8003/audio"

    # Service settings
    APP_NAME: str = "Voice Pipeline"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # CORS — override in production with explicit origin list
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    # Observability
    SENTRY_DSN: str = ""
    ENVIRONMENT: str = "production"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
