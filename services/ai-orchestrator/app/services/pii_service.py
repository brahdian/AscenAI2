"""
PII Pseudonymization Service — Microsoft Presidio Edition

Uses presidio-analyzer to securely identify PII/Health Data and 
replaces it with email-like pseudo-values to bypass LLM safety filters.
"""
import json
import os
import re
import uuid
import hmac
import hashlib
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
import structlog

from app.core.config import settings

from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_anonymizer import AnonymizerEngine

logger = structlog.get_logger(__name__)

PII_PSEUDO_DOMAIN = os.getenv("PII_PSEUDO_DOMAIN", "ascenai.private")

_analyzer: Optional[AnalyzerEngine] = None
_anonymizer: Optional[AnonymizerEngine] = None

async def warmup() -> None:
    """Pre-warm PII service at startup and configure Presidio."""
    global _analyzer, _anonymizer
    if _analyzer is None:
        logger.info("pii_service_presidio_init_start")
        # Load spaCy model inside AnalyzerEngine
        # Defaulting to standard engine; in prod this would use en_core_sci_sm for HIPAA NER
        _analyzer = AnalyzerEngine()
        
        # Robust Recognizer for Medical/Health Conditions (HIPAA Readiness)
        # This catch-all pattern covers common symptoms, diseases, medications and records.
        health_regex = (
            r"\b(headache|fever|cough|chest pain|stroke|cancer|diabetes|asthma|depression|anxiety|"
            r"pain|COVID|flu|hypertension|arthritis|alzheimer|dementia|bipolar|schizophrenia|"
            r"autism|adhd|cholesterol|insulin|ibuprofen|aspirin|penicillin|vicodin|lipitor|"
            r"blood pressure|mri|x-ray|ct scan|biopsy|surgery|rehab|diagnosis|prognosis|"
            r"cardiology|oncology|psychiatry|dentist|surgery|clinic|hospital)\b"
        )
        
        health_recognizer = PatternRecognizer(
            supported_entity="HEALTH_CONDITION",
            patterns=[
                Pattern(
                    name="medical_entities_and_symptoms",
                    regex=health_regex,
                    score=0.85
                )
            ]
        )
        _analyzer.registry.add_recognizer(health_recognizer)
        
        # Zenith Pillar 2: Deep Value Redaction for technical artifacts
        secret_regex = r"\b(sk-[a-zA-Z0-9]{20,}|AIza[0-9A-Za-z-_]{35}|AKIA[0-9A-Z]{16})\b"
        secret_recognizer = PatternRecognizer(
            supported_entity="SECRET_KEY",
            patterns=[Pattern(name="secret_keys", regex=secret_regex, score=0.95)]
        )
        _analyzer.registry.add_recognizer(secret_recognizer)

        token_regex = r"\b(ey[a-zA-Z0-9._-]{20,})\b" # JWTs starting with 'ey'
        token_recognizer = PatternRecognizer(
            supported_entity="BEARER_TOKEN",
            patterns=[Pattern(name="tokens", regex=token_regex, score=0.95)]
        )
        _analyzer.registry.add_recognizer(token_recognizer)

        # Add support for SSN/International equivalents if not in baseline
        _anonymizer = AnonymizerEngine()
        logger.info("pii_service_presidio_init_complete", method="presidio_hybrid_engine")

def redact(text: str, hipaa_mode: bool = False) -> str:
    """One-way PII redaction for output guardrail. Replaces PII with [TYPE] labels."""
    if not text or _analyzer is None:
        return text
    
    # HIPAA Mode: Lower threshold to 0.25 to be more aggressive
    threshold = 0.25 if hipaa_mode else 0.4
    results = _analyzer.analyze(text=text, language='en', score_threshold=threshold)
    results.sort(key=lambda x: x.start, reverse=True)
    
    result_text = text
    for r in results:
        result_text = result_text[:r.start] + f"[{r.entity_type}]" + result_text[r.end:]
    return result_text


