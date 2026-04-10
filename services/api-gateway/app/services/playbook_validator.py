from __future__ import annotations

import re
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

try:
    import spacy
    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False
    logger.warning("spacy_not_available_using_regex_only")

_nlp: Optional[object] = None


def _get_nlp():
    global _nlp
    if _nlp is None and SPACY_AVAILABLE:
        try:
            _nlp = spacy.load("en_core_web_sm")
        except Exception:
            logger.warning("spacy_model_not_loaded_using_regex_only")
            return None
    return _nlp


CREDIT_CARD_PATTERNS = [
    r"\bcredit\s*card\b",
    r"\bcard\s*number\b",
    r"\bcvv\b",
    r"\bcvc\b",
    r"\bsecurity\s*code\b",
    r"\bexpir(?:y|ation)\b",
]

SENSITIVE_PATTERNS = [
    r"\bsin\b",
    r"\bsocial\s*security\b",
    r"\bssn\b",
    r"\bbank\s*account\b",
    r"\brouting\s*number\b",
]

DIRECT_REQUEST_PATTERNS = [
    r"\bprovide\s+your\s+card\b",
    r"\bread\s+out\s+(?:your\s+)?card\b",
    r"\btell\s+me\s+your\s+card\b",
    r"\bgive\s+(?:me\s+)?your\s+card\b",
    r"\bshare\s+(?:your\s+)?card\b",
]

ALL_PATTERNS = CREDIT_CARD_PATTERNS + SENSITIVE_PATTERNS + DIRECT_REQUEST_PATTERNS


def _compile_patterns(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


COMPILED_PATTERNS = _compile_patterns(ALL_PATTERNS)


def validate_playbook_safety(text: str) -> dict:
    if not text or not isinstance(text, str):
        return {"safe": True, "detected_terms": [], "warning": None}

    detected_terms: list[str] = []

    for pattern in COMPILED_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            for match in matches:
                if isinstance(match, tuple):
                    detected_terms.extend([m for m in match if m])
                else:
                    detected_terms.append(match)

    unique_terms = list(set(detected_terms))

    if unique_terms:
        warning = (
            "Playbook contains potentially sensitive PII requests. "
            "Please review the content for credit card or other sensitive data requests."
        )
        return {
            "safe": False,
            "warning": warning,
            "detected_terms": unique_terms,
        }

    return {"safe": True, "detected_terms": [], "warning": None}