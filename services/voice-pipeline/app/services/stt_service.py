"""
Speech-to-Text service supporting OpenAI Whisper and Deepgram.
Provides both batch and streaming transcription with Voice Activity Detection.
"""
import asyncio
import io
import struct
import math
import time
from typing import AsyncGenerator

import httpx
import structlog
from pydantic import BaseModel

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
    Streaming and batch Speech-to-Text service.
    Supports OpenAI Whisper and Deepgram.
    """

    def __init__(self):
        self._openai_client = None
        self._deepgram_client = None

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
        Batch transcription via OpenAI Whisper API.

        Sends the entire audio buffer to Whisper and returns a complete
        TranscriptResult with detected text, confidence, language, and duration.
        """
        if not audio_data:
            return TranscriptResult(
                text="", confidence=0.0, language=language, duration_ms=0
            )

        start_time = time.monotonic()
        client = self._get_openai_client()

        # Build a file-like object with correct MIME type so Whisper accepts it
        mime_map = {
            "webm": "audio/webm",
            "mp3": "audio/mpeg",
            "mp4": "audio/mp4",
            "wav": "audio/wav",
            "ogg": "audio/ogg",
            "flac": "audio/flac",
            "m4a": "audio/m4a",
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

            # verbose_json returns duration in seconds; fall back to elapsed if absent
            audio_duration_ms = int(getattr(response, "duration", 0) * 1000) or elapsed_ms

            # Whisper doesn't expose per-segment confidence via the simple API,
            # so we report 1.0 for a successful response.
            confidence = 1.0
            detected_language = getattr(response, "language", language) or language

            logger.info(
                "stt_transcribe_complete",
                chars=len(response.text),
                duration_ms=elapsed_ms,
                language=detected_language,
            )

            return TranscriptResult(
                text=response.text.strip(),
                confidence=confidence,
                language=detected_language,
                duration_ms=audio_duration_ms,
            )

        except Exception as exc:
            logger.error("stt_transcribe_error", error=str(exc))
            raise

    async def transcribe_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        language: str = "en",
    ) -> AsyncGenerator[PartialTranscript, None]:
        """
        Streaming transcription using Deepgram Live Streaming API.

        Opens a persistent WebSocket to Deepgram, forwards audio chunks as they
        arrive, and yields PartialTranscript objects as Deepgram emits interim
        and final transcript events.  Falls back to OpenAI Whisper if no
        Deepgram key is configured.
        """
        if settings.DEEPGRAM_API_KEY:
            async for partial in self._deepgram_stream(audio_stream, language):
                yield partial
        else:
            # Fallback: buffer all audio then do single Whisper call
            logger.warning(
                "deepgram_key_missing_falling_back_to_whisper",
            )
            async for partial in self._whisper_buffered_stream(audio_stream, language):
                yield partial

    async def _deepgram_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        language: str,
    ) -> AsyncGenerator[PartialTranscript, None]:
        """
        Live streaming transcription via Deepgram WebSocket API.
        https://developers.deepgram.com/reference/streaming
        """
        import json
        import websockets  # type: ignore

        url = (
            "wss://api.deepgram.com/v1/listen"
            f"?language={language}"
            "&model=nova-2"
            "&encoding=linear16"
            f"&sample_rate={settings.SAMPLE_RATE}"
            "&channels=1"
            "&interim_results=true"
            "&endpointing=500"
        )
        headers = {"Authorization": f"Token {settings.DEEPGRAM_API_KEY}"}

        result_queue: asyncio.Queue[PartialTranscript | None] = asyncio.Queue()

        async def _send_audio(ws):
            try:
                async for chunk in audio_stream:
                    await ws.send(chunk)
                # Signal end of stream
                await ws.send(json.dumps({"type": "CloseStream"}))
            except Exception as exc:
                logger.error("deepgram_send_error", error=str(exc))

        async def _receive_transcripts(ws):
            try:
                async for message in ws:
                    data = json.loads(message)
                    msg_type = data.get("type", "")
                    if msg_type == "Results":
                        channel = data.get("channel", {})
                        alternatives = channel.get("alternatives", [{}])
                        if alternatives:
                            alt = alternatives[0]
                            transcript = alt.get("transcript", "").strip()
                            is_final = data.get("is_final", False)
                            confidence = alt.get("confidence", 0.0)
                            if transcript:
                                await result_queue.put(
                                    PartialTranscript(
                                        text=transcript,
                                        is_final=is_final,
                                        confidence=confidence,
                                    )
                                )
                    elif msg_type in ("SpeechStarted", "UtteranceEnd"):
                        pass  # informational
            except Exception as exc:
                logger.error("deepgram_receive_error", error=str(exc))
            finally:
                await result_queue.put(None)  # sentinel

        try:
            async with websockets.connect(url, extra_headers=headers) as ws:
                send_task = asyncio.create_task(_send_audio(ws))
                recv_task = asyncio.create_task(_receive_transcripts(ws))

                while True:
                    item = await result_queue.get()
                    if item is None:
                        break
                    yield item

                await asyncio.gather(send_task, recv_task, return_exceptions=True)
        except Exception as exc:
            logger.error("deepgram_connection_error", error=str(exc))
            raise

    async def _whisper_buffered_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        language: str,
    ) -> AsyncGenerator[PartialTranscript, None]:
        """
        Buffer all incoming audio, then transcribe once via Whisper.
        Used as a fallback when Deepgram is unavailable.
        Emits interim 'listening…' updates every second while buffering.
        """
        buffer = bytearray()
        last_interim = time.monotonic()

        async for chunk in audio_stream:
            buffer.extend(chunk)
            now = time.monotonic()
            if now - last_interim >= 1.0:
                last_interim = now
                yield PartialTranscript(text="...", is_final=False, confidence=0.0)

        if buffer:
            result = await self.transcribe_audio(bytes(buffer), language=language)
            yield PartialTranscript(
                text=result.text, is_final=True, confidence=result.confidence
            )

    async def detect_voice_activity(
        self,
        audio_chunk: bytes,
        sample_rate: int = 16000,
    ) -> bool:
        """
        Simple energy-based Voice Activity Detection (VAD).

        Interprets ``audio_chunk`` as raw 16-bit little-endian PCM samples,
        computes the root-mean-square (RMS) energy, and returns True if the
        RMS exceeds the configured threshold fraction of the int16 maximum
        amplitude (32768).

        Returns False (silence) when the chunk is too small to analyse.
        """
        if len(audio_chunk) < 2:
            return False

        # Parse as 16-bit signed integers (little-endian)
        num_samples = len(audio_chunk) // 2
        samples = struct.unpack_from(f"<{num_samples}h", audio_chunk, 0)

        # RMS energy
        mean_sq = sum(s * s for s in samples) / num_samples
        rms = math.sqrt(mean_sq)

        # Normalise to [0, 1] range relative to int16 max
        normalised_rms = rms / 32768.0

        is_voice = normalised_rms > settings.VAD_ENERGY_THRESHOLD
        return is_voice
