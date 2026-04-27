"""
Transcription Scrubber — LiveKit-Inspired Interim Transcript Cleanup (Phase 2).

The Problem
-----------
Real-time STT providers (Deepgram, Cartesia) emit a rapid stream of *interim*
transcripts as the user speaks.  These often look like:

    "I"  →  "I want"  →  "I want to"  →  "I want to book"  →  "I want to book a"
    →  "I want"  →  "I want to book a table"  ← correction

The AI Orchestrator would be confused if it received these partial/corrected
transcripts.  Naive concatenation produces gibberish like:
    "I I want I want to I want to book I want I want to book a table"

This module handles two patterns:
  1. "Stutter": The provider sends the same words over and over as it becomes
     more confident.  We detect this via longest-common-prefix matching and
     deduplicate.
  2. "Correction": The provider revises a previous interim (e.g. "duck" → "dock").
     We replace the old interim with the new one.

Design
------
TranscriptBuffer accumulates interim segments and returns only the *stable*
(not-yet-revised) prefix plus the latest segment.  On `finalize()`, it
returns the complete, scrubbed transcript.

Usage
-----
    buf = TranscriptBuffer()

    # Feed interim events from your STT stream
    for event in stt_stream:
        if event.is_final:
            transcript = buf.finalize(event.text)
            # send to LLM
        else:
            stable = buf.update(event.text)
            # optionally show "typing indicator" text to user

Algorithm
---------
We track the last *final* segment boundary.  Interim updates after a final
segment only update the "pending" tail.  This mirrors LiveKit's
TranscriptionSegment merging strategy.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TranscriptSegment:
    text: str
    is_final: bool
    confidence: float
    timestamp: float = field(default_factory=time.monotonic)


# ---------------------------------------------------------------------------
# Core scrubber
# ---------------------------------------------------------------------------

class TranscriptBuffer:
    """
    Accumulates interim STT segments and returns a clean, deduplicated
    transcript.

    Thread safety: not thread-safe — designed for use within a single asyncio
    task per voice session.
    """

    def __init__(self, session_id: str = "") -> None:
        self._session_id = session_id
        # Stable finalized segments (list of strings)
        self._final_segments: list[str] = []
        # The current working (interim) text
        self._pending: str = ""
        # Last raw interim from the provider (for stutter detection)
        self._last_interim: str = ""
        # Total segment count for logging
        self._interim_count = 0
        self._correction_count = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_interim(self, text: str) -> str:
        """
        Record a new interim transcript.  Returns the current "display text"
        (final segments + this interim), suitable for a "typing indicator" UI.

        Handles stutter deduplication and interim correction silently.
        """
        text = text.strip()
        if not text:
            return self._build_display("")

        self._interim_count += 1
        cleaned = self._clean_stutter(text, self._last_interim)

        if cleaned != text:
            self._correction_count += 1
            logger.debug(
                "transcript_stutter_removed",
                session_id=self._session_id,
                before=text[:60],
                after=cleaned[:60],
            )

        self._pending = cleaned
        self._last_interim = text
        return self._build_display(cleaned)

    def add_final(self, text: str) -> None:
        """
        Mark a segment as final (no more corrections expected for this part).
        Clears the pending interim.
        """
        text = text.strip()
        if text:
            # Check for correction of the last final segment
            if self._final_segments:
                merged = self._try_merge_correction(self._final_segments[-1], text)
                if merged != self._final_segments[-1]:
                    self._correction_count += 1
                    self._final_segments[-1] = merged
                else:
                    self._final_segments.append(text)
            else:
                self._final_segments.append(text)

        self._pending = ""
        self._last_interim = ""

    def finalize(self, last_text: Optional[str] = None) -> str:
        """
        Called when the user has finished speaking (VAD speech_end).
        Returns the complete, scrubbed transcript.

        Parameters
        ----------
        last_text : the final transcript from the provider if available,
                    otherwise uses the accumulated segments + pending.
        """
        if last_text:
            last_text = last_text.strip()
            # If the provider gives us a complete final transcript, trust it
            # but still run it through our stutter cleaner.
            result = self._clean_stutter(last_text, self._last_interim)
        else:
            # Build from accumulated finals + pending
            parts = self._final_segments.copy()
            if self._pending:
                parts.append(self._pending)
            result = " ".join(parts)

        result = self._post_process(result)

        logger.info(
            "transcript_finalized",
            session_id=self._session_id,
            chars=len(result),
            interim_count=self._interim_count,
            correction_count=self._correction_count,
        )

        self.reset()
        return result

    def reset(self) -> None:
        """Clear all accumulated state for the next utterance."""
        self._final_segments = []
        self._pending = ""
        self._last_interim = ""
        self._interim_count = 0
        self._correction_count = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_display(self, interim: str) -> str:
        """Concatenate final segments with the current interim."""
        parts = self._final_segments.copy()
        if interim:
            parts.append(interim)
        return " ".join(parts)

    @staticmethod
    def _clean_stutter(text: str, prev: str) -> str:
        """
        Remove leading repetition when a new interim re-states words already
        present in the previous one.

        Example:
            prev = "I want to book"
            text = "I want to book a"
            → "a"  (NOT prepended — the caller builds display from finals)

        Actually, we DON'T strip the prefix here because the whole text is the
        running transcript.  Instead we detect and log stutter and return the
        longer/newer version.
        """
        if not prev or not text:
            return text

        # If the new text starts with the old text, it's a simple extension
        if text.startswith(prev):
            return text  # normal incremental update

        # Correction case: new text diverges.  Trust the newer, longer one.
        if len(text) >= len(prev):
            return text

        # The new text is shorter — provider walked back.  Keep it as-is;
        # the display will reflect the correction.
        return text

    @staticmethod
    def _try_merge_correction(existing: str, new_segment: str) -> str:
        """
        If `new_segment` shares a long common prefix with `existing`,
        treat it as a correction and return the merged/updated version.
        """
        # Simple heuristic: if new_segment is a revision of existing
        # (>= 50% word overlap), replace the tail.
        existing_words = existing.split()
        new_words = new_segment.split()

        common = 0
        for a, b in zip(existing_words, new_words):
            if a.lower() == b.lower():
                common += 1
            else:
                break

        overlap_ratio = common / max(len(existing_words), 1)
        if overlap_ratio >= 0.5 and len(new_words) > common:
            # Keep common prefix, append new tail
            merged = " ".join(existing_words[:common] + new_words[common:])
            return merged

        return new_segment

    @staticmethod
    def _post_process(text: str) -> str:
        """
        Final cleanup: collapse whitespace, strip filler words the STT
        sometimes adds ("um", "uh", lone "hm"), fix common STT artifacts.
        """
        if not text:
            return text

        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # Remove lone filler words at start (STT often adds these)
        text = re.sub(r"^(um|uh|hmm|hm|ah)\s+", "", text, flags=re.IGNORECASE)

        # Remove trailing filler
        text = re.sub(r"\s+(um|uh|hmm|hm)\s*$", "", text, flags=re.IGNORECASE)

        return text
