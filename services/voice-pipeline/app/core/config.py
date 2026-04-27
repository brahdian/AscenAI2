from functools import lru_cache
from typing import Any
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
    # Unified Orchestration (In-process Brain)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ascenai"
    
    # STT config
    # Deepgram Nova-2 is recommended for STT ($0.46/hr). Gemini is fallback.
    STT_PROVIDER: str = "deepgram"  # "cartesia" | "deepgram" | "gemini" | "openai"
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
    # Cartesia Sonic ($31/1M chars, sub-100ms latency) OR Deepgram Aura 2 ($30/1M chars)
    TTS_PROVIDER: str = "cartesia"  # "cartesia" | "deepgram" | "google" | "elevenlabs" | "openai"
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
    INTERNAL_API_KEY: str = ""

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
    CHUNK_SIZE_MS: int = 32              # Silero VAD requires 32ms frames at 16kHz
    VAD_SILENCE_THRESHOLD_MS: int = 300  # Neural VAD: 300ms (was 800ms energy-based)
    MAX_UTTERANCE_DURATION_S: int = 30

    # Legacy energy-based VAD threshold (used as fallback if Silero fails to load)
    VAD_ENERGY_THRESHOLD: float = 0.01

    # Phase 1: Silero VAD
    # Download from: https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx
    SILERO_VAD_ENABLED: bool = True
    SILERO_VAD_THRESHOLD: float = 0.5        # Speech probability threshold (0.0-1.0)
    SILERO_VAD_MIN_SPEECH_MS: int = 250      # Minimum voiced frame length to count as speech
    SILERO_VAD_MIN_SILENCE_MS: int = 300     # Silence gap to signal end of utterance
    SILERO_VAD_MODEL_PATH: str = "/tmp/silero_vad.onnx"  # Auto-downloaded on first run

    # Phase 2: Streaming STT
    STT_STREAMING_ENABLED: bool = True       # Open live STT WS, not batch upload
    STT_INTERIM_CONFIDENCE_THRESHOLD: float = 0.0  # Accept all interim results for early LLM fire

    # Phase 3: Voice-Mode LLM Routing
    # When set, this model is used for voice turns (overrides ai-orchestrator default)
    VOICE_LLM_MODEL: str = ""                # e.g. "gemini-2.0-flash" or Groq model
    VOICE_LLM_MAX_TOKENS: int = 200          # Keep voice responses short

    # Phase 4: Chunked TTS
    TTS_WORD_CHUNK_SIZE: int = 10            # Synthesize after N words (don't wait for sentence end)
    TTS_FORCE_CHUNK_CHARS: int = 80          # Also flush if buffer > N chars even without punctuation

    # Phase 4: Latency Telemetry
    LATENCY_TELEMETRY_ENABLED: bool = True   # Track hop-by-hop latency per session

    # Storage for audio files
    AUDIO_STORAGE_PATH: str = "/tmp/audio"
    AUDIO_CDN_BASE_URL: str = "http://localhost:8003/audio"

    # Service settings
    APP_NAME: str = "Voice Pipeline"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # CORS — override in production with explicit origin list
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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
