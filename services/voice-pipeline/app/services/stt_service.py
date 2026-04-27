"""
Speech-to-Text service powered by LiveKit Deepgram Plugin.
Provides production-grade streaming transcription with official SDK logic.
"""
import asyncio
import io
import time
from typing import AsyncGenerator, Optional

import structlog
from pydantic import BaseModel
from livekit import rtc
from livekit.plugins import deepgram
from livekit.agents import stt

from app.core.config import settings

logger = structlog.get_logger(__name__)


class TranscriptResult(BaseModel):
    text: str
    confidence: float
    language: str
    duration_ms: int


class PartialTranscript(BaseModel):
    text: str
    is_final: bool
    confidence: float


class STTService:
    """
    STT service using the official LiveKit Deepgram plugin.
    Supports both batch (via Whisper fallback) and streaming.
    """

    def __init__(self):
        self._openai_client = None
        # Initialize the official Deepgram plugin
        self._dg_stt = deepgram.STT(
            api_key=settings.DEEPGRAM_API_KEY,
            model="nova-2",
            language="en-US",
            interim_results=True,
        )

    def _get_openai_client(self):
        if self._openai_client is None:
            import openai
            self._openai_client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self._openai_client

    async def transcribe_audio(
        self,
        audio_data: bytes,
        language: str = "en",
        format: str = "webm",
    ) -> TranscriptResult:
        """
        Batch transcription via OpenAI Whisper API (retained for fallback).
        """
        if not audio_data:
            return TranscriptResult(text="", confidence=0.0, language=language, duration_ms=0)

        start_time = time.monotonic()
        client = self._get_openai_client()

        mime_map = {
            "webm": "audio/webm",
            "mp3": "audio/mpeg",
            "mp4": "audio/mp4",
            "wav": "audio/wav",
        }
        content_type = mime_map.get(format.lower(), "audio/webm")
        filename = f"audio.{format.lower()}"

        try:
            response = await client.audio.transcriptions.create(
                model="whisper-1",
                file=(filename, io.BytesIO(audio_data), content_type),
                language=language if language != "auto" else None,
                response_format="verbose_json",
            )
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            return TranscriptResult(
                text=response.text.strip(),
                confidence=1.0,
                language=getattr(response, "language", language),
                duration_ms=int(getattr(response, "duration", 0) * 1000) or elapsed_ms,
            )
        except Exception as exc:
            logger.error("stt_batch_error", error=str(exc))
            return TranscriptResult(text="", confidence=0.0, language=language, duration_ms=0)

    async def transcribe_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        language: str = "en",
    ) -> AsyncGenerator[PartialTranscript, None]:
        """
        Official LiveKit Deepgram Streaming STT.
        
        This handles the complex WebSocket handshake, keep-alives, 
        and interim result consolidation automatically.
        """
        # Create an official STT stream
        stt_stream = self._dg_stt.stream()

        async def _push_audio():
            try:
                async for chunk in audio_stream:
                    # Wrap raw bytes in AudioFrame for the SDK
                    frame = rtc.AudioFrame(
                        data=chunk,
                        sample_rate=settings.SAMPLE_RATE,
                        num_channels=1,
                        samples_per_channel=len(chunk) // 2
                    )
                    stt_stream.push_frame(frame)
                stt_stream.end_input()
            except Exception as e:
                logger.error("stt_stream_push_error", error=str(e))

        # Start pushing in background
        push_task = asyncio.create_task(_push_audio())

        try:
            # Iterate over official STT events
            async for event in stt_stream:
                if event.type == stt.SpeechEventType.FINAL_TRANSCRIPT:
                    yield PartialTranscript(
                        text=event.alternatives[0].text,
                        is_final=True,
                        confidence=event.alternatives[0].confidence
                    )
                elif event.type == stt.SpeechEventType.INTERIM_TRANSCRIPT:
                    yield PartialTranscript(
                        text=event.alternatives[0].text,
                        is_final=False,
                        confidence=event.alternatives[0].confidence
                    )
        finally:
            if not push_task.done():
                push_task.cancel()

    async def detect_voice_activity(self, audio_chunk: bytes) -> bool:
        """
        Legacy fallback VAD (RMS energy). 
        The main pipeline now uses Silero VAD from silero_vad.py.
        """
        import struct, math
        if len(audio_chunk) < 2: return False
        num_samples = len(audio_chunk) // 2
        samples = struct.unpack_from(f"<{num_samples}h", audio_chunk, 0)
        rms = math.sqrt(sum(s * s for s in samples) / num_samples)
        return (rms / 32768.0) > settings.VAD_ENERGY_THRESHOLD
