"""
IntentDetector — production-ready, playbook-driven intent classification.

Design principles
-----------------
1. **No hardcoded intent vocabulary.** Every business is different. Intent
   labels are sourced dynamically from the operator-configured AgentPlaybook
   objects: their ``intent_triggers`` phrases and any
   ``config.trigger_condition.keywords`` lists.

2. **Zero extra I/O per turn.** ``classify_from_playbooks`` is a pure in-
   process scoring function (O(n·k)). The LLM-based routing that handles
   ambiguous multi-playbook cases already lives in
   ``PlaybookHandler.route_active_playbook``; we do not add a second LLM call.

3. **Winning playbook name IS the intent.** When the orchestrator has already
   resolved a playbook (the common path), it simply uses ``playbook.name`` as
   the intent label, so this detector is only invoked as a fallback when no
   playbook is matched.

4. **Universal heuristics kept.** Greeting, farewell, escalation, and language
   detection are cross-domain utilities that belong here — they are not domain-
   specific intents.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    from app.models.agent import AgentPlaybook

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Universal escalation phrases — not domain-specific, every agent needs these
# ---------------------------------------------------------------------------
_ESCALATION_EXACT: tuple[str, ...] = (
    "speak to a human",
    "talk to a person",
    "talk to an agent",
    "talk to a real person",
    "real person",
    "live agent",
    "human agent",
    "customer service",
    "speak to someone",
    "connect me to a human",
    "transfer me",
    "get me a representative",
)

# ---------------------------------------------------------------------------
# Universal greeting / farewell marker words
# ---------------------------------------------------------------------------
_GREETING_PATTERNS: tuple[str, ...] = (
    r"\bhi\b", r"\bhello\b", r"\bhey\b",
    r"\bgood morning\b", r"\bgood afternoon\b", r"\bgood evening\b",
    r"\bhowdy\b", r"\bgreetings\b", r"\bhiya\b", r"\bwhat'?s up\b",
)

_FAREWELL_PATTERNS: tuple[str, ...] = (
    r"\bbye\b", r"\bgoodbye\b", r"\bgood bye\b",
    r"\bthanks\b", r"\bthank you\b", r"\bsee you\b",
    r"\btake care\b", r"\bhave a good\b", r"\bthat'?s all\b",
    r"\bno more\b", r"\bdone\b", r"\bfinished\b",
)

# Pre-compile for speed
_CRE_GREETING = [re.compile(p, re.IGNORECASE) for p in _GREETING_PATTERNS]
_CRE_FAREWELL = [re.compile(p, re.IGNORECASE) for p in _FAREWELL_PATTERNS]


class IntentDetector:
    """
    Dynamic, playbook-driven intent classifier.

    The primary method is :meth:`classify_from_playbooks`, which scores the
    user message against every active playbook's ``intent_triggers`` and
    ``config.trigger_condition.keywords``.  The playbook with the highest
    score wins; its ``name`` is returned as the intent label.

    All other helpers (escalation, greeting, farewell, language) are
    domain-agnostic and unchanged from the previous implementation.
    """

    # ------------------------------------------------------------------
    # Primary intent classifier
    # ------------------------------------------------------------------

    def classify_from_playbooks(
        self,
        text: str,
        playbooks: list["AgentPlaybook"],
    ) -> str:
        """
        Score *text* against each playbook using a combined additive model.

        Both the ``description`` and the ``intent_triggers`` contribute to
        the same score for each playbook.  They are not alternatives — they
        reinforce each other.

        Scoring weights
        ~~~~~~~~~~~~~~~
        - **Description** content word match (alphabetic, len > 3)  → **+2** each
          Description carries higher per-signal weight and therefore takes
          precedence: a playbook whose description contains many matching
          words will consistently outscore one with only a few trigger hits.

        - **Intent trigger** multi-word phrase (substring exact match)  → +3
          (phrase specificity bonus — more precise than a single word)

        - **Intent trigger** single word (word-boundary match)          → +1

        When a playbook has no ``intent_triggers``, its score is driven
        entirely by the description — intentionally, as per the requirement.

        Returns the ``name`` of the best-scoring playbook, or ``"general"``
        when no playbook is provided or no signal fires.
        """
        if not text or not text.strip() or not playbooks:
            return "general"

        normalized = text.lower().strip()
        best_score = 0
        best_name = "general"

        for playbook in playbooks:
            score = 0

            # ── Description (primary, higher weight: +2 per content word) ──
            description = (playbook.description or "").strip()
            if description:
                for word in re.findall(r"[a-z]+", description.lower()):
                    if len(word) > 3 and re.search(r"\b" + re.escape(word) + r"\b", normalized):
                        score += 2

            # ── Intent triggers (supplementary, runs when triggers exist) ──
            for trigger in (playbook.intent_triggers or []):
                if not isinstance(trigger, str) or not trigger.strip():
                    continue
                kw = trigger.lower().strip()
                if " " in kw:
                    # Multi-word phrase: exact substring (+3 specificity bonus)
                    if kw in normalized:
                        score += 3
                else:
                    # Single word: word-boundary match
                    if re.search(r"\b" + re.escape(kw) + r"\b", normalized):
                        score += 1

            if score > best_score:
                best_score = score
                best_name = playbook.name or "general"

        if best_score > 0:
            logger.debug(
                "intent_classified",
                text_preview=text[:80],
                intent=best_name,
                score=best_score,
            )
        else:
            logger.debug("intent_unmatched", text_preview=text[:80])

        return best_name

    # ------------------------------------------------------------------
    # Universal cross-domain utilities
    # ------------------------------------------------------------------

    def should_escalate_immediately(self, text: str) -> bool:
        """
        Return True if the user is explicitly asking for a human agent.

        This check is domain-agnostic and intentionally conservative: it
        only fires on explicit escalation phrases so that ordinary
        questions (e.g. "who is the best person to ask about X?") are not
        mis-classified.
        """
        if not text:
            return False
        normalized = text.lower()
        for phrase in _ESCALATION_EXACT:
            if phrase in normalized:
                logger.info(
                    "immediate_escalation_triggered",
                    phrase=phrase,
                    text_preview=text[:80],
                )
                return True
        return False

    def is_greeting(self, text: str) -> bool:
        """Return True if the message is an opening greeting."""
        if not text:
            return False
        t = text.strip()
        # Short messages (≤ 5 words) that match a greeting pattern
        if len(t.split()) > 8:
            return False
        return any(cre.search(t) for cre in _CRE_GREETING)

    def is_farewell(self, text: str) -> bool:
        """Return True if the message is a closing farewell."""
        if not text:
            return False
        t = text.strip()
        if len(t.split()) > 8:
            return False
        return any(cre.search(t) for cre in _CRE_FAREWELL)

    def detect_language(self, text: str, supported_langs: list[str]) -> Optional[str]:
        """
        Heuristic language detection for common patterns.

        Runs in O(n) over a small fixed set of regex patterns — no I/O,
        no model call.  Returns the best-matching code from
        *supported_langs*, or a bare language code if the agent supports
        it implicitly (e.g. ``"fr"`` even if only ``"fr-CA"`` is listed).
        Falls back to ``None`` when detection is inconclusive.
        """
        if not text:
            return None
        t = text.lower().strip()

        # French patterns
        _fr = [
            r"\bbonjour\b", r"\bsalut\b", r"\bpouvez-vous\b", r"\baidez-moi\b",
            r"\bcomment\b", r"\bmerci\b", r"\boui\b", r"\bnon\b", r"\bfrançais\b",
            r"\bje veux\b", r"\bj'ai besoin\b",
        ]
        if any(re.search(p, t) for p in _fr):
            return "fr-CA" if "fr-CA" in supported_langs else "fr"

        # Spanish patterns
        _es = [
            r"\bhola\b", r"\bbuenos días\b", r"\bgracias\b", r"\bpor favor\b",
            r"\bueno\b", r"\bdiga\b", r"\bentendido\b", r"\bsí\b", r"\bno\b",
        ]
        if any(re.search(p, t) for p in _es):
            return "es-MX" if "es-MX" in supported_langs else "es"

        # Hindi patterns
        _hi = [
            r"\bnamaste\b", r"\bnamaskar\b", r"\bshukriya\b", r"\baap\b",
            r"\bkaise\b", r"\bhaan\b", r"\btheek\b", r"\bhindi\b",
        ]
        if any(re.search(p, t) for p in _hi):
            return "hi"

        # Tagalog / Filipino patterns
        _tl = [
            r"\bkumusta\b", r"\bsalamat\b", r"\boo\b", r"\btagalog\b",
            r"\bfilipino\b", r"\bmagandang\b", r"\bopo\b", r"\bpo\b",
        ]
        if any(re.search(p, t) for p in _tl):
            return "tl"

        # German patterns
        _de = [
            r"\bhallo\b", r"\bguten tag\b", r"\bdanke\b", r"\bbitte\b",
            r"\bja\b", r"\bnein\b", r"\bdeutsch\b", r"\bhilfe\b",
        ]
        if any(re.search(p, t) for p in _de):
            return "de"

        # English patterns (checked second — lower-priority default)
        _en = [
            r"\bhello\b", r"\bhi\b", r"\bcan you\b", r"\bhelp\b", r"\bhow\b",
            r"\bthanks\b", r"\byes\b", r"\bno\b", r"\benglish\b",
        ]
        if any(re.search(p, t) for p in _en):
            return "en-US" if "en-US" in supported_langs else "en"

        return None
