from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # STT config
    STT_PROVIDER: str = "openai"  # "openai" | "deepgram" | "google"
    OPENAI_API_KEY: str = ""
    DEEPGRAM_API_KEY: str = ""

    # TTS config
    TTS_PROVIDER: str = "openai"  # "openai" | "elevenlabs" | "google"
    ELEVENLABS_API_KEY: str = ""

    # AI Orchestrator
    AI_ORCHESTRATOR_WS_URL: str = "ws://ai-orchestrator:8002"
    AI_ORCHESTRATOR_URL: str = "http://ai-orchestrator:8002"

    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = "change-this-secret-key-in-production"

    # JWT
    JWT_ALGORITHM: str = "HS256"

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
