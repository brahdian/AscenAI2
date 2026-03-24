from pydantic import BaseModel, Field
from typing import Optional


class TranscriptResult(BaseModel):
    """Result of a completed batch STT transcription."""

    text: str = Field(..., description="Transcribed text")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0-1")
    language: str = Field(..., description="Detected or requested language code")
    duration_ms: int = Field(..., description="Audio duration in milliseconds")


class PartialTranscript(BaseModel):
    """Streaming partial transcript yielded during live transcription."""

    text: str = Field(..., description="Partial or final transcript text")
    is_final: bool = Field(..., description="True when the utterance is complete")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class TTSRequest(BaseModel):
    """Request body for TTS endpoints."""

    text: str = Field(..., min_length=1, max_length=4096, description="Text to synthesize")
    voice_id: str = Field(
        default="alloy",
        description="Voice ID. OpenAI: alloy, echo, fable, onyx, nova, shimmer. ElevenLabs: voice UUID.",
    )
    language: str = Field(default="en", description="Language code e.g. 'en', 'es'")
    speed: float = Field(default=1.0, ge=0.25, le=4.0, description="Speech speed multiplier")
    format: str = Field(default="mp3", description="Audio format: mp3, opus, aac, flac, wav, pcm")
    provider: Optional[str] = Field(
        default=None,
        description="Override TTS provider: openai | elevenlabs. Uses server default if None.",
    )


class STTRequest(BaseModel):
    """Metadata for batch STT request."""
    language: str = Field(default="en", description="Language code e.g. 'en', 'es'")
    session_id: str = Field(default="", description="Optional session identifier")


class STTResponse(BaseModel):
    """Response from batch STT endpoint."""
    transcript: str = Field(..., description="Transcribed text")
    language: str
    session_id: str


class TTSUrlResponse(BaseModel):
    """Response for TTS URL endpoint."""

    url: str = Field(..., description="URL to the generated audio file")
    duration_estimate_s: Optional[float] = Field(
        default=None, description="Estimated audio duration in seconds"
    )
    voice_id: str
    format: str


class VoiceSessionInfo(BaseModel):
    """Metadata sent to client when WebSocket session is established."""

    session_id: str
    tenant_id: str
    agent_id: str
    sample_rate: int
    chunk_size_ms: int
    vad_silence_threshold_ms: int


class WSMessageType:
    """WebSocket binary frame type prefix byte values."""

    # Client -> Server
    AUDIO_CHUNK = 0x01      # raw PCM / WebM audio chunk
    CONTROL = 0x02          # JSON control message (start, stop, barge-in)

    # Server -> Client
    TRANSCRIPT_PARTIAL = 0x10   # partial transcript JSON
    TRANSCRIPT_FINAL = 0x11     # final transcript JSON
    AI_TEXT_DELTA = 0x12        # streaming AI text delta JSON
    AUDIO_RESPONSE = 0x13       # TTS audio bytes
    SESSION_EVENT = 0x14        # session lifecycle events (ready, error, barge_in_ack)
    HEARTBEAT = 0x15            # keep-alive
