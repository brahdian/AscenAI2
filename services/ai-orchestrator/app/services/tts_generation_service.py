"""
TTS Generation Service — pre-generates voice greeting and IVR prompt audio.

Flow:
  1. LLM enrichment  — add natural speech pauses / pacing to the raw text
  2. Synthesis call  — POST to voice-pipeline /voice/tts → raw MP3 bytes
  3. Persist         — write to local storage, return CDN URL

Called at agent create/update time (not per-call), so latency is acceptable
and the audio file is ready before the first caller arrives.
"""
from __future__ import annotations

import os
import uuid
import structlog
from pathlib import Path
from typing import Optional

import httpx

from app.core.config import settings

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# LLM enrichment prompt
# ---------------------------------------------------------------------------

_ENRICH_SYSTEM = """\
You are a voice-script editor for a professional telephone IVR system.
Your only task is to lightly rewrite the provided script so it sounds natural
when spoken aloud by a text-to-speech engine.

Rules:
- Keep the meaning exactly the same. Do not add, remove, or paraphrase information.
- Add a comma after every natural breath pause (e.g. "Thank you for calling, Acme Corp.").
- Use "..." for a slightly longer pause where the speaker would let an idea land.
- Keep sentences short — 20 words maximum each.
- Never add bullet points, numbers, markdown, or HTML.
- Never invent content not present in the original.
- Return ONLY the rewritten script — no explanation, no preamble.
"""

_ENRICH_MAX_TOKENS = 400
_ENRICH_TEMPERATURE = 0.3  # low creativity — punctuation touch-ups only

# ---------------------------------------------------------------------------
# Storage paths (fallback to env; overridden when instantiated from agents.py)
# ---------------------------------------------------------------------------

_DEFAULT_STORAGE_PATH = os.environ.get("GREETING_AUDIO_PATH", "/tmp/voice-greetings")
_DEFAULT_CDN_BASE = os.environ.get("GREETING_CDN_BASE", "/agent-greetings")


class TTSGenerationService:
    """
    Generates pre-rendered TTS audio files for agent voice greetings and IVR
    language-selection prompts.
    """

    def __init__(
        self,
        voice_pipeline_url: str = "",
        storage_path: str = "",
        cdn_base: str = "",
    ):
        self.voice_pipeline_url = (
            voice_pipeline_url
            or getattr(settings, "VOICE_PIPELINE_URL", "http://voice-pipeline:8003")
        ).rstrip("/")
        self.storage_path = Path(storage_path or _DEFAULT_STORAGE_PATH)
        self.cdn_base = (cdn_base or _DEFAULT_CDN_BASE).rstrip("/")

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    async def generate_greeting(
        self,
        text: str,
        voice_id: str = "alloy",
        agent_id: str = "",
        enrich: bool = True,
    ) -> Optional[str]:
        """
        Generate and save TTS audio for a voice greeting.

        Args:
            text:     Greeting text from the UI (greeting_message field).
            voice_id: TTS voice identifier (provider-dependent).
            agent_id: Agent UUID — embedded in the filename for traceability.
            enrich:   When True, the LLM adds natural speech pauses before synthesis.

        Returns:
            CDN URL for the generated audio file, or None on failure.
        """
        return await self._generate(
            text=text,
            voice_id=voice_id,
            filename_hint=f"greeting_{agent_id}",
            enrich=enrich,
        )

    async def generate_ivr_prompt(
        self,
        text: str,
        voice_id: str = "alloy",
        agent_id: str = "",
        enrich: bool = True,
    ) -> Optional[str]:
        """
        Generate and save TTS audio for an IVR language-selection prompt.

        Returns:
            CDN URL for the generated audio file, or None on failure.
        """
        return await self._generate(
            text=text,
            voice_id=voice_id,
            filename_hint=f"ivr_{agent_id}",
            enrich=enrich,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _generate(
        self,
        text: str,
        voice_id: str,
        filename_hint: str,
        enrich: bool,
    ) -> Optional[str]:
        if not text or not text.strip():
            return None

        speech_text = await self._enrich_for_speech(text) if enrich else text
        return await self._synthesize_and_save(
            text=speech_text,
            voice_id=voice_id,
            filename_hint=filename_hint,
        )

    async def _enrich_for_speech(self, text: str) -> str:
        """
        Call the LLM to add natural speech punctuation cues.
        Falls back to the original text on any error so synthesis always proceeds.
        """
        try:
            from app.services.llm_client import LLMClient  # lazy import — avoid circular deps

            llm = LLMClient(
                provider=settings.LLM_PROVIDER,
                model=settings.GEMINI_MODEL,
                api_key=settings.GEMINI_API_KEY,
            )
            messages = [
                {"role": "user", "content": text},
            ]
            response = await llm.complete(
                messages=messages,
                temperature=_ENRICH_TEMPERATURE,
                max_tokens=_ENRICH_MAX_TOKENS,
            )
            # LLMResponse.content holds the text; fall back if empty
            enriched = getattr(response, "content", None) or ""
            if enriched.strip():
                logger.info(
                    "tts_enrichment_complete",
                    original_len=len(text),
                    enriched_len=len(enriched),
                )
                return enriched.strip()
        except Exception as exc:
            logger.warning("tts_enrichment_failed", error=str(exc))

        return text

    async def _synthesize_and_save(
        self,
        text: str,
        voice_id: str,
        filename_hint: str,
    ) -> Optional[str]:
        """
        POST to voice-pipeline /voice/tts and persist the returned audio.
        Returns the CDN URL, or None on failure.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.voice_pipeline_url}/voice/tts",
                    json={
                        "text": text,
                        "voice_id": voice_id,
                        "format": "mp3",
                        "speed": 1.0,
                    },
                    headers={
                        # The voice-pipeline validates X-Tenant-ID for all requests.
                        # We use "internal" here as this is a server-to-server call.
                        "X-Tenant-ID": "internal",
                        "X-Internal-Key": getattr(settings, "INTERNAL_API_KEY", ""),
                    },
                )
                resp.raise_for_status()
                audio_bytes = resp.content
        except Exception as exc:
            logger.error("tts_synthesis_request_failed", error=str(exc))
            return None

        if not audio_bytes:
            logger.warning("tts_synthesis_empty_response", hint=filename_hint)
            return None

        # Persist to local storage
        self.storage_path.mkdir(parents=True, exist_ok=True)
        file_uuid = uuid.uuid4()
        filename = f"{filename_hint}_{file_uuid}.mp3"
        filepath = self.storage_path / filename

        try:
            filepath.write_bytes(audio_bytes)
            logger.info(
                "tts_audio_saved",
                filename=filename,
                bytes=len(audio_bytes),
            )
        except Exception as exc:
            logger.error("tts_audio_save_failed", error=str(exc))
            return None

        return f"{self.cdn_base}/{filename}"
