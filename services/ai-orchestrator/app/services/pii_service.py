"""
PII detection, redaction, and reversible pseudonymization using Microsoft Presidio.

Two modes:
  1. pii_redaction=True   — one-way redaction of output text (replaces PII with type labels)
  2. pii_pseudonymization — two-pass: anonymize input before LLM, restore original values
                            from response so the user receives personalised replies

Entity types detected (Presidio defaults + extras):
  PERSON, EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, IBAN_CODE, IP_ADDRESS,
  LOCATION, DATE_TIME, URL, DOMAIN_NAME, NRP (nationality/religion/political),
  US_SSN, US_BANK_NUMBER, US_DRIVER_LICENSE, US_PASSPORT, US_ITIN,
  UK_NHS, SG_NRIC_FIN, IN_PAN, AU_ABN, CA_SIN, MEDICAL_LICENSE, CRYPTO
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Lazy-load Presidio — import cost ~300 ms first call (spaCy model load).
# We instantiate once at module level so subsequent calls are fast.
# ---------------------------------------------------------------------------
_analyzer = None
_anonymizer = None


def _get_analyzer():
    global _analyzer
    if _analyzer is None:
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider

            # Prefer the medium model for balance of accuracy vs image size.
            # Falls back to small if medium is not installed.
            for model_name in ("en_core_web_lg", "en_core_web_md", "en_core_web_sm"):
                try:
                    import spacy
                    spacy.load(model_name)
                    _spacy_model = model_name
                    break
                except OSError:
                    continue
            else:
                _spacy_model = "en_core_web_sm"  # last resort

            provider = NlpEngineProvider(nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": _spacy_model}],
            })
            nlp_engine = provider.create_engine()
            _analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
            logger.info("presidio_analyzer_loaded", model=_spacy_model)
        except ImportError:
            logger.warning(
                "presidio_not_installed",
                detail="Install presidio-analyzer presidio-anonymizer spacy en_core_web_sm",
            )
            _analyzer = None
    return _analyzer


def _get_anonymizer():
    global _anonymizer
    if _anonymizer is None:
        try:
            from presidio_anonymizer import AnonymizerEngine
            _anonymizer = AnonymizerEngine()
            logger.info("presidio_anonymizer_loaded")
        except ImportError:
            _anonymizer = None
    return _anonymizer


# ---------------------------------------------------------------------------
# Public: simple one-way redaction (replaces PII with <ENTITY_TYPE>)
# ---------------------------------------------------------------------------

# Entities to detect in every call — ordered by sensitivity
_ENTITIES = [
    "CREDIT_CARD", "IBAN_CODE", "US_SSN", "US_BANK_NUMBER", "US_ITIN",
    "US_PASSPORT", "US_DRIVER_LICENSE", "UK_NHS", "SG_NRIC_FIN", "IN_PAN",
    "AU_ABN", "CA_SIN", "MEDICAL_LICENSE", "CRYPTO",
    "EMAIL_ADDRESS", "PHONE_NUMBER", "IP_ADDRESS",
    "PERSON", "LOCATION", "URL", "DOMAIN_NAME", "DATE_TIME", "NRP",
]

# Regex fallback when Presidio is unavailable
_EMAIL_RE = re.compile(r'\b[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}\b')
_PHONE_RE = re.compile(r'\b(\+?[\d][\d\s\-().]{7,}\d)\b')
_CARD_RE  = re.compile(r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b')


def redact(text: str, score_threshold: float = 0.6) -> str:
    """
    One-way PII redaction — replaces detected entities with their type labels.
    Falls back to regex if Presidio is not installed.

    Args:
        text: Input string.
        score_threshold: Presidio confidence threshold (0-1).

    Returns:
        Redacted string, e.g. "Call [PHONE_NUMBER] or email [EMAIL_ADDRESS]"
    """
    analyzer = _get_analyzer()
    if analyzer is None:
        # Regex fallback
        text = _EMAIL_RE.sub('[EMAIL_ADDRESS]', text)
        text = _PHONE_RE.sub('[PHONE_NUMBER]', text)
        text = _CARD_RE.sub('[CREDIT_CARD]', text)
        return text

    try:
        anonymizer = _get_anonymizer()
        if anonymizer is None:
            return text

        from presidio_anonymizer.entities import OperatorConfig

        results = analyzer.analyze(text=text, language="en", entities=_ENTITIES,
                                   score_threshold=score_threshold)
        if not results:
            return text

        anonymized = anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators={"DEFAULT": OperatorConfig("replace", {"new_value": lambda r: f"[{r.entity_type}]"})},
        )
        return anonymized.text
    except Exception as exc:
        logger.warning("presidio_redact_failed", error=str(exc))
        return text


# ---------------------------------------------------------------------------
# Reversible pseudonymization
# ---------------------------------------------------------------------------

# Token format: <ENTITY_TYPE_INDEX> e.g. <PERSON_0>, <EMAIL_ADDRESS_1>
_TOKEN_RE = re.compile(r'<([A-Z_]+)_(\d+)>')


@dataclass
class PseudonymizationContext:
    """
    Holds the token↔value mapping for one conversation turn (or session).

    The same value always maps to the same token so cross-references
    ("send it to John" after establishing <PERSON_0>=John) stay coherent.
    """
    # Maps token string → original value, e.g. "<PERSON_0>" → "John Smith"
    token_to_value: dict[str, str] = field(default_factory=dict)
    # Reverse map for dedup: normalised value → token
    value_to_token: dict[str, str] = field(default_factory=dict)
    # Counters per entity type
    _counters: dict[str, int] = field(default_factory=dict)

    def _make_token(self, entity_type: str, value: str) -> str:
        """Return existing token for value, or mint a new one."""
        norm = value.strip().lower()
        if norm in self.value_to_token:
            return self.value_to_token[norm]
        idx = self._counters.get(entity_type, 0)
        self._counters[entity_type] = idx + 1
        token = f"<{entity_type}_{idx}>"
        self.token_to_value[token] = value
        self.value_to_token[norm] = token
        return token

    def anonymize(self, text: str, score_threshold: float = 0.5) -> str:
        """
        Replace PII in *text* with tokens. Updates internal mapping.
        Returns the anonymized text safe to send to the LLM.
        """
        analyzer = _get_analyzer()
        if analyzer is None:
            return text  # fail-open: send original if Presidio unavailable

        try:
            results = analyzer.analyze(text=text, language="en", entities=_ENTITIES,
                                       score_threshold=score_threshold)
            if not results:
                return text

            # Sort descending by start so replacements don't shift offsets
            results = sorted(results, key=lambda r: r.start, reverse=True)
            chars = list(text)
            for result in results:
                original = text[result.start:result.end]
                token = self._make_token(result.entity_type, original)
                chars[result.start:result.end] = list(token)

            return "".join(chars)
        except Exception as exc:
            logger.warning("presidio_anonymize_failed", error=str(exc))
            return text

    def restore(self, text: str) -> str:
        """
        Replace all <ENTITY_TYPE_N> tokens in *text* with their original values.
        Tokens the LLM invented (not in our map) are left as-is.
        """
        def _replace(m: re.Match) -> str:
            token = m.group(0)
            return self.token_to_value.get(token, token)

        return _TOKEN_RE.sub(_replace, text)

    def to_dict(self) -> dict:
        """Serialise to a plain dict for Redis storage."""
        return {
            "token_to_value": self.token_to_value,
            "value_to_token": self.value_to_token,
            "counters": self._counters,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PseudonymizationContext":
        ctx = cls()
        ctx.token_to_value = data.get("token_to_value", {})
        ctx.value_to_token = data.get("value_to_token", {})
        ctx._counters = data.get("counters", {})
        return ctx


# ---------------------------------------------------------------------------
# Redis-backed session persistence for multi-turn pseudonymization
# ---------------------------------------------------------------------------

_CTX_TTL = 3600  # 1 hour — same as session idle timeout


async def load_context(session_id: str, redis) -> PseudonymizationContext:
    """Load the pseudonymization context for a session from Redis."""
    if redis is None:
        return PseudonymizationContext()
    try:
        import json
        raw = await redis.get(f"pii_ctx:{session_id}")
        if raw:
            return PseudonymizationContext.from_dict(json.loads(raw))
    except Exception as exc:
        logger.warning("pii_ctx_load_failed", session_id=session_id, error=str(exc))
    return PseudonymizationContext()


async def save_context(session_id: str, ctx: PseudonymizationContext, redis) -> None:
    """Persist the pseudonymization context for a session in Redis."""
    if redis is None or not ctx.token_to_value:
        return
    try:
        import json
        await redis.setex(f"pii_ctx:{session_id}", _CTX_TTL, json.dumps(ctx.to_dict()))
    except Exception as exc:
        logger.warning("pii_ctx_save_failed", session_id=session_id, error=str(exc))


# ---------------------------------------------------------------------------
# System prompt addendum — tells the LLM to preserve tokens
# ---------------------------------------------------------------------------

PSEUDONYMIZATION_SYSTEM_NOTE = """
IMPORTANT — Privacy Protection:
The user's message has had personally-identifiable information (PII) replaced with
placeholder tokens like <PERSON_0>, <EMAIL_ADDRESS_1>, <PHONE_NUMBER_2>, etc.
You MUST preserve these tokens exactly as written whenever you refer to that information.
Do NOT invent new tokens. Do NOT substitute pronouns for tokens when the token is needed
for the user to understand the response (e.g. "I'll email <EMAIL_ADDRESS_0>" is correct;
"I'll email you" loses the reference).
"""