# ---------------------------------------------------------------------------
# Session-level PII Context
# ---------------------------------------------------------------------------

@dataclass
class PIIContext:
    """Stores PII mapping for a single session."""
    tenant_id: str = ""
    real_to_pseudo: Dict[str, str] = field(default_factory=dict)  # real -> pseudo
    pseudo_to_real: Dict[str, str] = field(default_factory=dict)  # pseudo -> real
    
    def get_pseudo(self, pii_type: str, real_value: str) -> str:
        """Get or create pseudo-value for real PII."""
        if real_value in self.real_to_pseudo:
            return self.real_to_pseudo[real_value]
        
        pseudo = self._generate_pseudo(pii_type, real_value)
        self.real_to_pseudo[real_value] = pseudo
        self.pseudo_to_real[pseudo] = real_value
        logger.info("pii_pseudo_created", pii_type=pii_type, pseudo=pseudo)
        return pseudo
    
    def get_real(self, pseudo_value: str) -> Optional[str]:
        """Get real value for pseudo-value."""
        return self.pseudo_to_real.get(pseudo_value)
    
    def has_mappings(self) -> bool:
        return len(self.real_to_pseudo) > 0
    
    def _generate_pseudo(self, pii_type: str, value: str) -> str:
        """
        Generate a DETERMINISTIC pseudo-value for a given PII string.
        Uses HMAC-SHA256 keyed by the system secret and scoped to the tenant.
        This ensures RAG works between redacted queries and redacted docs.
        """
        # Create a unique but deterministic hash for this value within this tenant
        h = hmac.new(
            settings.SECRET_KEY.encode(),
            f"{self.tenant_id}:{value}".encode(),
            hashlib.sha256
        )
        hash_id = h.hexdigest()[:8]

        if pii_type == 'EMAIL_ADDRESS':
            return f"user_{hash_id}@{PII_PSEUDO_DOMAIN}"
        elif pii_type == 'PHONE_NUMBER':
            return f"+1-555-{hash_id[:4]}"
        elif pii_type == 'CREDIT_CARD':
            return f"4000-{hash_id[:4]}-{hash_id[4:8]}-0001"
        elif pii_type in ('US_SSN', 'SIN'):
            return f"{hash_id[:3]}-{hash_id[3:5]}-0001"
        elif pii_type == 'PERSON':
            return f"Person_{hash_id[:4]}"
        elif pii_type == 'LOCATION':
            return f"Location_{hash_id[:4]}"
        elif pii_type == 'HEALTH_CONDITION':
            return f"Condition_{hash_id[:4]}"
        elif pii_type == 'SECRET_KEY':
            return f"Secret_{hash_id[:4]}..."
        elif pii_type == 'BEARER_TOKEN':
            return f"Token_{hash_id[:4]}..."
        else:
            return f"ref_{hash_id}@{PII_PSEUDO_DOMAIN}"
    
    def to_dict(self) -> dict:
        return {
            "tid": self.tenant_id,
            "r2p": self.real_to_pseudo,
            "p2r": self.pseudo_to_real,
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> "PIIContext":
        ctx = cls(tenant_id=d.get("tid", ""))
        ctx.real_to_pseudo = d.get("r2p", {})
        ctx.pseudo_to_real = d.get("p2r", {})
        return ctx


# ---------------------------------------------------------------------------
# Redis persistence
# ---------------------------------------------------------------------------

async def load_context(session_id: str, redis, tenant_id: str = "") -> PIIContext:
    """Load PII context from Redis."""
    if redis is None:
        return PIIContext(tenant_id=tenant_id)
    try:
        raw = await redis.get(f"pii_ctx:{session_id}")
        if raw:
            ctx = PIIContext.from_dict(json.loads(raw))
            # If loaded context was missing tid, backfill it
            if not ctx.tenant_id:
                ctx.tenant_id = tenant_id
            return ctx
    except Exception as e:
        logger.warning("pii_ctx_load_failed", session_id=session_id, error=str(e))
    return PIIContext(tenant_id=tenant_id)


async def save_context(session_id: str, ctx: PIIContext, redis) -> None:
    """Save PII context to Redis with 2-hour TTL."""
    if redis is None or not ctx.has_mappings():
        return
    try:
        data = json.dumps(ctx.to_dict(), separators=(',', ':'))
        await redis.setex(f"pii_ctx:{session_id}", 7200, data)
        logger.info("pii_ctx_saved", session_id=session_id, mappings=len(ctx.real_to_pseudo))
    except Exception as e:
        logger.warning("pii_ctx_save_failed", session_id=session_id, error=str(e))


# ---------------------------------------------------------------------------
# Redaction: Replace real PII with pseudo-values BEFORE LLM
# ---------------------------------------------------------------------------

def redact_pii(text: str, ctx: PIIContext, session_id: str = "", hipaa_mode: bool = False) -> str:
    """Replace real PII with pseudo-values that look natural."""
    if not text:
        logger.warning("pii_redact_empty", session_id=session_id)
        return text

    logger.info("pii_redact_start", session_id=session_id, text_preview=text[:100], hipaa_mode=hipaa_mode)
    
    if _analyzer is None:
        logger.error("presidio_analyzer_not_initialized")
        return text

    # HIPAA Mode: Lower threshold to 0.25 to be more aggressive
    threshold = 0.25 if hipaa_mode else 0.4
    results = _analyzer.analyze(text=text, language='en', score_threshold=threshold)
    
    if not results:
        logger.info("pii_no_match", session_id=session_id, text_preview=text[:100])
        return text

    # Sort results in reverse so offsets don't change during replacement
    results.sort(key=lambda x: x.start, reverse=True)
    
    result_text = text
    found_types = []
    
    for r in results:
        real_value = text[r.start:r.end]
        pseudo = ctx.get_pseudo(r.entity_type, real_value)
        result_text = result_text[:r.start] + pseudo + result_text[r.end:]
        found_types.append(r.entity_type)
        logger.info("pii_replaced", session_id=session_id, pii_type=r.entity_type, pseudo=pseudo)

    logger.info("pii_redacted", session_id=session_id, types=list(set(found_types)),
               mappings=len(ctx.real_to_pseudo))
    
    return result_text


# ---------------------------------------------------------------------------
# Restoration: Replace pseudo-values with real values on output
# ---------------------------------------------------------------------------

def restore_pii(text: str, ctx: PIIContext, session_id: str = "") -> str:
    """Restore pseudo-values to real values in output."""
    if not text or not ctx.has_mappings():
        return text

    result = text
    for pseudo, real in ctx.pseudo_to_real.items():
        if pseudo in result:
            result = result.replace(pseudo, real)
            logger.info("pii_restored", session_id=session_id, pseudo=pseudo[:20] + "...")
    
    return result

def restore_dict(d: dict, ctx: PIIContext, session_id: str = "") -> dict:
    """Restore PII in dict values (for tool arguments)."""
    if not ctx.has_mappings():
        return d
    return {
        k: restore_pii(v, ctx, session_id) if isinstance(v, str) else v
        for k, v in d.items()
    }


def restore_context(items: list[dict], ctx: PIIContext, session_id: str = "") -> list[dict]:
    """Restore PII in a list of context items (from MCP retrieval)."""
    if not ctx.has_mappings():
        return items
    
    restored = []
    for item in items:
        # Shallow copy to avoid mutating the original retrieved objects
        new_item = dict(item)
        if "content" in new_item and isinstance(new_item["content"], str):
            new_item["content"] = restore_pii(new_item["content"], ctx, session_id)
        restored.append(new_item)
    return restored


def redact_dict(d: dict, ctx: PIIContext, session_id: str = "", hipaa_mode: bool = False) -> dict:
    """Redact PII in dict values (for tool results going back to LLM)."""
    return {
        k: redact_pii(v, ctx, session_id, hipaa_mode=hipaa_mode) if isinstance(v, str) else v
        for k, v in d.items()
    }


def redact_for_display(text: str, ctx: PIIContext, hipaa_mode: bool = False) -> str:
    """Redact PII for chat history display.

    Handles both:
    1. Pseudo-values (user_x7k2m@ascenai.private) -> [EMAIL]
    2. Real PII values that may have been restored -> [EMAIL]
    """
    if not text:
        return text

    result = text

    # First, redact pseudo-values (if they still exist in text)
    if ctx and ctx.has_mappings():
        for pseudo, real in ctx.pseudo_to_real.items():
            if pseudo.startswith('user_') and PII_PSEUDO_DOMAIN in pseudo:
                result = result.replace(pseudo, '[EMAIL]')
            elif pseudo.startswith('+1-555'):
                result = result.replace(pseudo, '[PHONE]')
            elif pseudo.startswith('4000-'):
                result = result.replace(pseudo, '[CREDIT_CARD]')
            elif pseudo.startswith('Person_'):
                result = result.replace(pseudo, '[PERSON]')
            elif pseudo.startswith('Location_'):
                result = result.replace(pseudo, '[LOCATION]')
            elif pseudo.startswith('Condition_'):
                result = result.replace(pseudo, '[HEALTH_CONDITION]')
            elif re.match(r'\w{3}-\w{2}-0001', pseudo):
                result = result.replace(pseudo, '[SSN]')
            elif '@' in pseudo:
                result = result.replace(pseudo, '[EMAIL]')
            else:
                result = result.replace(pseudo, '[PII]')

    # Also apply the one-way redaction to catch any raw PII that slipped through
    result = redact(result, hipaa_mode=hipaa_mode)
    
    return result


def redact_deep(obj: Any, hipaa_mode: bool = False) -> Any:
    """Recursively redact PII in strings within any object (list, dict, etc)."""
    if isinstance(obj, str):
        return redact(obj, hipaa_mode=hipaa_mode)
    if isinstance(obj, dict):
        return {k: redact_deep(v, hipaa_mode=hipaa_mode) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_deep(v, hipaa_mode=hipaa_mode) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Streaming Parser for Real-time Token Restoration
# ---------------------------------------------------------------------------

class PIIStreamingParser:
    """
    Accumulates chunks of text and replaces pseudo-values with real values.
    Handles pseudo-values that might be split across chunks.
    """
    def __init__(self, ctx: PIIContext, session_id: str = ""):
        self.ctx = ctx
        self.session_id = session_id
        self.buffer = ""
        # Longest possible pseudo-value length to wait for potential matches
        self.max_pseudo_len = 64 

    def process_chunk(self, chunk: str) -> str:
        self.buffer += chunk
        
        # If we have potential pseudo-tokens, we wait until we have enough buffer
        # to ensure we don't return a partial token.
        # For simplicity, we just replace everything we can in the current buffer
        # and keep a small tail.
        
        result = self.buffer
        for pseudo, real in self.ctx.pseudo_to_real.items():
            if pseudo in result:
                result = result.replace(pseudo, real)
        
        # Keep the last max_pseudo_len characters in buffer to catch split tokens
        if len(result) > self.max_pseudo_len:
            to_return = result[:-self.max_pseudo_len]
            self.buffer = result[-self.max_pseudo_len:]
            return to_return
        else:
            self.buffer = result
            return ""

    def flush(self) -> str:
        final = self.buffer
        for pseudo, real in self.ctx.pseudo_to_real.items():
            final = final.replace(pseudo, real)
        self.buffer = ""
        return final


def create_streaming_parser(ctx: PIIContext, session_id: str = "") -> PIIStreamingParser:
    """Factory for PIIStreamingParser."""
    return PIIStreamingParser(ctx, session_id)
