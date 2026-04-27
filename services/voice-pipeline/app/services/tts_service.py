"""
Text-to-Speech service powered by LiveKit Cartesia Plugin.
Provides sub-100ms TTFA (Time-to-First-Audio) using the Sonic engine.
"""
import asyncio
from typing import AsyncGenerator, Optional
from pathlib import Path

import structlog
from livekit import rtc
from livekit.plugins import cartesia
from app.core.config import settings

logger = structlog.get_logger(__name__)


class TTSService:
    """
    TTS service using the official LiveKit Cartesia plugin.
    Includes built-in sanitization and batch fallback.
    """

    def __init__(self):
        self._openai_client = None
        # Initialize official Cartesia plugin (Sonic-3 model)
        self._cartesia_tts = cartesia.TTS(
            api_key=settings.CARTESIA_API_KEY,
            model="sonic-english", # Fast & high quality
            voice="a0e99841-438c-4a64-b679-ae501e7d6091", # Default Sonic voice
            sample_rate=settings.SAMPLE_RATE, # 16000
            encoding="pcm_s16le",
        )
        # Ensure storage directory exists
        Path(settings.AUDIO_STORAGE_PATH).mkdir(parents=True, exist_ok=True)

    def _get_openai_client(self):
        if self._openai_client is None:
            import openai
            self._openai_client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self._openai_client

    async def synthesize_stream(
        self,
        text: str,
        voice_id: Optional[str] = None,
    ) -> AsyncGenerator[bytes, None]:
        """
        Official LiveKit Cartesia Streaming TTS.
        Yields raw PCM audio chunks.
        """
        if not text.strip():
            return

        # VULN-031: Strip SSML to prevent engine injection
        clean_text = self._sanitize_tts_input(text)

        # Create official TTS stream
        # (We use the sonic-english model which is optimized for real-time)
        tts_stream = self._cartesia_tts.stream()
        tts_stream.push_text(clean_text)
        tts_stream.flush()
        tts_stream.end_input()

        try:
            async for event in tts_stream:
                # The official plugin yields AudioFrame objects
                if event.type == cartesia.tts.SynthesizeEventType.AUDIO:
                    if event.audio and event.audio.data:
                        # Extract raw bytes from the frame
                        yield event.audio.data
        except Exception as e:
            logger.error("tts_stream_error", error=str(e))
        finally:
            await tts_stream.aclose()

    async def synthesize(self, text: str) -> bytes:
        """Batch synthesis fallback using OpenAI (cheap/fast)."""
        client = self._get_openai_client()
        response = await client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=text,
            response_format="mp3",
        )
        return response.content

    @staticmethod
    def _sanitize_tts_input(text: str) -> str:
        import re
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'(prosody|pitch|rate|volume|emphasis)\s*=', '', text, flags=re.IGNORECASE)
        return text

    async def save_audio(self, audio: bytes, format: str = "mp3") -> str:
        import aiofiles
        import uuid
        filename = f"{uuid.uuid4()}.{format}"
        file_path = Path(settings.AUDIO_STORAGE_PATH) / filename
        async with aiofiles.open(str(file_path), "wb") as f:
            await f.write(audio)
        return f"{settings.AUDIO_CDN_BASE_URL.rstrip('/')}/{filename}"

    async def close(self):
        pass
