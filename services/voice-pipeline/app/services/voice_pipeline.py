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
    # Only one utterance may run the STT→orchestrator→TTS pipeline at a time.
    # Barge-in cancels the TTS task, but the *next* utterance must wait for the
    # lock to be released before starting a new pipeline pass.
    utterance_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # VULN-032 FIX: Rate limiting on utterance processing
    utterance_timestamps: list[float] = field(default_factory=list)
    # VULN-032 FIX: Rate limiting on utterance processing
    utterance_timestamps: list[float] = field(default_factory=list)

    # Per-session agent configuration (persisted after first fetch)
    agent_config: Optional[dict] = None

    # Backchannel state -------------------------------------------------------
    # Monotonic time when the user started their current voiced segment.
    speech_started_at: float = 0.0
    # Monotonic time of the last backchannel emission (prevents spamming).
    last_backchannel_at: float = 0.0
    # True once a backchannel has been sent for the current utterance.
    backchannel_sent: bool = False

    # Twilio Telephony Integration ---------------------------------------------
    # Set to the StreamSid when a Twilio Media Stream connects.
    twilio_stream_sid: Optional[str] = None

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
        self.speech_started_at = 0.0
        self.backchannel_sent = False


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
            # Play pre-recorded greeting (zero TTS cost per call) or TTS-synthesise
            # the text greeting before entering the listening loop.
            await self._play_greeting(websocket, state)
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
                text_data = raw["text"]
                try:
                    import json
                    ctrl = json.loads(text_data)
                    event_type = ctrl.get("event") or ctrl.get("type", "")

                    if event_type == "start" and "streamSid" in ctrl.get("start", {}):
                        # Twilio setup: extract stream SID so we can target audio back
                        state.twilio_stream_sid = ctrl["start"]["streamSid"]
                        logger.info("twilio_stream_started", stream_sid=state.twilio_stream_sid)
                        continue

                    elif event_type == "media" and "payload" in ctrl.get("media", {}):
                        # Twilio sends 8000Hz mu-law audio encoded as base64
                        import base64
                        import audioop
                        payload = ctrl["media"]["payload"]
                        mulaw_bytes = base64.b64decode(payload)
                        # Convert 8kHz mu-law to 16kHz PCM (our pipeline standard)
                        pcm_bytes = audioop.ulaw2lin(mulaw_bytes, 2)
                        resampled_bytes, _ = audioop.ratecv(pcm_bytes, 2, 1, 8000, 16000, None)
                        
                        # Pack it into the raw context so the existing pipeline processes it seamlessly
                        raw = {"bytes": resampled_bytes}
                        # DO NOT continue; fall through to the binary audio chunk handler below

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

            # Barge-in: if TTS is playing and user starts speaking, interrupt
            has_voice = await self.stt.detect_voice_activity(audio_chunk)
            if has_voice and state.is_speaking:
                logger.info("barge_in_detected", session_id=state.session_id)
                await self._handle_barge_in(state)
                await self._send_json(websocket, {"type": "barge_in"})

            if state.is_listening:
                state.audio_buffer.extend(audio_chunk)

                if has_voice:
                    if not state.speech_detected:
                        # Record when voiced speech began for backchannel timing
                        state.speech_started_at = time.monotonic()
                    state.speech_detected = True
                    state.silence_frames = 0

                    # Backchannel: emit a filler word after the user has been
                    # speaking long enough and we haven't sent one this turn.
                    await self._maybe_emit_backchannel(websocket, state)

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
        try:
            # 1. Transcribe — use Gemini audio STT if configured (44× cheaper)
            if settings.STT_PROVIDER == "gemini" and settings.GEMINI_API_KEY:
                raw_text, detected_lang = await self._transcribe_gemini(audio_data)
                transcript = TranscriptResult(
                    text=raw_text, confidence=1.0, language=detected_lang, duration_ms=0
                )
            else:
                transcript = await self.stt.transcribe_audio(
                    audio_data, language="auto", format="webm"
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
                fallback_msg = (state.agent_config or {}).get("computed_fallback") or "Sorry, I didn't quite catch that. Could you say that again?"
                tts_task = asyncio.create_task(
                    self._tts_and_send(
                        fallback_msg,
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
                text=_redact_pii(transcript.text)[:80],
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
                self._stream_response(transcript.text, websocket, state, detected_language=transcript.language)
            )
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
                error=type(exc).__name__,  # no stack details to client
            )
            # Graceful fallback — keep the call alive and let the user retry
            await self._tts_and_send(
                "Sorry, something went wrong on my end. Could you repeat that?",
                websocket, state,
            )
        finally:
            state.is_speaking = False
            state.is_listening = True  # resume listening

    async def _stream_response(
        self,
        user_text: str,
        websocket: WebSocket,
        state: SessionState,
        detected_language: str = "en",
    ) -> None:
        """
        Query the AI orchestrator via SSE, buffer text into sentences, and
        synthesise+send each sentence concurrently using a producer/consumer
        asyncio.Queue.

        Architecture
        ------------
        Producer (LLM)  →  sentence_queue  →  Consumer (TTS)

        While TTS is playing sentence N the LLM continues streaming sentence
        N+1 into the queue — eliminating the serialisation gap that previously
        existed between each TTS call.

        Barge-in: a shared asyncio.Event (cancel_event) signals both tasks to
        abort immediately; the queue is emptied so no stale sentences play.
        """
        # Bounded queue — back-pressures the LLM producer if TTS falls behind.
        sentence_queue: asyncio.Queue[Optional[str]] = asyncio.Queue(maxsize=6)
        cancel_event = asyncio.Event()

        # ── Producer: LLM SSE → sentence_queue ──────────────────────────────
        async def _producer() -> None:
            sentence_buffer = ""
            try:
                async for text_chunk in self._send_text_to_orchestrator(user_text, state, detected_language=detected_language):
                    if cancel_event.is_set() or state.interrupt_tts:
                        break

                    sentence_buffer += text_chunk
                    await self._send_json(
                        websocket, {"type": "ai_text_chunk", "text": text_chunk}
                    )

                    # Flush complete sentences into the queue immediately
                    while True:
                        sentence, remainder = _split_sentence(sentence_buffer)
                        if sentence is None:
                            break
                        sentence_buffer = remainder
                        if sentence.strip():
                            logger.debug(
                                "llm_producer_queued_sentence",
                                session_id=state.session_id,
                                chars=len(sentence),
                            )
                            await sentence_queue.put(sentence)
                        if cancel_event.is_set() or state.interrupt_tts:
                            return

                # Flush any trailing fragment
                if sentence_buffer.strip() and not (cancel_event.is_set() or state.interrupt_tts):
                    await sentence_queue.put(sentence_buffer)
            except asyncio.CancelledError:
                pass
            finally:
                # Sentinel: tells consumer there are no more sentences
                await sentence_queue.put(None)

        # ── Consumer: sentence_queue → TTS → WebSocket ───────────────────────
        async def _consumer() -> None:
            while True:
                try:
                    sentence = await asyncio.wait_for(sentence_queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    logger.warning("tts_consumer_timeout", session_id=state.session_id)
                    break

                if sentence is None:  # producer sent the sentinel
                    break
                if cancel_event.is_set() or state.interrupt_tts:
                    # Drain remaining queue without synthesising
                    while not sentence_queue.empty():
                        sentence_queue.get_nowait()
                    break

                t_start = time.monotonic()
                await self._tts_and_send(sentence, websocket, state)
                elapsed_ms = int((time.monotonic() - t_start) * 1000)
                logger.debug(
                    "tts_consumer_sent_audio",
                    session_id=state.session_id,
                    chars=len(sentence),
                    elapsed_ms=elapsed_ms,
                )

        # Watch barge-in: if state.interrupt_tts flips, signal cancel_event so
        # both coroutines exit cleanly without waiting for the full LLM stream.
        async def _barge_in_watcher() -> None:
            while not cancel_event.is_set():
                if state.interrupt_tts:
                    cancel_event.set()
                    # Drain the queue so the consumer exits immediately
                    while not sentence_queue.empty():
                        try:
                            sentence_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    # Push a sentinel so the consumer unblocks from get()
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
            cancel_event.set()  # clean up watcher

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

            voice_greeting_url: str = agent_data.get("voice_greeting_url") or ""
            greeting_text: str = agent_data.get("greeting_message") or ""
            computed_greeting: str = agent_data.get("computed_greeting") or ""

            if voice_greeting_url:
                # Resolve relative URL against orchestrator base
                if voice_greeting_url.startswith("/"):
                    audio_url = f"{self.orchestrator_url}{voice_greeting_url}"
                else:
                    audio_url = voice_greeting_url

                logger.info(
                    "playing_prerecorded_greeting",
                    session_id=state.session_id,
                    url=audio_url,
                )
                state.is_speaking = True
                try:
                    async with client.stream("GET", audio_url, timeout=10.0) as audio_resp:
                        async for chunk in audio_resp.aiter_bytes(4096):
                            if websocket.client_state == WebSocketState.CONNECTED:
                                await websocket.send_bytes(chunk)
                finally:
                    state.is_speaking = False
                await self._send_json(websocket, {"type": "greeting_complete"})

            elif greeting_text or computed_greeting:
                text_to_speak = greeting_text or computed_greeting
                logger.info(
                    "synthesising_greeting",
                    session_id=state.session_id,
                    use_computed=not bool(greeting_text)
                )
                state.is_speaking = True
                try:
                    await self._tts_and_send(text_to_speak, websocket, state)
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
        # (e.g. "**bold**" → "asterisk asterisk bold asterisk asterisk").
        spoken_text = _strip_markdown_for_tts(text)
        if not spoken_text.strip():
            return

        try:
            provider = settings.TTS_PROVIDER.lower()
            
            # Request explicit mu-law 8kHz format if communicating over Twilio
            # so we don't need to transcode inside the Python process.
            fmt_kwargs = {}
            if state.twilio_stream_sid:
                if provider == "cartesia":
                    fmt_kwargs["output_format"] = {
                        "container": "raw",
                        "encoding": "pcm_mulaw",
                        "sample_rate": 8000
                    }
                elif provider == "deepgram":
                    fmt_kwargs["encoding"] = "mulaw"
                    fmt_kwargs["sample_rate"] = 8000

            if provider == "deepgram":
                audio_iter = self.tts.synthesize_deepgram_stream(
                    spoken_text,
                    voice_id="aura-asteria-en",
                    **fmt_kwargs
                )
            elif provider == "cartesia":
                audio_iter = self.tts.synthesize_cartesia_stream(
                    spoken_text,
                    voice_id=settings.CARTESIA_VOICE_ID,
                    **fmt_kwargs
                )
            elif provider == "google":
                audio_bytes = await self._tts_google_cloud(spoken_text)
                async def _google_iter():
                    if audio_bytes:
                        yield audio_bytes
                audio_iter = _google_iter()
            elif provider == "elevenlabs":
                audio_iter = self.tts.synthesize_elevenlabs(
                    spoken_text,
                    voice_id="21m00Tcm4TlvDq8ikWAM",
                    model_id="eleven_turbo_v2_5",
                )
            else:
                # Default: OpenAI TTS
                audio_iter = self.tts.synthesize_stream(spoken_text, voice_id="alloy")

            async for audio_chunk in audio_iter:
                if state.interrupt_tts:
                    return
                await self._emit_audio(websocket, audio_chunk, state)
        except Exception as exc:
            logger.error("tts_send_error", session_id=state.session_id, error=str(exc))

    async def _emit_audio(self, websocket: WebSocket, audio_chunk: bytes, state: SessionState) -> None:
        """Helper to send audio correctly depending on the channel type (Browser PCM/MP3 vs Twilio base64 mu-law)."""
        if websocket.client_state != WebSocketState.CONNECTED:
            return
            
        if state.twilio_stream_sid:
            import base64
            # Twilio Media Streams require base64 encoded audio wrapped in JSON.
            payload = {
                "event": "media",
                "streamSid": state.twilio_stream_sid,
                "media": {
                    "payload": base64.b64encode(audio_chunk).decode("utf-8")
                }
            }
            await self._send_json(websocket, payload)
        else:
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
            "detected_language": detected_language,
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
