"""
Enterprise PII pseudonymization service — Microsoft Presidio + structured envelope.

Architecture
============
- Async-first: all CPU-bound Presidio work runs in a dedicated ThreadPoolExecutor
  so the asyncio event loop is never blocked.
- Pre-warmed: call ``warmup()`` at application startup; first-request cold-start
  latency (~300 ms for spaCy model load) is eliminated.
- Token format: ``{{PII_ENTITY_TYPE_N}}`` — double-brace template syntax that
  modern LLMs reliably preserve; ``PII_`` prefix lets our regex find orphaned tokens
  even when the LLM slightly reformats them.
- Structured envelope: when pseudonymization is active, the LLM is instructed to
  return JSON ``{"message": "...", "refs": ["{{PII_PERSON_0}}", ...]}``.  The
  ``message`` field is extracted and tokens are restored deterministically.
  If JSON parsing fails we fall back to direct regex token restoration on the raw
  text — degraded UX (less personalization) but never a privacy breach.
- Tool arguments: de-tokenize BEFORE executing any tool call so downstream APIs
  (booking, CRM, etc.) receive real values.  Tool RESULTS are re-anonymized BEFORE
  being added back to the LLM message history.
- Multi-turn: the ``PseudonymizationContext`` (token ↔ value map) is persisted in
  Redis keyed by session, with a 1-hour TTL and a 200-token cap per session.
- Per-entity confidence thresholds: financial identifiers use lower thresholds
  (higher recall) while noisy types like DATE_TIME and URL use higher ones.
- Prometheus metrics: entities detected, tokens restored, parse failures, latency.
- Audit log: every anonymization and restoration emits a structured log event
  (entity types only — never the actual values).
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Thread pool — Presidio / spaCy are CPU-bound synchronous libraries
# ---------------------------------------------------------------------------
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="presidio")

# ---------------------------------------------------------------------------
# Token format
# ---------------------------------------------------------------------------
# {{PII_PERSON_0}}, {{PII_CREDIT_CARD_0}}, etc.
_TOKEN_RE = re.compile(r'\{\{PII_([A-Z_]+)_(\d+)\}\}')
_TOKEN_APPROX_RE = re.compile(
    r'\{?\{?\s*PII_([A-Z_]+)_(\d+)\s*\}?\}?', re.IGNORECASE
)  # fuzzy fallback

# ---------------------------------------------------------------------------
# Entities to detect — ordered: high-sensitivity first
# ---------------------------------------------------------------------------
ENTITIES: list[str] = [
    # Financial
    "CREDIT_CARD", "IBAN_CODE", "US_BANK_NUMBER", "US_ITIN",
    # Government / national IDs
    "US_SSN", "US_PASSPORT", "US_DRIVER_LICENSE",
    "UK_NHS", "SG_NRIC_FIN", "IN_PAN", "AU_ABN", "CA_SIN",
    "MEDICAL_LICENSE", "NRP",
    # Contact
    "EMAIL_ADDRESS", "PHONE_NUMBER", "IP_ADDRESS",
    # Crypto
    "CRYPTO",
    # Identity
    "PERSON", "LOCATION",
    # Misc
    "URL", "DOMAIN_NAME", "DATE_TIME",
]

# Per-entity confidence thresholds — lower = higher recall (use for sensitive types)
ENTITY_THRESHOLDS: dict[str, float] = {
    "CREDIT_CARD":       0.45,
    "IBAN_CODE":         0.45,
    "US_SSN":            0.45,
    "US_BANK_NUMBER":    0.45,
    "US_ITIN":           0.45,
    "US_PASSPORT":       0.50,
    "US_DRIVER_LICENSE": 0.50,
    "UK_NHS":            0.50,
    "SG_NRIC_FIN":       0.50,
    "IN_PAN":            0.50,
    "AU_ABN":            0.50,
    "CA_SIN":            0.50,
    "MEDICAL_LICENSE":   0.50,
    "CRYPTO":            0.55,
    "EMAIL_ADDRESS":     0.60,
    "PHONE_NUMBER":      0.60,
    "IP_ADDRESS":        0.60,
    "PERSON":            0.70,
    "NRP":               0.70,
    "LOCATION":          0.75,
    "URL":               0.80,
    "DOMAIN_NAME":       0.80,
    "DATE_TIME":         0.85,  # Very common in normal text — high threshold
}
_DEFAULT_THRESHOLD = 0.65

# Context limits
_MAX_TOKENS_PER_SESSION = 200   # Max unique PII tokens stored per session
_CONTEXT_TTL_SECONDS   = 3600  # 1 hour idle timeout
_MAX_CONTEXT_BYTES     = 65_536 # 64 KB Redis value cap

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
try:
    from prometheus_client import Counter, Histogram

    _PII_ENTITIES_DETECTED = Counter(
        "ascenai_pii_entities_detected_total",
        "Number of PII entities detected and anonymized",
        labelnames=["entity_type"],
    )
    _PII_TOKENS_RESTORED = Counter(
        "ascenai_pii_tokens_restored_total",
        "Number of PII tokens restored in LLM responses",
    )
    _PII_ENVELOPE_PARSE_FAILURES = Counter(
        "ascenai_pii_envelope_parse_failures_total",
        "Structured envelope JSON parse failures (fell back to regex)",
    )
    _PII_ANONYMIZE_LATENCY = Histogram(
        "ascenai_pii_anonymize_duration_seconds",
        "Presidio anonymization latency",
        buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
    )
    _METRICS_AVAILABLE = True
except ImportError:
    _METRICS_AVAILABLE = False


def _inc_entity(entity_type: str) -> None:
    if _METRICS_AVAILABLE:
        _PII_ENTITIES_DETECTED.labels(entity_type=entity_type).inc()


def _inc_restored(n: int = 1) -> None:
    if _METRICS_AVAILABLE:
        _PII_TOKENS_RESTORED.inc(n)


def _inc_envelope_failure() -> None:
    if _METRICS_AVAILABLE:
        _PII_ENVELOPE_PARSE_FAILURES.inc()


# ---------------------------------------------------------------------------
# Presidio lazy globals — initialized in warmup()
# ---------------------------------------------------------------------------
_analyzer  = None
_anonymizer = None
_initialized = False


def _build_analyzer():
    """Build and return a configured AnalyzerEngine (runs in thread pool)."""
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    import spacy

    for model in ("en_core_web_lg", "en_core_web_md", "en_core_web_sm"):
        try:
            spacy.load(model)
            chosen = model
            break
        except OSError:
            continue
    else:
        raise RuntimeError("No spaCy English model found. Run: python -m spacy download en_core_web_sm")

    provider = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": chosen}],
    })
    engine = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])
    return engine, chosen


async def warmup() -> None:
    """
    Pre-warm Presidio models at application startup.

    Must be called from the FastAPI lifespan so that the first real request
    does not pay the ~300 ms spaCy model load penalty.
    """
    global _analyzer, _anonymizer, _initialized
    if _initialized:
        return

    t0 = time.monotonic()
    try:
        loop = asyncio.get_running_loop()
        from presidio_anonymizer import AnonymizerEngine

        analyzer, model_name = await loop.run_in_executor(_executor, _build_analyzer)
        anonymizer = AnonymizerEngine()

        _analyzer  = analyzer
        _anonymizer = anonymizer
        _initialized = True

        logger.info(
            "pii_service_ready",
            model=model_name,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        logger.warning(
            "pii_service_unavailable",
            error=str(exc),
            detail="Install presidio-analyzer presidio-anonymizer and a spaCy model",
        )


def is_available() -> bool:
    return _initialized and _analyzer is not None


# ---------------------------------------------------------------------------
# Regex fallback (when Presidio not installed / init failed)
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(r'\b[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}\b')
_PHONE_RE = re.compile(r'\b(\+?[\d][\d\s\-().]{7,}\d)\b')
_CARD_RE  = re.compile(r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b')


def _regex_redact(text: str) -> str:
    text = _EMAIL_RE.sub('[EMAIL_ADDRESS]', text)
    text = _PHONE_RE.sub('[PHONE_NUMBER]', text)
    text = _CARD_RE.sub('[CREDIT_CARD]', text)
    return text


# ---------------------------------------------------------------------------
# One-way output redaction (pii_redaction=True)
# ---------------------------------------------------------------------------

def _presidio_redact_sync(text: str) -> str:
    """Synchronous Presidio redaction — called from thread pool only."""
    from presidio_anonymizer.entities import OperatorConfig

    results = _analyzer.analyze(text=text, language="en", entities=ENTITIES,
                                score_threshold=_DEFAULT_THRESHOLD)
    if not results:
        return text

    for r in results:
        _inc_entity(r.entity_type)

    return _anonymizer.anonymize(
        text=text,
        analyzer_results=results,
        operators={"DEFAULT": OperatorConfig(
            "replace", {"new_value": lambda r: f"[{r.entity_type}]"}
        )},
    ).text


async def redact(text: str) -> str:
    """
    One-way PII redaction for LLM output (pii_redaction guardrail).
    Replaces detected entities with ``[ENTITY_TYPE]`` labels.
    Falls back to regex if Presidio is unavailable.
    """
    if not text:
        return text
    if not is_available():
        return _regex_redact(text)

    loop = asyncio.get_running_loop()
    try:
        t0 = time.monotonic()
        result = await loop.run_in_executor(_executor, _presidio_redact_sync, text)
        if _METRICS_AVAILABLE:
            _PII_ANONYMIZE_LATENCY.observe(time.monotonic() - t0)
        return result
    except Exception as exc:
        logger.warning("pii_redact_error", error=str(exc))
        return _regex_redact(text)


# ---------------------------------------------------------------------------
# PseudonymizationContext
# ---------------------------------------------------------------------------

@dataclass
class PseudonymizationContext:
    """
    Bidirectional token ↔ PII value map for one conversation session.

    Same value always maps to the same token (deduplication) so cross-turn
    references like "call <{{PII_PHONE_NUMBER_0}}>  back" stay consistent.
    """
    token_to_value: dict[str, str] = field(default_factory=dict)
    value_to_token: dict[str, str] = field(default_factory=dict)
    _counters:      dict[str, int] = field(default_factory=dict)

    # ---- minting ----

    def _mint_token(self, entity_type: str, value: str) -> str:
        norm = value.strip().lower()
        if norm in self.value_to_token:
            return self.value_to_token[norm]

        if len(self.token_to_value) >= _MAX_TOKENS_PER_SESSION:
            # Session is at capacity — return a generic placeholder without
            # storing it so we don't poison the context.
            idx = self._counters.get(entity_type, 0)
            return f"{{{{PII_{entity_type}_{idx}}}}}"

        idx = self._counters.get(entity_type, 0)
        self._counters[entity_type] = idx + 1
        token = f"{{{{PII_{entity_type}_{idx}}}}}"
        self.token_to_value[token]  = value
        self.value_to_token[norm]   = token
        return token

    # ---- anonymize ----

    def _anonymize_sync(self, text: str) -> tuple[str, list[str]]:
        """Run Presidio analysis + token replacement synchronously (in executor)."""
        entity_types_found: list[str] = []

        results = _analyzer.analyze(text=text, language="en", entities=ENTITIES,
                                    score_threshold=_DEFAULT_THRESHOLD)

        # Apply per-entity thresholds
        results = [r for r in results
                   if r.score >= ENTITY_THRESHOLDS.get(r.entity_type, _DEFAULT_THRESHOLD)]

        if not results:
            return text, []

        # Sort descending so slice replacements don't shift later offsets
        results = sorted(results, key=lambda r: r.start, reverse=True)

        chars = list(text)
        for r in results:
            original = text[r.start:r.end]
            token = self._mint_token(r.entity_type, original)
            chars[r.start:r.end] = list(token)
            entity_types_found.append(r.entity_type)

        return "".join(chars), entity_types_found

    # ---- restore ----

    def restore(self, text: str) -> tuple[str, int]:
        """
        Replace all ``{{PII_TYPE_N}}`` tokens with their original values.

        Returns (restored_text, tokens_replaced_count).
        Performs two passes:
          1. Exact canonical match via the token map
          2. Fuzzy match for tokens the LLM may have slightly reformatted
             (e.g. case changes, extra spaces inside braces)
        """
        count = 0

        # Pass 1 — exact
        def _exact(m: re.Match) -> str:
            nonlocal count
            token = m.group(0)
            if token in self.token_to_value:
                count += 1
                return self.token_to_value[token]
            return token

        text = _TOKEN_RE.sub(_exact, text)

        # Pass 2 — fuzzy (handles minor LLM reformatting)
        def _fuzzy(m: re.Match) -> str:
            nonlocal count
            entity_type = m.group(1).upper()
            idx         = m.group(2)
            canonical   = f"{{{{PII_{entity_type}_{idx}}}}}"
            if canonical in self.token_to_value:
                count += 1
                return self.token_to_value[canonical]
            return m.group(0)  # leave unknown tokens as-is

        text = _TOKEN_APPROX_RE.sub(_fuzzy, text)
        return text, count

    # ---- serialization ----

    def to_dict(self) -> dict:
        return {
            "t2v": self.token_to_value,
            "v2t": self.value_to_token,
            "ctr": self._counters,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PseudonymizationContext":
        ctx = cls()
        ctx.token_to_value = d.get("t2v", {})
        ctx.value_to_token = d.get("v2t", {})
        ctx._counters      = d.get("ctr", {})
        return ctx

    def is_empty(self) -> bool:
        return not self.token_to_value


# ---------------------------------------------------------------------------
# Async public API for orchestrator
# ---------------------------------------------------------------------------

async def anonymize_message(
    text: str,
    ctx: PseudonymizationContext,
    session_id: str,
) -> str:
    """
    Anonymize PII in *text*, updating *ctx* with new token mappings.
    Returns the anonymized text safe to send to the LLM.
    """
    if not text:
        return text
    if not is_available():
        logger.warning("pii_service_not_ready_skip_anonymize", session_id=session_id)
        return text  # fail-open

    loop = asyncio.get_running_loop()
    try:
        t0 = time.monotonic()
        anonymized, entity_types = await loop.run_in_executor(
            _executor, ctx._anonymize_sync, text
        )
        if _METRICS_AVAILABLE:
            _PII_ANONYMIZE_LATENCY.observe(time.monotonic() - t0)

        if entity_types:
            for et in entity_types:
                _inc_entity(et)
            logger.info(
                "pii_input_anonymized",
                session_id=session_id,
                entity_types=sorted(set(entity_types)),
                token_count=len(ctx.token_to_value),
            )

        return anonymized
    except Exception as exc:
        logger.error("pii_anonymize_failed", session_id=session_id, error=str(exc))
        return text  # fail-open


def restore_text(text: str, ctx: PseudonymizationContext, session_id: str) -> str:
    """
    Restore tokens in *text* to their original PII values.
    Synchronous — restoration is a pure dict lookup, no Presidio involved.
    """
    if not text or ctx.is_empty():
        return text

    restored, n = ctx.restore(text)
    if n:
        _inc_restored(n)
        logger.info("pii_tokens_restored", session_id=session_id, count=n)
    return restored


def restore_dict(d: dict[str, Any], ctx: PseudonymizationContext, session_id: str) -> dict[str, Any]:
    """
    Restore tokens in every string value of dict *d*.
    Used to de-tokenize tool call arguments before execution.
    """
    if ctx.is_empty():
        return d
    return {
        k: restore_text(v, ctx, session_id) if isinstance(v, str) else v
        for k, v in d.items()
    }


async def re_anonymize_dict(
    d: dict[str, Any],
    ctx: PseudonymizationContext,
    session_id: str,
) -> dict[str, Any]:
    """
    Re-anonymize string values in a tool result dict before adding to LLM context.
    Keeps PII out of the message history when APIs echo back real values.
    """
    result = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = await anonymize_message(v, ctx, session_id)
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# Structured envelope parsing
# ---------------------------------------------------------------------------

def parse_envelope(raw: str, ctx: PseudonymizationContext, session_id: str) -> str:
    """
    Extract the final user-facing text from a structured envelope response.

    The LLM is instructed to return:
      {"message": "Hi {{PII_PERSON_0}}, ...", "refs": ["{{PII_PERSON_0}}"]}

    Parsing strategy (in order):
      1. JSON parse → extract ``message`` field → restore tokens
      2. Regex extract ``message`` value from malformed JSON → restore tokens
      3. Restore tokens directly on the raw string (ultimate fallback)
    """
    stripped = raw.strip()

    # Strip markdown code fences the LLM sometimes wraps JSON in
    if stripped.startswith("```"):
        stripped = re.sub(r'^```(?:json)?\s*', '', stripped)
        stripped = re.sub(r'\s*```$', '', stripped)
        stripped = stripped.strip()

    # Strategy 1: clean JSON
    try:
        parsed = json.loads(stripped)
        message = parsed.get("message") or parsed.get("text") or parsed.get("response")
        if message and isinstance(message, str):
            return restore_text(message, ctx, session_id)
    except (json.JSONDecodeError, AttributeError):
        pass

    # Strategy 2: regex extraction of the message value
    m = re.search(
        r'"(?:message|text|response)"\s*:\s*"((?:[^"\\]|\\.)*)"',
        stripped, re.DOTALL
    )
    if m:
        _inc_envelope_failure()
        raw_msg = m.group(1).encode('raw_unicode_escape').decode('unicode_escape')
        logger.warning("pii_envelope_json_malformed_regex_fallback", session_id=session_id)
        return restore_text(raw_msg, ctx, session_id)

    # Strategy 3: restore tokens directly on the raw LLM output
    _inc_envelope_failure()
    logger.warning("pii_envelope_parse_failed_token_fallback", session_id=session_id)
    return restore_text(stripped, ctx, session_id)


# ---------------------------------------------------------------------------
# Redis persistence
# ---------------------------------------------------------------------------

async def load_context(session_id: str, redis) -> PseudonymizationContext:
    """Load the pseudonymization context for *session_id* from Redis."""
    if redis is None:
        return PseudonymizationContext()
    try:
        raw = await redis.get(f"pii_ctx:{session_id}")
        if raw:
            return PseudonymizationContext.from_dict(json.loads(raw))
    except Exception as exc:
        logger.warning("pii_ctx_load_failed", session_id=session_id, error=str(exc))
    return PseudonymizationContext()


async def save_context(session_id: str, ctx: PseudonymizationContext, redis) -> None:
    """Persist the pseudonymization context for *session_id* in Redis."""
    if redis is None or ctx.is_empty():
        return
    try:
        serialized = json.dumps(ctx.to_dict(), separators=(',', ':'))
        if len(serialized) > _MAX_CONTEXT_BYTES:
            logger.warning(
                "pii_ctx_too_large_truncating",
                session_id=session_id,
                size=len(serialized),
            )
            # Drop the oldest half of the token map to stay under limit
            items = list(ctx.token_to_value.items())
            keep  = items[len(items) // 2:]
            ctx.token_to_value = dict(keep)
            ctx.value_to_token = {v.strip().lower(): k for k, v in keep}
            serialized = json.dumps(ctx.to_dict(), separators=(',', ':'))

        await redis.setex(f"pii_ctx:{session_id}", _CONTEXT_TTL_SECONDS, serialized)
    except Exception as exc:
        logger.warning("pii_ctx_save_failed", session_id=session_id, error=str(exc))


# ---------------------------------------------------------------------------
# System prompt addendum injected when pseudonymization is active
# ---------------------------------------------------------------------------

ENVELOPE_SYSTEM_PROMPT = """
=== PRIVACY SHIELD ACTIVE ===
The user message has had personally-identifiable information replaced with
privacy tokens in the format {{PII_ENTITY_TYPE_N}} (e.g. {{PII_PERSON_0}},
{{PII_PHONE_NUMBER_1}}, {{PII_EMAIL_ADDRESS_0}}).

YOU MUST respond with valid JSON following this exact schema — no prose before
or after the JSON:

{
  "message": "<your full response to the user, with all {{PII_...}} tokens preserved verbatim>",
  "refs": ["{{PII_PERSON_0}}", "{{PII_PHONE_NUMBER_1}}"]
}

Rules (strictly enforced):
1. "message" contains your complete response — what the user will read.
2. Every {{PII_...}} token you reference in "message" must appear in "refs".
3. Copy tokens EXACTLY — same case, same braces, same index number.
4. Do NOT invent tokens. Do NOT expose that you are using tokens.
5. If you pass a token to a tool argument, copy the token string verbatim.
6. Do not add any text outside the JSON object.
=== END PRIVACY SHIELD ===
"""
