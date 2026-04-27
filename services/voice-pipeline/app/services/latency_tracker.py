"""
Latency Tracker — Hop-by-Hop Voice Pipeline Telemetry (Phase 4).

Tracks 5 key latency hops for every voice session turn:

  VAD_LAG       Time from last audio chunk to speech_end firing.
  STT_LAG       Time from speech_end to final transcript being ready.
  LLM_TTFT      Time to First Token from LLM (orchestrator).
  TTS_TTFA      Time to First Audio byte from TTS provider.
  E2E_LAG       Total end-to-end: from speech_end to first audio chunk sent.

All measurements are in milliseconds (int).

Usage
-----
    tracker = LatencyTracker(session_id="abc")

    tracker.mark("speech_end")
    transcript = await stt.finalize()
    tracker.mark("stt_done")

    async for chunk in llm.stream():
        if tracker.first_token:
            tracker.mark("llm_first_token")
        ...

    async for audio in tts.stream():
        if tracker.first_audio:
            tracker.mark("tts_first_audio")
        ...

    tracker.report()      # logs a structured summary
    tracker.emit_metrics()  # pushes to Prometheus

Prometheus Metrics
------------------
  voice_vad_lag_ms (Histogram)
  voice_stt_lag_ms (Histogram)
  voice_llm_ttft_ms (Histogram)
  voice_tts_ttfa_ms (Histogram)
  voice_e2e_lag_ms (Histogram)
"""
from __future__ import annotations

import time
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Prometheus metric definitions (lazy-initialized to avoid import-time cost)
# ---------------------------------------------------------------------------

def _get_metrics():
    """Lazily build and cache the Prometheus histogram objects."""
    try:
        from prometheus_client import Histogram, REGISTRY  # type: ignore

        buckets = (50, 100, 150, 200, 300, 400, 500, 750, 1000, 1500, 2000, 3000)

        def _h(name: str, doc: str):
            # Re-use existing metric if already registered (e.g. test reloads)
            try:
                return Histogram(name, doc, buckets=buckets)
            except ValueError:
                return REGISTRY._names_to_collectors.get(name)  # type: ignore

        return {
            "vad_lag": _h("voice_vad_lag_ms", "Time (ms) from last audio chunk to VAD speech_end"),
            "stt_lag": _h("voice_stt_lag_ms", "Time (ms) from speech_end to final STT transcript"),
            "llm_ttft": _h("voice_llm_ttft_ms", "Time (ms) to first LLM token (voice path)"),
            "tts_ttfa": _h("voice_tts_ttfa_ms", "Time (ms) to first TTS audio byte"),
            "e2e": _h("voice_e2e_lag_ms", "End-to-end (ms): speech_end → first audio chunk sent"),
        }
    except ImportError:
        return {}


_METRICS: Optional[dict] = None


def _metrics() -> dict:
    global _METRICS
    if _METRICS is None:
        _METRICS = _get_metrics()
    return _METRICS


# ---------------------------------------------------------------------------
# Per-turn latency tracker
# ---------------------------------------------------------------------------

class LatencyTracker:
    """
    Lightweight per-session-turn latency recorder.

    Instantiate a new tracker for each utterance (not per session).
    """

    # Named checkpoints
    SPEECH_END = "speech_end"
    STT_DONE = "stt_done"
    LLM_FIRST_TOKEN = "llm_first_token"
    TTS_FIRST_AUDIO = "tts_first_audio"
    RESPONSE_COMPLETE = "response_complete"

    def __init__(self, session_id: str, turn: int = 0) -> None:
        self._session_id = session_id
        self._turn = turn
        self._marks: dict[str, float] = {}
        self._start: float = time.monotonic()

    def mark(self, checkpoint: str) -> None:
        """Record the current monotonic time for a named checkpoint."""
        if checkpoint not in self._marks:
            self._marks[checkpoint] = time.monotonic()

    def _delta_ms(self, from_key: str, to_key: str) -> Optional[int]:
        """Return elapsed milliseconds between two checkpoints, or None."""
        t0 = self._marks.get(from_key)
        t1 = self._marks.get(to_key)
        if t0 is not None and t1 is not None:
            return max(0, int((t1 - t0) * 1000))
        return None

    # ------------------------------------------------------------------
    # Convenience helpers — call these at the right moment in the pipeline
    # ------------------------------------------------------------------

    def on_speech_end(self) -> None:
        self.mark(self.SPEECH_END)

    def on_stt_done(self) -> None:
        self.mark(self.STT_DONE)

    def on_llm_first_token(self) -> None:
        self.mark(self.LLM_FIRST_TOKEN)

    def on_tts_first_audio(self) -> None:
        self.mark(self.TTS_FIRST_AUDIO)

    def on_response_complete(self) -> None:
        self.mark(self.RESPONSE_COMPLETE)

    # ------------------------------------------------------------------
    # Computed metrics
    # ------------------------------------------------------------------

    @property
    def stt_lag_ms(self) -> Optional[int]:
        return self._delta_ms(self.SPEECH_END, self.STT_DONE)

    @property
    def llm_ttft_ms(self) -> Optional[int]:
        return self._delta_ms(self.STT_DONE, self.LLM_FIRST_TOKEN)

    @property
    def tts_ttfa_ms(self) -> Optional[int]:
        return self._delta_ms(self.LLM_FIRST_TOKEN, self.TTS_FIRST_AUDIO)

    @property
    def e2e_lag_ms(self) -> Optional[int]:
        """Total: from speech_end to first audio byte sent."""
        return self._delta_ms(self.SPEECH_END, self.TTS_FIRST_AUDIO)

    @property
    def total_ms(self) -> Optional[int]:
        return self._delta_ms(self.SPEECH_END, self.RESPONSE_COMPLETE)

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def report(self) -> dict:
        """Build and log a structured latency summary.  Returns the dict."""
        summary = {
            "session_id": self._session_id,
            "turn": self._turn,
            "stt_lag_ms": self.stt_lag_ms,
            "llm_ttft_ms": self.llm_ttft_ms,
            "tts_ttfa_ms": self.tts_ttfa_ms,
            "e2e_lag_ms": self.e2e_lag_ms,
            "total_ms": self.total_ms,
        }
        logger.info("voice_latency_report", **summary)
        return summary

    def emit_metrics(self) -> None:
        """Push hop-by-hop measurements to Prometheus histograms."""
        from app.core.config import settings
        if not settings.LATENCY_TELEMETRY_ENABLED:
            return

        m = _metrics()
        if not m:
            return

        def _observe(key: str, val: Optional[int]) -> None:
            if val is not None and key in m and m[key]:
                try:
                    m[key].observe(val)
                except Exception:
                    pass

        _observe("stt_lag", self.stt_lag_ms)
        _observe("llm_ttft", self.llm_ttft_ms)
        _observe("tts_ttfa", self.tts_ttfa_ms)
        _observe("e2e", self.e2e_lag_ms)
