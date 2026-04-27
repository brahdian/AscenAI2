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
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncGenerator, Optional

from pydantic import BaseModel, Field

import httpx
import structlog
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.config import settings
from app.core.security import validate_token_for_tenant
from app.services.stt_service import STTService, TranscriptResult
from app.services.tts_service import TTSService

# Phase 1: Neural VAD & Audio Foundation (ported from livekit-plugins-silero)
from app.services.silero_vad import SileroVAD, SileroVADStream, VADEventType, get_silero_vad
from app.services.audio_processor import AudioProcessor

# Phase 2: Transcription Scrubbing
from app.services.transcription_scrubber import TranscriptBuffer

# Phase 3: Interrupt State Machine
from app.services.interrupt_state_machine import InterruptStateMachine, PipelineState

# Phase 4: Latency Telemetry
from app.services.latency_tracker import LatencyTracker

# Unified Orchestration: In-process Brain (replaces HTTP SSE hop for voice)
try:
    from shared.orchestration.voice_bridge import VoiceOrchestrator
    _VOICE_ORCHESTRATOR_AVAILABLE = True
except ImportError:
    VoiceOrchestrator = None  # type: ignore[assignment,misc]
    _VOICE_ORCHESTRATOR_AVAILABLE = False

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# PII redaction helper — strip PII from log messages before emitting
# Uses Presidio when available (50+ entity types); regex fallback otherwise.
# ---------------------------------------------------------------------------
import re as _re

