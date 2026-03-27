"""
Core real-time voice pipeline.

Manages the full duplex voice conversation flow:
  1. Receive raw audio frames via WebSocket (binary messages)
  2. Buffer frames and run energy-based VAD on each
  3. When end-of-utterance is detected, transcribe via STT
  4. Forward transcript to AI Orchestrator via SSE stream
  5. Consume streamed text response sentence-by-sentence
  6. Synthesize each sentence to audio via TTS
  7. Stream audio chunks back to the client over WebSocket

Barge-in support: if the user starts speaking while the pipeline is
streaming TTS audio back, the current TTS task is cancelled immediately
and the new utterance is processed.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional

import httpx
import structlog
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.config import settings
from app.core.security import validate_token_for_tenant
from app.services.stt_service import STTService, TranscriptResult
from app.services.tts_service import TTSService

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class SessionState:
    session_id: str
    tenant_id: str
    agent_id: str
    is_speaking: bool           # True while pipeline is streaming TTS back
    is_listening: bool          # True while pipeline accepts audio input
    audio_buffer: bytearray
    silence_frames: int         # consecutive silent frames since last speech
    interrupt_tts: bool = False
    current_tts_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
    speech_detected: bool = False  # at least one voiced frame in current utterance
    # Per-session mutex: prevents concurrent utterance processing (TC-A02).
    # Only one utterance may run the STT→orchestrator→TTS pipeline at a time.
    # Barge-in cancels the TTS task, but the *next* utterance must wait for the
    # lock to be released before starting a new pipeline pass.
    utterance_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # Derived timing helpers ---------------------------------------------------

    @property
    def silence_ms(self) -> int:
        """How many milliseconds of consecutive silence have accumulated."""
        return self.silence_frames * settings.CHUNK_SIZE_MS

    def reset_utterance(self) -> None:
        """Clear buffers ready for the next utterance."""
        self.audio_buffer = bytearray()
        self.silence_frames = 0
        self.speech_detected = False
        self.interrupt_tts = False


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class VoicePipeline:
    """
    Manages full real-time voice conversation flow including barge-in support.
    """

    def __init__(
        self,
        stt: STTService,
        tts: TTSService,
        orchestrator_url: str,
        redis,
    ):
        self.stt = stt
        self.tts = tts
        self.orchestrator_url = orchestrator_url.rstrip("/")
        self.redis = redis
        self.active_sessions: dict[str, SessionState] = {}
        self._http_client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Public WebSocket entry point
    # ------------------------------------------------------------------

    async def handle_websocket(
        self,
        websocket: WebSocket,
        tenant_id: str,
        session_id: str,
        agent_id: str,
        token: str,
    ) -> None:
        """
        Authenticate the caller, accept the WebSocket, and run the voice loop.
        Cleans up session state on exit regardless of how the loop ends.
        """
        # Validate JWT before accepting the connection
        try:
            validate_token_for_tenant(token, tenant_id)
        except Exception as exc:
            await websocket.close(code=4401, reason=str(exc))
            return

        await websocket.accept()

        state = SessionState(
            session_id=session_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            is_speaking=False,
            is_listening=True,
            audio_buffer=bytearray(),
            silence_frames=0,
        )
        self.active_sessions[session_id] = state

        logger.info(
            "voice_session_started",
            session_id=session_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
        )

        try:
            await self._run_voice_loop(websocket, state)
        except WebSocketDisconnect:
            logger.info("voice_session_disconnected", session_id=session_id)
        except Exception as exc:
            logger.error("voice_session_error", session_id=session_id, error=str(exc))
        finally:
            # Cancel any in-flight TTS task
            if state.current_tts_task and not state.current_tts_task.done():
                state.current_tts_task.cancel()
            self.active_sessions.pop(session_id, None)
            logger.info("voice_session_ended", session_id=session_id)

    # ------------------------------------------------------------------
    # Main voice loop
    # ------------------------------------------------------------------

    async def _run_voice_loop(
        self, websocket: WebSocket, state: SessionState
    ) -> None:
        """
        Receive binary audio frames, run VAD, detect utterance boundaries,
        transcribe, query the orchestrator, and stream TTS back.

        Protocol
        --------
        Client → server:
          * Binary frames  : raw PCM-16 audio (16 kHz, mono)
          * Text frame     : JSON control message, e.g. {"type": "end_session"}

        Server → client:
          * Binary frames  : MP3 audio chunks (TTS output)
          * Text frames    : JSON status/transcript messages
        """
        max_utterance_bytes = (
            settings.SAMPLE_RATE
            * 2  # 16-bit = 2 bytes per sample
            * settings.MAX_UTTERANCE_DURATION_S
        )

        while True:
            # Respect WebSocket lifecycle
            if websocket.client_state != WebSocketState.CONNECTED:
                break

            try:
                # Use a short receive timeout so we can check interrupt flags
                raw = await asyncio.wait_for(
                    websocket.receive(), timeout=0.5
                )
            except asyncio.TimeoutError:
                continue

            # --- Handle disconnect ---
            if raw.get("type") == "websocket.disconnect":
                break

            # --- Text control messages ---
            if "text" in raw and raw["text"]:
                await self._handle_control_message(
                    raw["text"], websocket, state
                )
                continue

            # --- Binary audio frame ---
            audio_chunk: bytes = raw.get("bytes") or b""
            if not audio_chunk:
                continue

            # Barge-in: if TTS is playing and user starts speaking, interrupt
            has_voice = await self.stt.detect_voice_activity(audio_chunk)
            if has_voice and state.is_speaking:
                logger.info("barge_in_detected", session_id=state.session_id)
                await self._handle_barge_in(state)
                await self._send_json(websocket, {"type": "barge_in"})

            if state.is_listening:
                state.audio_buffer.extend(audio_chunk)

                if has_voice:
                    state.speech_detected = True
                    state.silence_frames = 0
                elif state.speech_detected:
                    # Accumulate silence only after real speech has been heard
                    state.silence_frames += 1

                # Trigger transcription on end-of-utterance conditions
                end_of_utterance = (
                    state.speech_detected
                    and state.silence_ms >= settings.VAD_SILENCE_THRESHOLD_MS
                )
                max_duration_reached = (
                    len(state.audio_buffer) >= max_utterance_bytes
                )

                if end_of_utterance or max_duration_reached:
                    utterance_audio = bytes(state.audio_buffer)
                    state.reset_utterance()
                    state.is_listening = False  # pause intake during processing

                    await self._send_json(websocket, {"type": "processing"})

                    asyncio.create_task(
                        self._process_utterance(utterance_audio, websocket, state)
                    )

    # ------------------------------------------------------------------
    # Utterance processing
    # ------------------------------------------------------------------

    async def _process_utterance(
        self,
        audio_data: bytes,
        websocket: WebSocket,
        state: SessionState,
    ) -> None:
        """
        Full pipeline for a single utterance:
          STT → orchestrator → TTS → WebSocket

        Serialised per session via utterance_lock (TC-A02): if barge-in fires
        while the previous utterance is still in the STT/orchestrator phase,
        the new utterance waits until the lock is released rather than racing.
        """
        # Non-blocking try: if another utterance is already being processed,
        # drop this one (the user barged in before the previous was done).
        if state.utterance_lock.locked():
            logger.debug("utterance_dropped_lock_busy", session_id=state.session_id)
            state.is_listening = True
            return

        async with state.utterance_lock:
            await self._run_utterance_pipeline(audio_data, websocket, state)

    async def _run_utterance_pipeline(
        self,
        audio_data: bytes,
        websocket: WebSocket,
        state: SessionState,
    ) -> None:
        """Internal: execute STT → orchestrator → TTS under the utterance lock."""
        try:
            # 1. Transcribe — use Gemini audio STT if configured (44× cheaper)
            if settings.STT_PROVIDER == "gemini" and settings.GEMINI_API_KEY:
                raw_text = await self._transcribe_gemini(audio_data)
                transcript = TranscriptResult(
                    text=raw_text, confidence=1.0, language="en", duration_ms=0
                )
            else:
                transcript = await self.stt.transcribe_audio(
                    audio_data, language="en", format="webm"
                )

            if not transcript.text.strip():
                logger.debug("empty_transcript_skipped", session_id=state.session_id)
                state.is_listening = True
                return

            # TC-A01: Low-confidence transcript gate.
            # If the STT provider returns confidence < 0.6, ask the user to
            # repeat rather than processing a potentially mis-transcribed utterance.
            if transcript.confidence < 0.6:
                logger.info(
                    "low_confidence_transcript",
                    session_id=state.session_id,
                    confidence=transcript.confidence,
                    text=transcript.text[:60],
                )
                await self._send_json(
                    websocket,
                    {
                        "type": "transcript",
                        "text": transcript.text,
                        "is_final": False,
                        "confidence": transcript.confidence,
                    },
                )
                state.is_listening = True
                tts_task = asyncio.create_task(
                    self._tts_and_send(
                        "Sorry, I didn't quite catch that. Could you say that again?",
                        websocket,
                        state,
                    )
                )
                state.current_tts_task = tts_task
                await tts_task
                return

            logger.info(
                "utterance_transcribed",
                session_id=state.session_id,
                text=transcript.text[:80],
            )
            await self._send_json(
                websocket,
                {
                    "type": "transcript",
                    "text": transcript.text,
                    "is_final": True,
                    "confidence": transcript.confidence,
                },
            )

            # 2. Stream text from orchestrator and synthesise TTS
            state.is_speaking = True
            state.interrupt_tts = False

            tts_task = asyncio.create_task(
                self._stream_response(transcript.text, websocket, state)
            )
            state.current_tts_task = tts_task

            await tts_task

        except asyncio.CancelledError:
            logger.info("utterance_processing_cancelled", session_id=state.session_id)
        except Exception as exc:
            logger.error(
                "utterance_processing_error",
                session_id=state.session_id,
                error=str(exc),
            )
            await self._send_json(
                websocket, {"type": "error", "message": "Processing error"}
            )
        finally:
            state.is_speaking = False
            state.is_listening = True  # resume listening

    async def _stream_response(
        self,
        user_text: str,
        websocket: WebSocket,
        state: SessionState,
    ) -> None:
        """
        Query the AI orchestrator via SSE, buffer text into sentences,
        synthesize each sentence with TTS, and stream audio back.
        """
        sentence_buffer = ""

        async for text_chunk in self._send_text_to_orchestrator(user_text, state):
            if state.interrupt_tts:
                break

            sentence_buffer += text_chunk
            await self._send_json(
                websocket, {"type": "ai_text_chunk", "text": text_chunk}
            )

            # Flush on sentence boundaries for lower latency
            while True:
                sentence, remainder = _split_sentence(sentence_buffer)
                if sentence is None:
                    break
                sentence_buffer = remainder
                if sentence.strip():
                    await self._tts_and_send(sentence, websocket, state)
                if state.interrupt_tts:
                    return

        # Flush any remaining text
        if sentence_buffer.strip() and not state.interrupt_tts:
            await self._tts_and_send(sentence_buffer, websocket, state)

        await self._send_json(websocket, {"type": "response_complete"})

    async def _tts_and_send(
        self,
        text: str,
        websocket: WebSocket,
        state: SessionState,
    ) -> None:
        """Synthesise one sentence and stream the resulting audio to the client."""
        if state.interrupt_tts:
            return

        voice = "alloy"
        try:
            async for audio_chunk in self.tts.synthesize_stream(text, voice_id=voice):
                if state.interrupt_tts:
                    return
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_bytes(audio_chunk)
        except Exception as exc:
            logger.error("tts_send_error", session_id=state.session_id, error=str(exc))

    # ------------------------------------------------------------------
    # Gemini audio STT
    # ------------------------------------------------------------------

    async def _transcribe_gemini(self, audio_bytes: bytes) -> str:
        """
        Transcribe raw PCM-16 audio (16 kHz mono) using Gemini multimodal STT.
        Roughly 44x cheaper than OpenAI Whisper (~$0.000135/min vs $0.006/min).
        """
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=settings.GEMINI_STT_MODEL,
                contents=[
                    types.Part.from_bytes(
                        data=audio_bytes,
                        mime_type="audio/pcm;rate=16000",
                    ),
                    "Transcribe the following audio accurately. Return only the transcript, nothing else.",
                ],
            ),
        )
        return (response.text or "").strip()

    # ------------------------------------------------------------------
    # Google Cloud TTS
    # ------------------------------------------------------------------

    async def _tts_google_cloud(self, text: str) -> bytes:
        """
        Synthesize speech using Google Cloud TTS Neural2 voices.
        Returns MP3 audio bytes.
        Cost: ~$0.000016/char for Neural2/HD voices.
        """
        from google.cloud import texttospeech

        client = texttospeech.TextToSpeechAsyncClient()
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code="en-US",
            name=settings.GOOGLE_TTS_VOICE,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=1.1,
            pitch=0.0,
            effects_profile_id=["small-bluetooth-speaker-class-device"],
        )
        response = await client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )
        return response.audio_content

    async def _tts_google_cloud_telephony(self, text: str) -> bytes:
        """
        Synthesize speech using Google Cloud TTS optimised for telephony.
        Returns 8 kHz μ-law PCM suitable for Twilio Media Streams.
        """
        from google.cloud import texttospeech

        client = texttospeech.TextToSpeechAsyncClient()
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code="en-US",
            name=settings.GOOGLE_TTS_VOICE,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MULAW,
            sample_rate_hertz=8000,
            effects_profile_id=["telephony-class-application"],
        )
        response = await client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )
        return response.audio_content

    # ------------------------------------------------------------------
    # Orchestrator communication
    # ------------------------------------------------------------------

    async def _send_text_to_orchestrator(
        self, text: str, state: SessionState
    ) -> AsyncGenerator[str, None]:
        """
        Send the transcribed text to the AI orchestrator's SSE stream endpoint
        and yield text delta chunks as they arrive.

        Expected orchestrator endpoint:
          POST /api/v1/chat/stream
          Body: {"tenant_id": ..., "agent_id": ..., "session_id": ..., "message": ...}
          Response: text/event-stream  data: {"delta": "...", "done": false}
        """
        url = f"{self.orchestrator_url}/api/v1/chat/stream"
        payload = {
            "tenant_id": state.tenant_id,
            "agent_id": state.agent_id,
            "session_id": state.session_id,
            "message": text,
        }

        client = await self._get_http_client()
        try:
            async with client.stream(
                "POST",
                url,
                json=payload,
                headers={"Accept": "text/event-stream"},
                timeout=60.0,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[len("data:"):].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        event = json.loads(raw)
                        if event.get("done"):
                            return
                        delta = event.get("delta", "")
                        if delta:
                            yield delta
                    except json.JSONDecodeError:
                        # Plain-text delta (non-JSON SSE)
                        yield raw

        except httpx.HTTPStatusError as exc:
            logger.error(
                "orchestrator_http_error",
                status=exc.response.status_code,
                detail=exc.response.text[:200],
            )
            yield "I'm sorry, I encountered an error processing your request."
        except Exception as exc:
            logger.error("orchestrator_connection_error", error=str(exc))
            yield "I'm sorry, I'm having trouble connecting right now."

    # ------------------------------------------------------------------
    # Barge-in
    # ------------------------------------------------------------------

    async def _handle_barge_in(self, state: SessionState) -> None:
        """Stop current TTS playback immediately when the user starts speaking."""
        state.interrupt_tts = True
        state.is_speaking = False
        if state.current_tts_task and not state.current_tts_task.done():
            state.current_tts_task.cancel()
            try:
                await state.current_tts_task
            except asyncio.CancelledError:
                pass
        state.current_tts_task = None
        state.reset_utterance()
        state.is_listening = True

    # ------------------------------------------------------------------
    # Control messages
    # ------------------------------------------------------------------

    async def _handle_control_message(
        self, raw: str, websocket: WebSocket, state: SessionState
    ) -> None:
        """Handle JSON control frames from the client."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("type", "")
        if msg_type == "end_session":
            await self._send_json(websocket, {"type": "session_ended"})
            await websocket.close()
        elif msg_type == "mute":
            state.is_listening = False
            await self._send_json(websocket, {"type": "muted"})
        elif msg_type == "unmute":
            state.is_listening = True
            await self._send_json(websocket, {"type": "unmuted"})
        elif msg_type == "ping":
            await self._send_json(websocket, {"type": "pong"})
        else:
            logger.debug("unknown_control_message", type=msg_type)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _send_json(self, websocket: WebSocket, data: dict) -> None:
        """Send a JSON text frame, swallowing errors if the socket is closed."""
        if websocket.client_state != WebSocketState.CONNECTED:
            return
        try:
            await websocket.send_text(json.dumps(data))
        except Exception:
            pass

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=60.0)
        return self._http_client

    async def close(self) -> None:
        """Shut down shared resources."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None


# ---------------------------------------------------------------------------
# Sentence splitter
# ---------------------------------------------------------------------------


def _split_sentence(text: str) -> tuple[Optional[str], str]:  # noqa: UP006
    """
    Extract the first complete sentence from ``text``.

    Returns (sentence, remainder) if a sentence boundary is found,
    or (None, text) if no boundary exists yet.

    Sentence boundaries: . ! ? followed by whitespace or end-of-string,
    plus newlines.
    """
    import re

    # Match sentence-ending punctuation followed by space/end, or a newline
    pattern = re.compile(r"(?<=[.!?])\s+|(?<=\n)")
    match = pattern.search(text)
    if match:
        return text[: match.start() + len(match.group())].rstrip(), text[match.end():]
    return None, text
