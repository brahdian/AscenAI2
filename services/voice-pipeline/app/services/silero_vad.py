"""
Silero VAD — Official LiveKit Plugin Wrapper.
Provides production-grade speech detection without connecting to LiveKit servers.
"""
import asyncio
from typing import Optional, AsyncIterator
from livekit.plugins import silero
from livekit import rtc
from app.core.config import settings
import structlog

logger = structlog.get_logger(__name__)

# Re-export types for compatibility with the rest of our pipeline
from livekit.agents.vad import VADEventType, VADEvent

class SileroVAD:
    """
    Local engine for Silero VAD.
    Initializes the official LiveKit Silero plugin in standalone mode.
    """
    
    def __init__(self):
        self._vad: Optional[silero.VAD] = None
        self._lock = asyncio.Lock()

    async def initialize(self):
        """Lazy-loader for the ONNX model."""
        if self._vad:
            return
        async with self._lock:
            if self._vad:
                return
            try:
                # Creates the official VAD object (downloads ONNX model if missing)
                self._vad = silero.VAD.load(
                    min_speech_duration=settings.SILERO_VAD_MIN_SPEECH_MS / 1000,
                    min_silence_duration=settings.SILERO_VAD_MIN_SILENCE_MS / 1000,
                    activation_threshold=settings.SILERO_VAD_THRESHOLD,
                    sample_rate=settings.SAMPLE_RATE # 16000
                )
                logger.info("silero_vad_initialized", provider="livekit-plugins-silero")
            except Exception as e:
                logger.error("silero_vad_init_failed", error=str(e))
                raise

    def stream(self) -> "SileroVADStream":
        """Creates a stateful stream for a single session."""
        if not self._vad:
            raise RuntimeError("SileroVAD not initialized. Call initialize() first.")
        return SileroVADStream(self._vad.stream())

class SileroVADStream:
    """
    Wraps the official LiveKit VADStream to accept raw bytes and yield events.
    """
    def __init__(self, stream):
        self._stream = stream
        self._event_queue = asyncio.Queue()
        # The official stream runs its own internal task
        asyncio.create_task(self._monitor())

    def push_frame(self, pcm_bytes: bytes, sample_rate: int = 16000):
        """Accepts raw PCM bytes, wraps them in AudioFrame, and pushes to VAD."""
        frame = rtc.AudioFrame(
            data=pcm_bytes,
            sample_rate=sample_rate,
            num_channels=1,
            samples_per_channel=len(pcm_bytes) // 2
        )
        self._stream.push_frame(frame)

    async def _monitor(self):
        """Drains events from the official stream into our queue."""
        async for event in self._stream:
            self._event_queue.put_nowait(event)

    async def events(self) -> AsyncIterator[VADEvent]:
        """Iterate over VAD events (START_OF_SPEECH, END_OF_SPEECH)."""
        while True:
            yield await self._event_queue.get()

# Global Singleton
_vad_instance = SileroVAD()

async def get_silero_vad() -> SileroVAD:
    if not _vad_instance._vad:
        await _vad_instance.initialize()
    return _vad_instance