_EMAIL_RE = _re.compile(r'\b[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}\b')
_PHONE_RE = _re.compile(r'\b(\+?[\d][\d\s\-().]{7,}\d)\b')
_CARD_RE  = _re.compile(r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b')

_presidio_redact = None


def _redact_pii(text: str) -> str:
    """Replace PII with safe placeholders. Presidio-backed with regex fallback."""
    global _presidio_redact
    if _presidio_redact is None:
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_anonymizer import AnonymizerEngine
            from presidio_anonymizer.entities import OperatorConfig
            _analyzer = AnalyzerEngine()
            _anon = AnonymizerEngine()

            def _presidio_fn(t: str) -> str:
                results = _analyzer.analyze(text=t, language="en",
                                            score_threshold=0.6)
                if not results:
                    return t
                return _anon.anonymize(
                    text=t, analyzer_results=results,
                    operators={"DEFAULT": OperatorConfig(
                        "replace", {"new_value": lambda r: f"[{r.entity_type}]"}
                    )},
                ).text

            _presidio_redact = _presidio_fn
        except Exception:
            _presidio_redact = False  # mark as unavailable

    if _presidio_redact:
        try:
            return _presidio_redact(text)
        except Exception:
            pass

    # Regex fallback
    text = _EMAIL_RE.sub('[EMAIL_ADDRESS]', text)
    text = _PHONE_RE.sub('[PHONE_NUMBER]', text)
    text = _CARD_RE.sub('[CREDIT_CARD]', text)
    return text


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Backchannel filler phrases (pre-synthesised once at startup → $0 runtime cost)
# ---------------------------------------------------------------------------

_BACKCHANNEL_PHRASES: list[str] = [
    "Mm-hmm.",
    "I see.",
    "Go on.",
    "Right.",
    "Okay.",
    "Sure.",
    "Of course.",
    "Understood.",
]

# How long (seconds) the user must be speaking before we emit a backchannel.
_BACKCHANNEL_TRIGGER_S: float = 1.5
# Minimum gap (seconds) between backchannels within a single session.
_BACKCHANNEL_COOLDOWN_S: float = 5.0


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
    utterance_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # VULN-032 FIX: Rate limiting on utterance processing
    utterance_timestamps: list[float] = field(default_factory=list)

    # Per-session agent configuration (persisted after first fetch)
    agent_config: Optional[dict] = None

    # Backchannel state
    speech_started_at: float = 0.0
    last_backchannel_at: float = 0.0
    backchannel_sent: bool = False

    # Twilio Telephony Integration
    twilio_stream_sid: Optional[str] = None
    call_sid: Optional[str] = None
    caller_phone: Optional[str] = None
    started_at: float = 0.0
    extension_map: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Phase 1: Neural VAD stream (per-session official Silero state)
    # ------------------------------------------------------------------
    vad_stream: Optional["VADStreamWrapper"] = None

    # Phase 1: Stateful Resampler (LiveKit RTC)
    audio_processor: Optional["AudioProcessor"] = None

    # Phase 2: Transcription scrubbing buffer (per-session)
    transcript_buffer: Optional["TranscriptBuffer"] = None

    # Phase 3: Interrupt state machine (per-session)
    fsm: Optional["InterruptStateMachine"] = None

    # Unified Brain: in-process VoiceOrchestrator (eliminates HTTP SSE hop)
    voice_orchestrator: Optional[object] = None

    # Partial frame buffer — stores <512 samples that don't fill a Silero frame yet
    _partial_frame: bytes = field(default_factory=bytes)

    # Derived timing helpers

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
        self.speech_started_at = 0.0
        self.backchannel_sent = False
        self._partial_frame = b""
        if self.transcript_buffer:
            self.transcript_buffer.reset()



class VoiceSessionRedisModel(BaseModel):
    session_id: str
    tenant_id: str
    agent_id: str
    twilio_stream_sid: Optional[str] = None
    call_sid: Optional[str] = None
    caller_phone: Optional[str] = None
    started_at: float
    agent_config: Optional[dict] = None
    extension_map: dict = Field(default_factory=dict)
    
    @classmethod
    def from_session_state(cls, state: SessionState) -> "VoiceSessionRedisModel":
        return cls(
            session_id=state.session_id,
            tenant_id=state.tenant_id,
            agent_id=state.agent_id,
            twilio_stream_sid=state.twilio_stream_sid,
            call_sid=state.call_sid,
            caller_phone=state.caller_phone,
            started_at=state.started_at,
            agent_config=state.agent_config,
            extension_map=state.extension_map,
        )

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

    async def _snapshot_session(self, state: SessionState) -> None:
        """Persist session metadata to Redis for externalization/telemetry."""
        if not self.redis:
            return
        try:
            model = VoiceSessionRedisModel.from_session_state(state)
            await self.redis.setex(
                f"voice_session:{state.session_id}",
                3600,
                model.model_dump_json()
            )
        except Exception as e:
            logger.warning("voice_session_snapshot_failed", session_id=state.session_id, error=str(e))

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

        # Phase 1: Initialize AudioProcessor per-session (stateful)
        # Twilio sends 8kHz, we want 16kHz
        processor = AudioProcessor(input_rate=8000, output_rate=16000)

        # Phase 1: Initialize Silero VAD
        vad = None
        if settings.SILERO_VAD_ENABLED:
            vad = await get_silero_vad()

        # Phase 2: Transcription scrubber per-session
        transcript_buf = TranscriptBuffer(session_id=session_id)

        # Phase 3: Interrupt state machine per-session
        fsm = InterruptStateMachine(session_id=session_id)

        # Unified Brain: initialize in-process VoiceOrchestrator if available
        voice_orc = None
        if _VOICE_ORCHESTRATOR_AVAILABLE:
            try:
                db = await self._get_db_session()
                voice_orc = VoiceOrchestrator(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    db=db,
                    redis_client=self.redis,
                )
                logger.info("voice_orchestrator_bridge_active", session_id=session_id)
            except Exception as _oe:
                logger.warning("voice_orchestrator_bridge_failed", error=str(_oe))
                voice_orc = None

        state = SessionState(
            session_id=session_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            is_speaking=False,
            is_listening=True,
            audio_buffer=bytearray(),
            silence_frames=0,
            vad_stream=vad.stream() if vad is not None else None,
            transcript_buffer=transcript_buf,
            fsm=fsm,
            audio_processor=processor,
            voice_orchestrator=voice_orc,
            started_at=time.time(),
        )

        self.active_sessions[session_id] = state

        logger.info(
            "voice_session_started",
            session_id=session_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            silero_vad=state.vad_stream is not None,
        )

        await self._snapshot_session(state)

        try:
            await self._play_greeting(websocket, state)

            menu = (state.agent_config or {}).get("ivr_dtmf_menu")
            has_menu = menu and isinstance(menu.get("entries"), list) and len(menu["entries"]) > 0
            if has_menu and not state.twilio_stream_sid:
                proceed = await self._run_dtmf_phase(websocket, state, menu)
                if not proceed:
                    return

            await self._run_voice_loop(websocket, state)
        except WebSocketDisconnect:
            logger.info("voice_session_disconnected", session_id=session_id)
        except Exception as exc:
            logger.error("voice_session_error", session_id=session_id, error=str(exc))
        finally:
            if state.current_tts_task and not state.current_tts_task.done():
                state.current_tts_task.cancel()
            self.active_sessions.pop(session_id, None)
            logger.info("voice_session_ended", session_id=session_id)
            asyncio.create_task(self._finalize_voice_session(state))


    # ------------------------------------------------------------------
    # Main voice loop
    # ------------------------------------------------------------------

    async def _run_dtmf_phase(
        self, websocket: WebSocket, state: SessionState, menu: dict
    ) -> bool:
        """
        Simulate the DTMF gathering phase over WebSocket for browser testing.
        Waits for a text message like {"type": "dtmf", "digit": "1"}.
        Returns True to proceed to AI loop, False to end the session.
        """
        timeout = menu.get("timeout_seconds", 10)
        max_retries = menu.get("max_retries", 3)
        entries = menu.get("entries", [])

        import time
        import json

        for retry_count in range(max_retries + 1):
            start_time = time.time()
            dtmf_received = False
            
            while time.time() - start_time < timeout:
                time_left = timeout - (time.time() - start_time)
                if time_left <= 0:
                    break
                    
                try:
                    raw = await asyncio.wait_for(websocket.receive(), timeout=time_left)
                except asyncio.TimeoutError:
                    break

                if raw.get("type") == "websocket.disconnect":
                    return False

                if "text" in raw and raw["text"]:
                    try:
                        ctrl = json.loads(raw["text"])
                        if ctrl.get("type") == "end_session":
                            await websocket.close(code=1000)
                            return False
                            
                        if ctrl.get("type") == "dtmf":
                            digit = ctrl.get("digit")
                            entry = next((e for e in entries if e.get("digit") == digit), None)
                            
                            if not entry:
                                # Invalid digit -> just proceed to agent for simplicity
                                return True
                                
                            action = entry.get("action")
                            if action == "proceed_to_agent":
                                return True
                            elif action == "end_call":
                                await websocket.close(code=1000)
                                return False
                            elif action == "repeat_menu":
                                await self._play_greeting(websocket, state)
                                dtmf_received = True # handled
                                break
                            elif action == "play_audio":
                                audio_url = entry.get("audio_url")
                                if audio_url:
                                    if audio_url.startswith("/"):
                                        audio_url = f"{self.orchestrator_url}{audio_url}"
                                    state.is_speaking = True
                                    try:
                                        client = await self._get_http_client()
                                        async with client.stream("GET", audio_url, timeout=10.0) as audio_resp:
                                            async for chunk in audio_resp.aiter_bytes(4096):
                                                if websocket.client_state == WebSocketState.CONNECTED:
                                                    await websocket.send_bytes(chunk)
                                    finally:
                                        state.is_speaking = False
                                        
                                after = entry.get("after_playback", "proceed_to_agent")
                                if after == "end_call":
                                    await websocket.close(code=1000)
                                    return False
                                else:
                                    return True
                    except json.JSONDecodeError:
                        pass
                
                # if we get audio bytes during DTMF simulation, we just drop them

            if dtmf_received:
                # We handled 'repeat_menu' inside the loop and broke out.
                # Continue the outer for loop to wait again.
                continue
                
            # If we get here and didn't break early, it's a timeout.
            if retry_count < max_retries:
                # Re-play prompt
                await self._play_greeting(websocket, state)
            else:
                # Exhausted
                return True

        return True

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
                text_data = raw["text"]
                try:
                    import json
                    ctrl = json.loads(text_data)
                    event_type = ctrl.get("event") or ctrl.get("type", "")

                    if event_type == "start" and "streamSid" in ctrl.get("start", {}):
                        # Twilio setup: extract stream SID so we can target audio back
                        state.twilio_stream_sid = ctrl["start"]["streamSid"]
                        start_data = ctrl["start"]
                        # Capture CallSid from customParameters or directly from start payload
                        state.call_sid = (
                            start_data.get("customParameters", {}).get("callSid")
                            or start_data.get("callSid")
                            or ctrl.get("callSid")
                        )
                        custom = start_data.get("customParameters", {}) or {}
                        state.caller_phone = (
                            custom.get("From")
                            or custom.get("from")
                            or start_data.get("from")
                        )
                        # Populate extension map from agent config if available
                        if state.agent_config:
                            state.extension_map = state.agent_config.get("escalation_extensions", {})
                        logger.info(
                            "twilio_stream_started",
                            stream_sid=state.twilio_stream_sid,
                            call_sid=state.call_sid,
                        )
                        asyncio.create_task(self._snapshot_session(state))
                        continue

                    elif event_type == "media" and "payload" in ctrl.get("media", {}):
                        # Twilio sends 8000Hz mu-law audio
                        import base64
                        payload = ctrl["media"]["payload"]
                        mulaw_bytes = base64.b64decode(payload)
                        # Convert mu-law to PCM (still 8kHz)
                        pcm8_bytes = AudioProcessor.convert_mulaw_to_pcm(mulaw_bytes)
                        # The binary handler below will resample it to 16kHz via session.audio_processor
                        raw = {"bytes": pcm8_bytes}

                    elif event_type == "stop":
                        # Twilio end of call
                        logger.info("twilio_stream_stopped", session_id=state.session_id)
                        break

                    else:
                        await self._handle_control_message(text_data, websocket, state)
                        continue
                except (json.JSONDecodeError, ImportError, ValueError):
                    pass

            # --- Binary audio frame ---
            audio_chunk: bytes = raw.get("bytes") or b""
            if not audio_chunk:
                continue

            # ------------------------------------------------------------------
            # Phase 2: Silero VAD path (if initialized) or legacy energy VAD
            # ------------------------------------------------------------------
            if state.vad_stream is not None and state.audio_processor:
                # 1. State-aware Resampling + Normalization (LiveKit RTC)
                # This ensures click-free audio even if Twilio sends tiny packets
                processed_chunk = state.audio_processor.resample_and_normalize(audio_chunk)
                if not processed_chunk:
                    continue

                # 2. Push to official VAD
                state.vad_stream.push_frame(processed_chunk, sample_rate=16000)

                # 3. Drain events
                while not state.vad_stream._event_queue.empty():
                    vad_event = state.vad_stream._event_queue.get_nowait()

                    if vad_event.type == VADEventType.START_OF_SPEECH:
                        if state.fsm and state.fsm.is_speaking:
                            await self._handle_barge_in(state, websocket)
                        state.speech_detected = True
                        state.speech_started_at = time.monotonic()
                        await self._maybe_emit_backchannel(websocket, state)
                        if state.transcript_buffer:
                            state.transcript_buffer.reset()

                    elif vad_event.type == VADEventType.END_OF_SPEECH:
                        if state.is_listening and state.speech_detected:
                            # Combine frames from the official VAD event
                            # (The SDK automatically includes the prefix padding)
                            utterance_audio = b"".join([f.data for f in vad_event.frames])
                            state.reset_utterance()
                            state.is_listening = False
                            await self._send_json(websocket, {"type": "processing"})
                            asyncio.create_task(
                                self._process_utterance(utterance_audio, websocket, state)
                            )

            else:
                # ------------------------------------------------------------------
                # Legacy energy-based VAD fallback (no Silero)
                # ------------------------------------------------------------------
                has_voice = await self.stt.detect_voice_activity(audio_chunk)

                # Phase 3 FSM: barge-in via legacy VAD
                if has_voice and state.is_speaking:
                    await self._handle_barge_in(state, websocket)

                if state.is_listening:
                    state.audio_buffer.extend(audio_chunk)

                    if has_voice:
                        if not state.speech_detected:
                            state.speech_started_at = time.monotonic()
                        state.speech_detected = True
                        state.silence_frames = 0
                        await self._maybe_emit_backchannel(websocket, state)
                    elif state.speech_detected:
                        state.silence_frames += 1

                    end_of_utterance = (
                        state.speech_detected
                        and state.silence_ms >= settings.VAD_SILENCE_THRESHOLD_MS
                    )
                    max_duration_reached = len(state.audio_buffer) >= max_utterance_bytes

                    if end_of_utterance or max_duration_reached:
                        utterance_audio = bytes(state.audio_buffer)
                        state.reset_utterance()
                        state.is_listening = False
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
        # VULN-032 FIX: Rate limit utterances per session (max 20 per minute)
        now = time.monotonic()
        state.utterance_timestamps = [t for t in state.utterance_timestamps if now - t < 60.0]
        if len(state.utterance_timestamps) >= 20:
            logger.warning("utterance_rate_limited", session_id=state.session_id, count=len(state.utterance_timestamps))
            await self._tts_and_send(
                "You're speaking too quickly. Please wait a moment before continuing.",
                websocket, state,
            )
            state.is_listening = True
            return
        state.utterance_timestamps.append(now)

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
        # Phase 4: per-turn latency tracker
        turn = len(state.utterance_timestamps)
        tracker = LatencyTracker(session_id=state.session_id, turn=turn)
        tracker.on_speech_end()  # T=0: VAD fired

        # Phase 3 FSM: transition to THINKING
        if state.fsm and state.fsm.can_transition_to(PipelineState.THINKING):
            state.fsm.transition_to(PipelineState.THINKING, reason="utterance_start")

        try:
            # 1. Transcribe
            if settings.STT_PROVIDER == "gemini" and settings.GEMINI_API_KEY:
                raw_text, detected_lang = await self._transcribe_gemini(audio_data)
                transcript = TranscriptResult(
                    text=raw_text, confidence=1.0, language=detected_lang, duration_ms=0
                )
            else:
                transcript = await self.stt.transcribe_audio(
                    audio_data, language="auto", format="webm"
                )

            tracker.on_stt_done()  # Phase 4: STT hop complete

            # Phase 2: run transcript through scrubber to remove stutter/fillers
            if state.transcript_buffer:
                clean_text = state.transcript_buffer.finalize(transcript.text)
            else:
                clean_text = transcript.text

            if not clean_text.strip():
                logger.debug("empty_transcript_skipped", session_id=state.session_id)
                if state.fsm and state.fsm.can_transition_to(PipelineState.LISTENING):
                    state.fsm.transition_to(PipelineState.LISTENING, reason="empty_transcript")
                state.is_listening = True
                return

            # TC-A01: Low-confidence gate
            if transcript.confidence < 0.6:
                logger.info(
                    "low_confidence_transcript",
                    session_id=state.session_id,
                    confidence=transcript.confidence,
                )
                await self._send_json(
                    websocket,
                    {"type": "transcript", "text": clean_text, "is_final": False, "confidence": transcript.confidence},
                )
                state.is_listening = True
                fallback_msg = (state.agent_config or {}).get("computed_fallback") or "Sorry, I didn't quite catch that. Could you say that again?"
                tts_task = asyncio.create_task(self._tts_and_send(fallback_msg, websocket, state))
                state.current_tts_task = tts_task
                await tts_task
                return

            logger.info(
                "utterance_transcribed",
                session_id=state.session_id,
                text=_redact_pii(clean_text)[:80],
            )
            await self._send_json(
                websocket,
                {"type": "transcript", "text": clean_text, "is_final": True, "confidence": transcript.confidence},
            )

            # Phase 13 (existing): Scrub PII before sending to orchestrator
            redacted_user_text = _redact_pii(clean_text)

            # Phase 3 FSM: transition to SPEAKING when TTS begins
            # (actual transition happens inside _stream_response on first audio)
            state.is_speaking = True
            state.interrupt_tts = False

            tts_task = asyncio.create_task(
                self._stream_response(
                    redacted_user_text, websocket, state,
                    detected_language=transcript.language,
                    tracker=tracker,
                )
            )
            # Phase 3 FSM: register task so FSM can cancel it on barge-in
            if state.fsm:
                state.fsm.register_tts_task(tts_task)
            state.current_tts_task = tts_task

            await tts_task

        except asyncio.CancelledError:
            logger.info("utterance_processing_cancelled", session_id=state.session_id)
        except (TimeoutError, asyncio.TimeoutError):
            logger.warning("utterance_processing_timeout", session_id=state.session_id)
            await self._tts_and_send(
                "Sorry, I'm taking too long to respond right now. Please try again.",
                websocket, state,
            )
        except Exception as exc:
            logger.error(
                "utterance_processing_error",
                session_id=state.session_id,
                error=type(exc).__name__,
            )
            await self._tts_and_send(
                "Sorry, something went wrong on my end. Could you repeat that?",
                websocket, state,
            )
        finally:
            state.is_speaking = False
            state.is_listening = True
            # Phase 3 FSM: reset after clean response
            if state.fsm:
                state.fsm.reset_after_response()
            # Phase 4: emit final latency report
            tracker.on_response_complete()
            report = tracker.report()
            tracker.emit_metrics()
            logger.info("turn_latency", **{k: v for k, v in report.items() if v is not None})


    async def _stream_response(
        self,
        user_text: str,
        websocket: WebSocket,
        state: SessionState,
        detected_language: str = "en",
        tracker: Optional["LatencyTracker"] = None,
    ) -> None:
        """
        Phase 4 Upgrade: LLM SSE → word-chunked TTS → WebSocket.

        Improvements over original:
        - Producer flushes to TTS after TTS_WORD_CHUNK_SIZE words (default 10)
          OR TTS_FORCE_CHUNK_CHARS characters — whichever comes first.
          This reduces Time-to-First-Audio from ~1 full sentence to ~10 words.
        - LatencyTracker instruments LLM TTFT and TTS TTFA per turn.
        - FSM transitions to SPEAKING on the first audio chunk sent.
        """
        sentence_queue: asyncio.Queue[Optional[str]] = asyncio.Queue(maxsize=8)
        cancel_event = asyncio.Event()

        first_token_recorded = False
        first_audio_recorded = False

        # ── Producer: LLM SSE → word-chunked sentence_queue ─────────────────
        async def _producer() -> None:
            nonlocal first_token_recorded
            text_buffer = ""
            try:
                async for text_chunk in self._send_text_to_orchestrator(
                    user_text, state, detected_language=detected_language
                ):
                    if cancel_event.is_set() or state.interrupt_tts:
                        break

                    # Phase 4: track first LLM token
                    if tracker and not first_token_recorded:
                        tracker.on_llm_first_token()
                        first_token_recorded = True

                    text_buffer += text_chunk
                    await self._send_json(
                        websocket, {"type": "ai_text_chunk", "text": text_chunk}
                    )

                    # Phase 4: Flush on sentence boundary OR word/char threshold
                    while True:
                        # 1. Try sentence split first (cleanest boundary)
                        sentence, remainder = _split_sentence(text_buffer)
                        if sentence is not None:
                            text_buffer = remainder
                            if sentence.strip():
                                await sentence_queue.put(sentence.strip())
                            if cancel_event.is_set() or state.interrupt_tts:
                                return
                            continue

                        # 2. If no sentence boundary yet, check word/char threshold
                        word_count = len(text_buffer.split())
                        if (
                            word_count >= settings.TTS_WORD_CHUNK_SIZE
                            or len(text_buffer) >= settings.TTS_FORCE_CHUNK_CHARS
                        ):
                            # Flush at last whitespace to avoid cutting mid-word
                            last_space = text_buffer.rfind(" ")
                            if last_space > 0:
                                chunk = text_buffer[:last_space].strip()
                                text_buffer = text_buffer[last_space + 1:]
                            else:
                                chunk = text_buffer.strip()
                                text_buffer = ""
                            if chunk:
                                await sentence_queue.put(chunk)
                            if cancel_event.is_set() or state.interrupt_tts:
                                return
                        break

                # Flush trailing text
                if text_buffer.strip() and not (cancel_event.is_set() or state.interrupt_tts):
                    await sentence_queue.put(text_buffer.strip())
            except asyncio.CancelledError:
                pass
            finally:
                await sentence_queue.put(None)

        # ── Consumer: sentence_queue → TTS → WebSocket ───────────────────────
        async def _consumer() -> None:
            nonlocal first_audio_recorded
            while True:
                try:
                    chunk = await asyncio.wait_for(sentence_queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    logger.warning("tts_consumer_timeout", session_id=state.session_id)
                    break

                if chunk is None:
                    break
                if cancel_event.is_set() or state.interrupt_tts:
                    while not sentence_queue.empty():
                        sentence_queue.get_nowait()
                    break

                # Phase 3 FSM: transition to SPEAKING on first TTS chunk
                if state.fsm and state.fsm.can_transition_to(PipelineState.SPEAKING):
                    state.fsm.transition_to(PipelineState.SPEAKING, reason="first_tts_chunk")

                t_start = time.monotonic()
                await self._tts_and_send(chunk, websocket, state)
                elapsed_ms = int((time.monotonic() - t_start) * 1000)

                # Phase 4: track first audio sent to client
                if tracker and not first_audio_recorded:
                    tracker.on_tts_first_audio()
                    first_audio_recorded = True

                logger.debug(
                    "tts_chunk_sent",
                    session_id=state.session_id,
                    chars=len(chunk),
                    elapsed_ms=elapsed_ms,
                )

        # ── Barge-in watcher ─────────────────────────────────────────────────
        async def _barge_in_watcher() -> None:
            while not cancel_event.is_set():
                if state.interrupt_tts:
                    cancel_event.set()
                    while not sentence_queue.empty():
                        try:
                            sentence_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    try:
                        sentence_queue.put_nowait(None)
                    except asyncio.QueueFull:
                        pass
                    return
                await asyncio.sleep(0.05)

        try:
            await asyncio.gather(
                _producer(),
                _consumer(),
                _barge_in_watcher(),
                return_exceptions=True,
            )
        finally:
            cancel_event.set()

        if not state.interrupt_tts:
            await self._send_json(websocket, {"type": "response_complete"})


    # ------------------------------------------------------------------
    # Backchannel: filler words during user speech
    # ------------------------------------------------------------------

    async def _presynthesize_backchannels(self) -> None:
        """
        Pre-synthesise all backchannel filler phrases to disk at startup.

        Files are written to ``{AUDIO_STORAGE_PATH}/backchannels/``.
        If the directory already contains all clips, this is a no-op so
        restarts are fast.  Uses the configured TTS provider so the voice
        matches the main pipeline.

        Cost: synthesised once per deployment → zero TTS API cost at runtime.
        """
        bc_dir = Path(settings.AUDIO_STORAGE_PATH) / "backchannels"
        bc_dir.mkdir(parents=True, exist_ok=True)

        for phrase in _BACKCHANNEL_PHRASES:
            filename = phrase.lower().replace(" ", "_").replace(".", "") + ".mp3"
            fpath = bc_dir / filename
            if fpath.exists():
                continue  # already synthesised
            try:
                provider = settings.TTS_PROVIDER.lower()
                if provider == "cartesia":
                    audio = await self.tts.synthesize_cartesia_to_bytes(phrase, voice_id=settings.CARTESIA_VOICE_ID)
                elif provider == "deepgram":
                    audio = await self.tts.synthesize_deepgram_to_bytes(phrase, voice_id="aura-asteria-en")
                else:
                    audio = await self.tts.synthesize(phrase, voice_id="alloy", format="mp3")
                fpath.write_bytes(audio)
                logger.info("backchannel_phrase_synthesised", phrase=phrase, path=str(fpath))
            except Exception as exc:
                logger.warning("backchannel_synthesis_skipped", phrase=phrase, error=str(exc))

    async def _maybe_emit_backchannel(
        self, websocket: WebSocket, state: SessionState
    ) -> None:
        """
        Emit a pre-synthesised filler clip if all timing guards pass.

        Guards:
          * User must have been speaking for at least ``_BACKCHANNEL_TRIGGER_S``.
          * At most one backchannel per utterance (``state.backchannel_sent``).
          * At least ``_BACKCHANNEL_COOLDOWN_S`` since the last emission
            (prevents rapid-fire fillers across short consecutive utterances).
          * Clip file must exist on disk (silently skips if pre-synthesis failed).

        The clip is sent as a separate binary frame prefixed with the single
        byte 0x02, which the client can distinguish from regular TTS audio
        (0x01) and apply optional volume ducking.
        """
        if state.backchannel_sent or not state.is_listening:
            return

        # Pre-synthesized backchannels are 44.1kHz MP3, which Twilio cannot play natively
        # without expensive live transcoding. Disable for Twilio calls to keep latency low.
        if state.twilio_stream_sid:
            return

        now = time.monotonic()
        speaking_duration = now - state.speech_started_at
        if speaking_duration < _BACKCHANNEL_TRIGGER_S:
            return

        cooldown_ok = (now - state.last_backchannel_at) >= _BACKCHANNEL_COOLDOWN_S
        if not cooldown_ok:
            return

        # Pick a random phrase and read its pre-synthesised clip
        phrase = random.choice(_BACKCHANNEL_PHRASES)
        filename = phrase.lower().replace(" ", "_").replace(".", "") + ".mp3"
        fpath = Path(settings.AUDIO_STORAGE_PATH) / "backchannels" / filename

        if not fpath.exists():
            return  # pre-synthesis hadn't completed yet for this phrase

        try:
            audio_bytes = fpath.read_bytes()
        except OSError:
            return

        # Mark sent *before* the await so concurrent VAD ticks don't double-send
        state.backchannel_sent = True
        state.last_backchannel_at = now

        from starlette.websockets import WebSocketState
        if websocket.client_state != WebSocketState.CONNECTED:
            return

        try:
            # 0x02 prefix = backchannel frame; client may apply ducking
            await websocket.send_bytes(b"\x02" + audio_bytes)
            logger.info(
                "backchannel_emitted",
                session_id=state.session_id,
                phrase=phrase,
                speaking_s=round(speaking_duration, 2),
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Greeting playback (pre-recorded audio saves TTS cost on every call)
    # ------------------------------------------------------------------

    async def _play_greeting(self, websocket: WebSocket, state: SessionState) -> None:

        """
        Fetch the agent's greeting from the orchestrator and play it.

        Cost-saving design:
          * If agent.voice_greeting_url is set → stream the static audio file
            directly (no TTS synthesis → $0 TTS cost per call; billed as storage).
          * Else if agent.greeting_message is set → TTS-synthesise it once per session.
          * Else → skip silently.
        """
        try:
            url = f"{self.orchestrator_url}/api/v1/agents/{state.agent_id}"
            headers = {"X-Tenant-ID": state.tenant_id}
            client = await self._get_http_client()
            resp = await client.get(url, headers=headers, timeout=5.0)
            if resp.status_code != 200:
                return
            agent_data = resp.json()
            state.agent_config = agent_data

            opening_audio_url: str = agent_data.get("opening_audio_url") or ""
            voice_greeting_url: str = agent_data.get("voice_greeting_url") or ""
            greeting_text: str = agent_data.get("greeting_message") or ""
            computed_greeting: str = agent_data.get("computed_greeting") or ""

            agent_config = agent_data.get("agent_config") or {}
            ivr_language_url: str = agent_config.get("ivr_language_url") or ""
            ivr_language_prompt: str = agent_config.get("ivr_language_prompt") or ""

            # Prioritize explicitly generated Voice Greetings
            audio_to_play = ivr_language_url or voice_greeting_url or opening_audio_url

            if audio_to_play:
                if audio_to_play.startswith("/"):
                    audio_to_play = f"{self.orchestrator_url}{audio_to_play}"
                
                logger.info("playing_prerecorded_greeting", session_id=state.session_id, url=audio_to_play)
                state.is_speaking = True
                try:
                    async with client.stream("GET", audio_to_play, timeout=10.0) as audio_resp:
                        async for chunk in audio_resp.aiter_bytes(4096):
                            if websocket.client_state == WebSocketState.CONNECTED:
                                await websocket.send_bytes(chunk)
                finally:
                    state.is_speaking = False
                await self._send_json(websocket, {"type": "greeting_complete"})

            elif ivr_language_prompt:
                # Voice Greeting (JIT Synthesis)
                logger.info("synthesising_ivr_greeting", session_id=state.session_id)
                state.is_speaking = True
                try:
                    await self._tts_and_send(ivr_language_prompt, websocket, state)
                finally:
                    state.is_speaking = False
                await self._send_json(websocket, {"type": "greeting_complete"})

            elif computed_greeting:
                # Fallback to backend-computed opening (Highest Cost)
                logger.info("synthesising_computed_greeting", session_id=state.session_id)
                state.is_speaking = True
                try:
                    await self._tts_and_send(computed_greeting, websocket, state)
                finally:
                    state.is_speaking = False
                await self._send_json(websocket, {"type": "greeting_complete"})

            elif greeting_text:
                # Fallback to chat greeting for backwards compatibility
                logger.info("synthesising_chat_greeting", session_id=state.session_id)
                state.is_speaking = True
                try:
                    await self._tts_and_send(greeting_text, websocket, state)
                finally:
                    state.is_speaking = False
                await self._send_json(websocket, {"type": "greeting_complete"})

        except Exception as exc:
            logger.warning(
                "greeting_playback_skipped",
                session_id=state.session_id,
                error=str(exc),
            )

    async def _tts_and_send(
        self,
        text: str,
        websocket: WebSocket,
        state: SessionState,
    ) -> None:
        """Synthesise one sentence and stream the resulting audio to the client."""
        if state.interrupt_tts:
            return

        # TC-A03: Strip markdown/formatting that TTS engines read literally
        spoken_text = _strip_markdown_for_tts(text)
        if not spoken_text.strip():
            return

        try:
            # Phase 4: Use refactored Cartesia TTS stream (Sonic engine)
            audio_iter = self.tts.synthesize_stream(spoken_text)

            async for audio_chunk in audio_iter:
                if state.interrupt_tts:
                    return
                await self._emit_audio(websocket, audio_chunk, state)

            # After all audio chunks are sent, emit a Twilio mark event
            if state.twilio_stream_sid and not state.interrupt_tts:
                await self._send_json(websocket, {
                    "event": "mark",
                    "streamSid": state.twilio_stream_sid,
                    "mark": {"name": "end_of_response"},
                })
        except Exception as exc:
            logger.error("tts_send_error", session_id=state.session_id, error=str(exc))

    async def _emit_audio(self, websocket: WebSocket, audio_chunk: bytes, state: SessionState) -> None:
        """Helper to send audio correctly depending on the channel type."""
        from starlette.websockets import WebSocketState
        if websocket.client_state != WebSocketState.CONNECTED:
            return

        if state.twilio_stream_sid:
            # Twilio requires 8kHz mu-law. Cartesia plugin yields 16kHz PCM (s16le).
            import audioop
            import base64
            try:
                # 1. Downsample 16kHz -> 8kHz
                pcm8, _ = audioop.ratecv(audio_chunk, 2, 1, 16000, 8000, None)
                # 2. Encode to mu-law
                mulaw_bytes = audioop.lin2ulaw(pcm8, 2)
            except Exception:
                mulaw_bytes = audio_chunk

            payload = {
                "event": "media",
                "streamSid": state.twilio_stream_sid,
                "media": {
                    "payload": base64.b64encode(mulaw_bytes).decode("utf-8")
                }
            }
            await self._send_json(websocket, payload)
        else:
            # Browser: Send raw PCM chunks (frontend handles playback)
            await websocket.send_bytes(audio_chunk)

    # ------------------------------------------------------------------
    # Gemini audio STT
    # ------------------------------------------------------------------

    async def _transcribe_gemini(self, audio_bytes: bytes) -> tuple[str, str]:
        """
        Transcribe raw PCM-16 audio (16 kHz mono) using Gemini multimodal STT.
        Roughly 44x cheaper than OpenAI Whisper (~$0.000135/min vs $0.006/min).
        Returns (transcript_text, detected_language_code).
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
                    (
                        "Transcribe the following audio accurately. "
                        "Return ONLY a JSON object with two fields: "
                        '"transcript" (the transcription text) and '
                        '"language" (ISO 639-1 code like en, fr, zh, es). '
                        "Return nothing else."
                    ),
                ],
            ),
        )
        raw = (response.text or "").strip()
        # Attempt to parse structured JSON response; fall back to raw text
        try:
            import json as _json
            parsed = _json.loads(raw)
            transcript = parsed.get("transcript", raw).strip()
            detected_lang = parsed.get("language", "en").strip()
        except Exception:
            transcript = raw
            detected_lang = "en"
        return transcript, detected_lang

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
        self, text: str, state: SessionState, detected_language: str = "en"
    ) -> AsyncGenerator[str, None]:
        """
        Forward the transcript to the AI Brain and yield streaming text deltas.

        PRIMARY PATH (in-process): if a VoiceOrchestrator is attached to the session,
        call it directly — zero network hops, zero serialization cost.

        FALLBACK PATH (HTTP SSE): if no in-process orchestrator is available
        (e.g. model failed to load, or running in standalone mode), fall back
        to the existing HTTP SSE call to the ai-orchestrator service.
        """
        # --- PRIMARY: In-process brain ---
        if state.voice_orchestrator is not None:
            try:
                async for delta in state.voice_orchestrator.stream_response(
                    user_message=text,
                    request_id=state.session_id,
                ):
                    yield delta
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "voice_orchestrator_bridge_error_falling_back",
                    error=str(exc),
                    session_id=state.session_id,
                )
                # Fall through to HTTP path below

        # --- FALLBACK: HTTP SSE to ai-orchestrator service ---
        url = f"{self.orchestrator_url}/api/v1/chat/stream"
        payload = {
            "tenant_id": state.tenant_id,
            "agent_id": state.agent_id,
            "session_id": state.session_id,
            "message": text,
            "detected_language": detected_language,
        }

        from shared.internal_auth import generate_internal_token
        token = generate_internal_token(settings.SECRET_KEY, getattr(settings, "JWT_ALGORITHM", "HS256"))

        client = await self._get_http_client()
        try:
            async with client.stream(
                "POST",
                url,
                json=payload,
                headers={
                    "Accept": "text/event-stream",
                    "Authorization": f"Bearer {token}",
                    "X-Tenant-ID": state.tenant_id,
                },
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

    async def _handle_barge_in(self, state: SessionState, websocket: Optional[WebSocket] = None) -> None:
        """
        Phase 3: Stop TTS playback via the InterruptStateMachine when the user
        speaks over the agent.  Falls back to direct task cancellation if FSM
        is unavailable (e.g. session created without Silero).
        """
        if state.fsm:
            # FSM path: validates state, cancels TTS task, transitions to LISTENING
            await state.fsm.cancel_speaking(reason="barge_in")
            state.interrupt_tts = True
            state.is_speaking = False
            state.current_tts_task = None
            state.reset_utterance()
            state.is_listening = True
        else:
            # Legacy path
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

        # Notify Twilio to discard queued audio
        if websocket and state.twilio_stream_sid:
            await self._send_json(websocket, {
                "event": "clear",
                "streamSid": state.twilio_stream_sid,
            })
        if websocket:
            await self._send_json(websocket, {"type": "barge_in"})


    # ------------------------------------------------------------------
    # SIP REFER / Extension escalation
    # ------------------------------------------------------------------

    async def _handle_escalation_to_extension(
        self,
        websocket: WebSocket,
        state: SessionState,
        extension: str,
    ) -> None:
        """
        Transfer a Twilio call to a target extension/phone number.

        Looks up the extension in `state.extension_map` (populated from
        agent config `escalation_extensions`).  If found, uses the Twilio
        REST API to redirect the live call via a new TwiML <Dial> verb.
        Also notifies the WebSocket client about the transfer.

        Requires TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN to be configured.
        """
        extension_map: dict = state.extension_map or {}
        # Refresh from agent config if map is empty
        if not extension_map and state.agent_config:
            extension_map = state.agent_config.get("escalation_extensions", {})

        target = extension_map.get(str(extension))
        if not target:
            logger.warning(
                "escalation_extension_not_found",
                session_id=state.session_id,
                extension=extension,
            )
            await self._tts_and_send(
                "I'm sorry, I couldn't find an available agent for that extension.",
                websocket,
                state,
            )
            return

        logger.info(
            "escalation_to_extension",
            session_id=state.session_id,
            extension=extension,
            target=f"{str(target)[:3]}***{str(target)[-4:]}" if len(str(target)) > 7 else "[MASKED]",
        )

        # Notify WebSocket client (useful for browser-based voice sessions)
        await self._send_json(websocket, {
            "type": "transfer",
            "extension": extension,
            "target": target,
        })

        # If this is a Twilio call, use the REST API to redirect it
        if state.call_sid and settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
            twiml = f"<Response><Dial>{target}</Dial></Response>"
            url = (
                f"https://api.twilio.com/2010-04-01/Accounts/"
                f"{settings.TWILIO_ACCOUNT_SID}/Calls/{state.call_sid}.json"
            )
            try:
                client = await self._get_http_client()
                resp = await client.post(
                    url,
                    data={"Twiml": twiml},
                    auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
                    timeout=10.0,
                )
                if resp.status_code in (200, 201, 204):
                    logger.info(
                        "twilio_call_redirected",
                        session_id=state.session_id,
                        call_sid=state.call_sid,
                        target=f"{str(target)[:3]}***{str(target)[-4:]}" if len(str(target)) > 7 else "[MASKED]",
                    )
                else:
                    logger.error(
                        "twilio_redirect_failed",
                        session_id=state.session_id,
                        status=resp.status_code,
                        body=resp.text[:200],
                    )
            except Exception as exc:
                logger.error(
                    "twilio_redirect_error",
                    session_id=state.session_id,
                    error=str(exc),
                )
        else:
            if not state.call_sid:
                logger.debug("escalation_no_call_sid_skipping_twilio_api", session_id=state.session_id)

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
        elif msg_type in ("transfer", "escalate"):
            extension = msg.get("extension") or msg.get("target", "")
            if extension:
                await self._handle_escalation_to_extension(websocket, state, str(extension))
            else:
                logger.debug("transfer_missing_extension", msg=msg)
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

    async def _finalize_voice_session(self, state: SessionState) -> None:
        """Fire-and-forget call to ai-orchestrator's voice/finalize endpoint.

        The orchestrator decides whether the agent has CRM auto-logging enabled,
        looks up / creates the contact, and writes a Note. All errors are swallowed
        — voice teardown must never raise.
        """
        try:
            duration = int(time.time() - state.started_at) if state.started_at else None
            payload = {
                "tenant_id": state.tenant_id,
                "agent_id": state.agent_id,
                "session_id": state.session_id,
                "caller_phone": state.caller_phone,
                "duration_seconds": duration,
            }
            client = await self._get_http_client()
            headers = {"X-Internal-Key": settings.INTERNAL_API_KEY} if getattr(settings, "INTERNAL_API_KEY", "") else {}
            await client.post(
                f"{self.orchestrator_url}/api/v1/internal/voice/finalize",
                json=payload,
                headers=headers,
                timeout=10.0,
            )
        except Exception as exc:
            logger.warning("voice_finalize_post_failed", session_id=state.session_id, error=str(exc))

    async def _get_db_session(self):
        """
        Returns an AsyncSession from the voice-pipeline's DB pool.
        Used to supply a DB connection to the in-process VoiceOrchestrator.
        """
        try:
            from app.core.database import AsyncSessionLocal
            return AsyncSessionLocal()
        except ImportError:
            # DB not configured in voice-pipeline (fallback to HTTP SSE path)
            return None

    async def close(self) -> None:
        """Shut down shared resources."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None


# ---------------------------------------------------------------------------
# TC-A03: Markdown stripper for TTS
# ---------------------------------------------------------------------------

def _strip_markdown_for_tts(text: str) -> str:
    """
    Remove markdown syntax that TTS engines read as literal symbols.

    Handles: bold/italic (**text**, *text*, __text__, _text_), headers (# ## ###),
    inline code (`code`), code fences (```), bullet symbols (- * •), numbered
    list prefixes (1. 2.), horizontal rules (---), HTML tags, and links [text](url).
    """
    import re

    # Code fences (``` ... ```) → remove entirely
    text = re.sub(r"```[\s\S]*?```", "", text)

    # Inline code → just the content
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # Bold+italic: ***text*** or ___text___
    text = re.sub(r"\*{3}(.+?)\*{3}", r"\1", text)
    text = re.sub(r"_{3}(.+?)_{3}", r"\1", text)

    # Bold: **text** or __text__
    text = re.sub(r"\*{2}(.+?)\*{2}", r"\1", text)
    text = re.sub(r"_{2}(.+?)_{2}", r"\1", text)

    # Italic: *text* or _text_ (single word boundary to avoid contractions)
    text = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", text)

    # Markdown links: [label](url) → label
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # Images: ![alt](url) → alt
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)

    # Headers: # ## ### at start of line
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # Horizontal rules: --- or *** or ___ on their own line
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)

    # Numbered list prefixes: "1. " "2. " at start of line
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)

    # Unordered bullets: "- " or "* " or "• " at start of line
    text = re.sub(r"^[-*•]\s+", "", text, flags=re.MULTILINE)

    # HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Blockquote markers: "> "
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)

    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


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
