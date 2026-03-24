"""
Text-to-Speech service supporting OpenAI TTS and ElevenLabs.
Provides both batch synthesis and streaming audio generation for low-latency responses.
"""
import asyncio
import os
import time
import uuid
from pathlib import Path
from typing import AsyncGenerator

import aiofiles
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

# Valid OpenAI TTS voices
OPENAI_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}


class TTSService:
    """
    Text-to-Speech service with streaming support.
    Supports OpenAI TTS and ElevenLabs.
    """

    def __init__(self):
        self._openai_client = None
        self._http_client = None
        # Ensure storage directory exists at startup
        Path(settings.AUDIO_STORAGE_PATH).mkdir(parents=True, exist_ok=True)

    def _get_openai_client(self):
        if self._openai_client is None:
            import openai
            self._openai_client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self._openai_client

    def _get_http_client(self):
        if self._http_client is None:
            import httpx
            self._http_client = httpx.AsyncClient(timeout=60.0)
        return self._http_client

    def _resolve_voice(self, voice_id: str) -> str:
        """Return a valid OpenAI voice name, defaulting to 'alloy'."""
        return voice_id if voice_id in OPENAI_VOICES else "alloy"

    # ------------------------------------------------------------------
    # Batch synthesis
    # ------------------------------------------------------------------

    async def synthesize(
        self,
        text: str,
        voice_id: str = "alloy",
        speed: float = 1.0,
        format: str = "mp3",
    ) -> bytes:
        """
        Synthesize text to audio (batch).

        Uses OpenAI TTS API (tts-1 model — cheap and fast).
        Returns the complete audio as raw bytes.

        Args:
            text:     The text to synthesize.
            voice_id: One of alloy, echo, fable, onyx, nova, shimmer.
            speed:    Playback speed multiplier (0.25 – 4.0).
            format:   Output format: mp3, opus, aac, flac, wav, pcm.
        """
        if not text.strip():
            return b""

        voice = self._resolve_voice(voice_id)
        client = self._get_openai_client()

        # Clamp speed to the supported range
        speed = max(0.25, min(4.0, speed))

        logger.info(
            "tts_synthesize_start",
            chars=len(text),
            voice=voice,
            format=format,
        )
        start = time.monotonic()

        try:
            response = await client.audio.speech.create(
                model="tts-1",
                voice=voice,  # type: ignore[arg-type]
                input=text,
                speed=speed,
                response_format=format,  # type: ignore[arg-type]
            )
            audio_bytes = response.content
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "tts_synthesize_complete",
                bytes=len(audio_bytes),
                elapsed_ms=elapsed_ms,
            )
            return audio_bytes
        except Exception as exc:
            logger.error("tts_synthesize_error", error=str(exc))
            raise

    # ------------------------------------------------------------------
    # Streaming synthesis (OpenAI)
    # ------------------------------------------------------------------

    async def synthesize_stream(
        self,
        text: str,
        voice_id: str = "alloy",
    ) -> AsyncGenerator[bytes, None]:
        """
        Stream audio synthesis — yields audio chunks as they are generated.

        Used for low-latency voice responses: the caller can begin playing
        audio before the entire synthesis is complete.
        """
        if not text.strip():
            return

        voice = self._resolve_voice(voice_id)
        client = self._get_openai_client()

        logger.info("tts_stream_start", chars=len(text), voice=voice)

        try:
            # iter_bytes streams the response body in chunks
            async with client.audio.speech.with_streaming_response.create(
                model="tts-1",
                voice=voice,  # type: ignore[arg-type]
                input=text,
                response_format="mp3",
            ) as response:
                async for chunk in response.iter_bytes(chunk_size=4096):
                    if chunk:
                        yield chunk

            logger.info("tts_stream_complete", voice=voice)
        except Exception as exc:
            logger.error("tts_stream_error", error=str(exc))
            raise

    # ------------------------------------------------------------------
    # ElevenLabs streaming synthesis
    # ------------------------------------------------------------------

    async def synthesize_elevenlabs(
        self,
        text: str,
        voice_id: str,
        model_id: str = "eleven_turbo_v2",
    ) -> AsyncGenerator[bytes, None]:
        """
        ElevenLabs streaming TTS for highest quality.

        Connects to the ElevenLabs streaming endpoint and yields mp3 chunks
        as they arrive.  Requires ELEVENLABS_API_KEY to be configured.

        Args:
            text:     Text to synthesize.
            voice_id: ElevenLabs voice ID (e.g. "21m00Tcm4TlvDq8ikWAM").
            model_id: ElevenLabs model (eleven_turbo_v2 for low latency).
        """
        if not settings.ELEVENLABS_API_KEY:
            raise RuntimeError(
                "ELEVENLABS_API_KEY is not configured. "
                "Set it in the environment or .env file."
            )

        if not text.strip():
            return

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
        headers = {
            "xi-api-key": settings.ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }

        logger.info(
            "elevenlabs_tts_stream_start",
            chars=len(text),
            voice_id=voice_id,
            model_id=model_id,
        )

        client = self._get_http_client()
        try:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(chunk_size=4096):
                    if chunk:
                        yield chunk

            logger.info("elevenlabs_tts_stream_complete", voice_id=voice_id)
        except Exception as exc:
            logger.error("elevenlabs_tts_stream_error", error=str(exc))
            raise

    # ------------------------------------------------------------------
    # Storage helpers
    # ------------------------------------------------------------------

    async def save_audio(self, audio: bytes, format: str = "mp3") -> str:
        """
        Persist audio bytes to the configured storage path.

        Returns the publicly accessible CDN URL for the saved file.
        """
        if not audio:
            raise ValueError("Cannot save empty audio buffer")

        filename = f"{uuid.uuid4()}.{format}"
        file_path = Path(settings.AUDIO_STORAGE_PATH) / filename

        async with aiofiles.open(str(file_path), "wb") as f:
            await f.write(audio)

        url = f"{settings.AUDIO_CDN_BASE_URL.rstrip('/')}/{filename}"
        logger.info("tts_audio_saved", path=str(file_path), url=url, bytes=len(audio))
        return url

    async def synthesize_and_save(
        self,
        text: str,
        voice_id: str = "alloy",
        speed: float = 1.0,
        format: str = "mp3",
    ) -> str:
        """
        Convenience method: synthesize text and persist the result.

        Returns the CDN URL of the saved audio file.
        """
        audio_bytes = await self.synthesize(
            text=text, voice_id=voice_id, speed=speed, format=format
        )
        return await self.save_audio(audio_bytes, format=format)

    async def close(self):
        """Clean up HTTP client resources."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
