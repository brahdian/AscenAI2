"""
Interrupt State Machine — Robust Barge-In Handling (Phase 3).

The Problem
-----------
Handling a barge-in (user speaking while AI is playing audio) seems simple:
"cancel the TTS task." But there are four subtle race conditions:

  1. VAD fires while TTS just finished → spurious interrupt triggers a re-listen
     cycle on silence, causing the agent to say "Sorry, I didn't catch that."
  2. User starts speaking *exactly* as the LLM fires its first token → the first
     audio chunk plays, then cuts off, causing a jarring half-word.
  3. Multiple rapid barge-ins (user saying "No... wait... actually...") stack
     up, causing stale `interrupt_tts` flags to leak across utterances.
  4. The STT stream is open when barge-in fires → we need to reset it cleanly
     without losing the new utterance's audio.

Solution: Explicit State Machine
---------------------------------
We model the session as a finite state machine with 4 states:

  LISTENING  → audio is being buffered; VAD is watching for speech
  THINKING   → STT finalized; LLM request is in flight
  SPEAKING   → TTS audio is streaming to the client
  INTERRUPTING → barge-in detected; cancelling TTS, draining buffer

Valid transitions:
  LISTENING  → THINKING    (speech_end from VAD)
  THINKING   → SPEAKING    (first LLM token received)
  SPEAKING   → INTERRUPTING (speech_start while is_speaking=True)
  INTERRUPTING → LISTENING  (TTS task cancelled, buffer reset)
  THINKING   → LISTENING    (empty transcript or guardrail block)
  SPEAKING   → LISTENING    (response_complete)

All state transitions are logged for forensic observability.
"""
from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class PipelineState(str, Enum):
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTING = "interrupting"


class InterruptStateMachine:
    """
    Per-session voice pipeline state machine.

    All methods are synchronous except `cancel_speaking()` which awaits the
    TTS task cancellation.

    Usage
    -----
        sm = InterruptStateMachine(session_id="abc")

        # When VAD detects speech end:
        if sm.can_transition_to(PipelineState.THINKING):
            sm.transition_to(PipelineState.THINKING)

        # When barge-in fires:
        await sm.cancel_speaking()
    """

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._state = PipelineState.LISTENING
        self._state_entered_at: float = time.monotonic()

        # Reference to the currently running TTS asyncio.Task (if any)
        self._active_tts_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

        # Number of barge-ins in this session (for analytics)
        self._barge_in_count = 0

        # Guards
        self._interrupt_requested = False

    # ------------------------------------------------------------------
    # State reads
    # ------------------------------------------------------------------

    @property
    def state(self) -> PipelineState:
        return self._state

    @property
    def is_listening(self) -> bool:
        return self._state == PipelineState.LISTENING

    @property
    def is_thinking(self) -> bool:
        return self._state == PipelineState.THINKING

    @property
    def is_speaking(self) -> bool:
        return self._state == PipelineState.SPEAKING

    @property
    def is_interrupting(self) -> bool:
        return self._state == PipelineState.INTERRUPTING

    @property
    def interrupt_requested(self) -> bool:
        """True when a barge-in has been requested but TTS hasn't stopped yet."""
        return self._interrupt_requested

    @property
    def state_age_ms(self) -> int:
        return int((time.monotonic() - self._state_entered_at) * 1000)

    # ------------------------------------------------------------------
    # Transition helpers
    # ------------------------------------------------------------------

    def can_transition_to(self, target: PipelineState) -> bool:
        """Return True if the requested transition is valid from the current state."""
        valid: dict[PipelineState, set[PipelineState]] = {
            PipelineState.LISTENING: {
                PipelineState.THINKING,
            },
            PipelineState.THINKING: {
                PipelineState.SPEAKING,
                PipelineState.LISTENING,   # empty transcript / guardrail block
            },
            PipelineState.SPEAKING: {
                PipelineState.LISTENING,       # response complete
                PipelineState.INTERRUPTING,    # barge-in
            },
            PipelineState.INTERRUPTING: {
                PipelineState.LISTENING,
            },
        }
        return target in valid.get(self._state, set())

    def transition_to(self, target: PipelineState, reason: str = "") -> None:
        """Perform a state transition (with validation)."""
        if not self.can_transition_to(target):
            logger.warning(
                "invalid_state_transition",
                session_id=self._session_id,
                from_state=self._state.value,
                to_state=target.value,
                reason=reason,
            )
            return

        prev = self._state
        self._state = target
        self._state_entered_at = time.monotonic()

        logger.info(
            "pipeline_state_transition",
            session_id=self._session_id,
            from_state=prev.value,
            to_state=target.value,
            reason=reason or "unspecified",
        )

    # ------------------------------------------------------------------
    # TTS task management
    # ------------------------------------------------------------------

    def register_tts_task(self, task: "asyncio.Task") -> None:
        """Register the current TTS streaming task so barge-in can cancel it."""
        self._active_tts_task = task
        self._interrupt_requested = False

    def clear_tts_task(self) -> None:
        self._active_tts_task = None

    async def cancel_speaking(self, reason: str = "barge_in") -> None:
        """
        Handle a barge-in:
          1. Set interrupt_requested flag (read by the TTS producer/consumer loop).
          2. Cancel the active TTS asyncio.Task.
          3. Transition to INTERRUPTING → LISTENING.

        Safe to call multiple times (idempotent).
        """
        if self._state not in (PipelineState.SPEAKING, PipelineState.THINKING):
            # Nothing to interrupt
            return

        self._interrupt_requested = True
        self._barge_in_count += 1

        logger.info(
            "barge_in_detected",
            session_id=self._session_id,
            state=self._state.value,
            barge_in_count=self._barge_in_count,
            reason=reason,
        )

        # Cancel the TTS task
        task = self._active_tts_task
        if task and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=0.3)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        self._active_tts_task = None

        # Transition through INTERRUPTING → LISTENING
        if self.can_transition_to(PipelineState.INTERRUPTING):
            self.transition_to(PipelineState.INTERRUPTING, reason=reason)
        self._interrupt_requested = False
        if self.can_transition_to(PipelineState.LISTENING):
            self.transition_to(PipelineState.LISTENING, reason="interrupt_complete")

    def reset_after_response(self) -> None:
        """Called when TTS finishes cleanly (no barge-in)."""
        self._interrupt_requested = False
        self._active_tts_task = None
        if self.can_transition_to(PipelineState.LISTENING):
            self.transition_to(PipelineState.LISTENING, reason="response_complete")

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    @property
    def barge_in_count(self) -> int:
        return self._barge_in_count
