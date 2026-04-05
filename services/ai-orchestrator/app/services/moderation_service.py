"""
ModerationService — ML-based toxicity and content moderation.

Three-layer strategy (fastest to slowest, fail-forward):
  1. OpenAI Moderation API    ~30–50 ms  — primary
  2. detoxify (local model)   ~80–150 ms — fallback when OpenAI unavailable
  3. Regex patterns           <1 ms      — last resort

Input moderation: fail-closed (block if flagged)
Output moderation: fail-open (warn + log, but don't block LLM response)

Severity levels:
  - blocked:  content must be rejected immediately
  - warned:   content passes but is logged and counted in metrics
  - clean:    no issues detected
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Toxic regex patterns (last-resort fallback)
# ---------------------------------------------------------------------------

_TOXIC_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bkill\s+(?:yourself|urself)\b", re.IGNORECASE),
    re.compile(r"\bsuicid(?:e|al)\b", re.IGNORECASE),
    re.compile(r"\b(?:bomb|explosive)\s+(?:how\s+to\s+make|build|instructions?)\b", re.IGNORECASE),
    re.compile(r"\bchild\s+(?:abuse|porn|exploitation)\b", re.IGNORECASE),
    re.compile(r"\bterror(?:ist|ism)\s+attack\b", re.IGNORECASE),
    re.compile(r"\b(?:n[i1]gg(?:er|a)|f[a4]gg[o0]t|c[u0]nt)\b", re.IGNORECASE),
    re.compile(r"\bI\s+(?:want|will|am\s+going)\s+to\s+(?:kill|murder|rape)\b", re.IGNORECASE),
    re.compile(r"\bdrunk\s+driving\s+(?:tips|how\s+to|guide)\b", re.IGNORECASE),
]

# Categories that are always blocked (OpenAI Moderation API category names)
_BLOCKED_CATEGORIES = frozenset({
    "sexual/minors",
    "violence/graphic",
    "hate/threatening",
    "self-harm/instructions",
    "harassment/threatening",
})

# Categories that trigger a warning (but are not blocked for output)
_WARNED_CATEGORIES = frozenset({
    "hate",
    "harassment",
    "self-harm",
    "violence",
    "sexual",
})


class OutputBlockedError(Exception):
    """
    Raised by ModerationService.check_output() when the LLM response contains
    content with severity "blocked".  Callers must catch this and substitute a
    safe fallback message — never surface the blocked text to the user.
    """

    def __init__(self, reason: str, categories: list[str]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.categories = categories


@dataclass
class ModerationResult:
    """Result of a moderation check."""
    severity: str  # "clean" | "warned" | "blocked"
    flagged: bool = False
    categories: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    provider: str = "none"
    reason: Optional[str] = None

    @property
    def is_blocked(self) -> bool:
        return self.severity == "blocked"

    @property
    def is_warned(self) -> bool:
        return self.severity == "warned"


class ModerationService:
    """
    Three-layer content moderation service.

    :param openai_api_key: OpenAI API key (optional — enables primary layer)
    """

    def __init__(self, openai_api_key: Optional[str] = None) -> None:
        self._openai_key = openai_api_key
        self._detoxify_model = None   # lazy-loaded
        self._detoxify_available = True  # set to False if import fails

    # ── Public API ────────────────────────────────────────────────────────────

    async def check_input(self, text: str) -> ModerationResult:
        """
        Check user input.  Fail-closed: blocked → reject.
        """
        result = await self._check(text)
        logger.info(
            "moderation_input",
            severity=result.severity,
            flagged=result.flagged,
            provider=result.provider,
            categories=result.categories,
        )
        return result

    async def check_output(self, text: str) -> ModerationResult:
        """
        Check LLM output.  Fail-closed: content with severity "blocked" raises
        OutputBlockedError so the caller MUST handle it — the flagged text is
        never returned to the end user.  Lower-severity results (warned, clean)
        are returned normally.
        """
        result = await self._check(text)
        if result.flagged:
            logger.warning(
                "moderation_output_flagged",
                severity=result.severity,
                provider=result.provider,
                categories=result.categories,
            )
        if result.severity == "blocked":
            raise OutputBlockedError(
                reason=result.reason or f"Output blocked by moderation ({result.provider})",
                categories=result.categories or [],
            )
        return result

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _check(self, text: str) -> ModerationResult:
        if not text or not text.strip():
            return ModerationResult(severity="clean")

        # Layer 1: OpenAI Moderation API
        if self._openai_key:
            result = await self._check_openai(text)
            if result is not None:
                return result

        # Layer 2: detoxify
        if self._detoxify_available:
            result = self._check_detoxify(text)
            if result is not None:
                return result

        # Layer 3: Regex
        return self._check_regex(text)

    async def _check_openai(self, text: str) -> Optional[ModerationResult]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/moderations",
                    headers={"Authorization": f"Bearer {self._openai_key}"},
                    json={"input": text[:4096]},
                )
                resp.raise_for_status()
                data = resp.json()

            result_data = data.get("results", [{}])[0]
            flagged = result_data.get("flagged", False)
            categories = result_data.get("categories", {})
            scores = result_data.get("category_scores", {})

            blocked_cats = [c for c, v in categories.items() if v and c in _BLOCKED_CATEGORIES]
            warned_cats = [c for c, v in categories.items() if v and c in _WARNED_CATEGORIES]

            if blocked_cats:
                return ModerationResult(
                    severity="blocked",
                    flagged=True,
                    categories=blocked_cats,
                    scores={c: scores.get(c, 0.0) for c in blocked_cats},
                    provider="openai",
                    reason=f"Blocked categories: {', '.join(blocked_cats)}",
                )
            if warned_cats:
                return ModerationResult(
                    severity="warned",
                    flagged=True,
                    categories=warned_cats,
                    scores={c: scores.get(c, 0.0) for c in warned_cats},
                    provider="openai",
                )
            if flagged:
                all_cats = [c for c, v in categories.items() if v]
                return ModerationResult(
                    severity="warned",
                    flagged=True,
                    categories=all_cats,
                    provider="openai",
                )
            return ModerationResult(severity="clean", provider="openai")

        except Exception as exc:
            logger.warning("openai_moderation_error", error=str(exc))
            return None

    def _check_detoxify(self, text: str) -> Optional[ModerationResult]:
        try:
            if self._detoxify_model is None:
                from detoxify import Detoxify  # type: ignore
                self._detoxify_model = Detoxify("original")
        except ImportError:
            self._detoxify_available = False
            return None
        except Exception as exc:
            logger.warning("detoxify_load_error", error=str(exc))
            self._detoxify_available = False
            return None

        try:
            predictions = self._detoxify_model.predict(text[:2000])
            severe = predictions.get("severe_toxicity", 0.0)
            threat = predictions.get("threat", 0.0)
            toxicity = predictions.get("toxicity", 0.0)
            identity_attack = predictions.get("identity_attack", 0.0)
            sexual_explicit = predictions.get("sexual_explicit", 0.0)

            if severe > 0.7 or threat > 0.8 or sexual_explicit > 0.85:
                cats = []
                if severe > 0.7:
                    cats.append("severe_toxicity")
                if threat > 0.8:
                    cats.append("threat")
                if sexual_explicit > 0.85:
                    cats.append("sexual_explicit")
                return ModerationResult(
                    severity="blocked",
                    flagged=True,
                    categories=cats,
                    scores={c: predictions.get(c, 0.0) for c in cats},
                    provider="detoxify",
                )
            if toxicity > 0.7 or identity_attack > 0.6:
                cats = []
                if toxicity > 0.7:
                    cats.append("toxicity")
                if identity_attack > 0.6:
                    cats.append("identity_attack")
                return ModerationResult(
                    severity="warned",
                    flagged=True,
                    categories=cats,
                    scores={c: predictions.get(c, 0.0) for c in cats},
                    provider="detoxify",
                )
            return ModerationResult(severity="clean", provider="detoxify")

        except Exception as exc:
            logger.warning("detoxify_predict_error", error=str(exc))
            return None

    def _check_regex(self, text: str) -> ModerationResult:
        for pattern in _TOXIC_PATTERNS:
            if pattern.search(text):
                return ModerationResult(
                    severity="blocked",
                    flagged=True,
                    categories=["regex_pattern"],
                    provider="regex",
                    reason=f"Matched pattern: {pattern.pattern[:60]}",
                )
        return ModerationResult(severity="clean", provider="regex")
