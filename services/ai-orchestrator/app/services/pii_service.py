"""
PII Pseudonymization Service — Reference pseudo-values approach.

Uses email-like pseudo-values with configurable domain to avoid Gemini
safety filters redacting them:

- john@example.com → user_x7k2m@ascenai.private
- 647-123-4567 → +1-555-x7k2m
- 123-45-6789 → x7k-yz9-0001
- 4111-1111-1111-1111 → 4000-x7k2-yz9ab-0001

Why this works:
1. Natural-looking format that LLMs handle well
2. Private TLD domain avoids matching real email providers
3. Chat history shows [TYPE] labels via redact_for_display
4. Output restores real values from mapping
"""

import json
import os
import re
import time
import uuid
import hashlib
from typing import Optional, Dict
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger(__name__)

PII_PSEUDO_DOMAIN = os.getenv("PII_PSEUDO_DOMAIN", "ascenai.private")


async def warmup() -> None:
    """Pre-warm PII service at startup. No-op for regex-based detection."""
    logger.info("pii_service_ready", method="pseudo_values")


async def redact(text: str) -> str:
    """One-way PII redaction for output guardrail. Replaces PII with [TYPE] labels."""
    if not text:
        return text
    result = text
    for pii_type, pattern in PII_PATTERNS.items():
        result = pattern.sub(f"[{pii_type}]", result)
    return result


# ---------------------------------------------------------------------------
# PII Detection Regex Patterns
# ---------------------------------------------------------------------------
PII_PATTERNS = {
    'EMAIL': re.compile(r'\b[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}\b'),
    'PHONE': re.compile(r'\b(\+?1?\s*)?(\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})\b'),
    'CREDIT_CARD': re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'),
    'SIN': re.compile(r'\b\d{3}[\s-]?\d{3}[\s-]?\d{3}\b'),
    'SSN': re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
}


# ---------------------------------------------------------------------------
# Session-level PII Context
# ---------------------------------------------------------------------------

@dataclass
class PIIContext:
    """Stores PII mapping for a single session."""
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
        """Generate a pseudo-value that looks natural."""
        hash_id = hashlib.md5(value.encode()).hexdigest()[:6]

        if pii_type == 'EMAIL':
            # Natural email format: user_x7k2m@ascenai.private
            return f"user_{hash_id}@{PII_PSEUDO_DOMAIN}"
        elif pii_type == 'PHONE':
            # Natural phone format: +1-555-XXXX
            return f"+1-555-{hash_id[:4]}"
        elif pii_type == 'CREDIT_CARD':
            return f"4000-{hash_id[:4]}-{hash_id[4:8]}-0001"
        elif pii_type == 'SIN':
            return f"{hash_id[:3]}-{hash_id[3:6]}-0001"
        elif pii_type == 'SSN':
            return f"{hash_id[:3]}-{hash_id[3:5]}-0001"
        else:
            return f"ref_{hash_id}@{PII_PSEUDO_DOMAIN}"
    
    def to_dict(self) -> dict:
        return {
            "r2p": self.real_to_pseudo,
            "p2r": self.pseudo_to_real,
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> "PIIContext":
        ctx = cls()
        ctx.real_to_pseudo = d.get("r2p", {})
        ctx.pseudo_to_real = d.get("p2r", {})
        return ctx


# ---------------------------------------------------------------------------
# Redis persistence
# ---------------------------------------------------------------------------

async def load_context(session_id: str, redis) -> PIIContext:
    """Load PII context from Redis."""
    if redis is None:
        return PIIContext()
    try:
        raw = await redis.get(f"pii_ctx:{session_id}")
        if raw:
            return PIIContext.from_dict(json.loads(raw))
    except Exception as e:
        logger.warning("pii_ctx_load_failed", session_id=session_id, error=str(e))
    return PIIContext()


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

def redact_pii(text: str, ctx: PIIContext, session_id: str = "") -> str:
    """Replace real PII with pseudo-values that look natural."""
    if not text:
        logger.warning("pii_redact_empty", session_id=session_id)
        return text

    logger.info("pii_redact_start", session_id=session_id, text_preview=text[:100])
    result = text
    found_types = []

    for pii_type, pattern in PII_PATTERNS.items():
        def replacer(match, ptype=pii_type):
            real_value = match.group(0)
            pseudo = ctx.get_pseudo(ptype, real_value)
            logger.info("pii_replaced", session_id=session_id, pii_type=ptype,
                       pseudo=pseudo, real_preview=real_value[:20])
            return pseudo

        before = result
        result = pattern.sub(replacer, result)
        if result != before:
            found_types.append(pii_type)

    if found_types:
        logger.info("pii_redacted", session_id=session_id, types=found_types,
                   mappings=len(ctx.real_to_pseudo))
    else:
        logger.info("pii_no_match", session_id=session_id, text_preview=text[:100])

    return result


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


def redact_dict(d: dict, ctx: PIIContext, session_id: str = "") -> dict:
    """Redact PII in dict values (for tool results going back to LLM)."""
    return {
        k: redact_pii(v, ctx, session_id) if isinstance(v, str) else v
        for k, v in d.items()
    }


def redact_for_display(text: str, ctx: PIIContext) -> str:
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
            if '@' in pseudo and PII_PSEUDO_DOMAIN in pseudo:
                result = result.replace(pseudo, '[EMAIL]')
            elif pseudo.startswith('+1-555'):
                result = result.replace(pseudo, '[PHONE]')
            elif pseudo.startswith('4000-'):
                result = result.replace(pseudo, '[CREDIT_CARD]')
            elif re.match(r'\d{3}-\d{3}-\d{4}', pseudo):
                result = result.replace(pseudo, '[SIN]')
            elif re.match(r'\d{3}-\d{2}-\d{4}', pseudo):
                result = result.replace(pseudo, '[SSN]')
            elif '@' in pseudo:
                result = result.replace(pseudo, '[EMAIL]')
            else:
                result = result.replace(pseudo, '[PII]')

    # Second, redact any real PII that might have been restored by streaming parser
    for pii_type, pattern in PII_PATTERNS.items():
        result = pattern.sub(f'[{pii_type}]', result)

    return result


def redact_dict_for_display(d: dict, ctx: PIIContext) -> dict:
    """Redact pseudo-values in dict for chat history display."""
    return {
        k: redact_for_display(v, ctx) if isinstance(v, str) else v
        for k, v in d.items()
    }


# ---------------------------------------------------------------------------
# Streaming Parser — Character-by-character for real-time restoration
# ---------------------------------------------------------------------------

class StreamingParser:
    """
    State machine that restores pseudo-values to real values during streaming.
    
    Guarantees (per D2):
    1. Partial pseudo-values split across chunks are fully restored before output.
    2. No leakage or truncation of pseudo-values in output stream.
    3. flush() must always be called at stream end to emit remaining buffer.
    
    Algorithm:
    - Buffer accumulation retains max_pseudo_length trailing characters.
    - Known pseudo-values are replaced only when a complete match is confirmed.
    - On flush(), any remaining buffer undergoes full restoration.
    """
    
    def __init__(self, ctx: PIIContext, session_id: str):
        self.ctx = ctx
        self.session_id = session_id
        self.buffer = ""
        # Calculate max pseudo-value length for buffer retention
        self.max_pseudo_len = max(len(p) for p in ctx.pseudo_to_real.keys()) if ctx.has_mappings() else 0
    
    def process_chunk(self, chunk: str) -> str:
        """
        Process a chunk, restoring pseudo-values to real values.
        
        Returns safe output that can be emitted immediately.
        Partial pseudo-values are held in buffer until complete match.
        """
        if not self.ctx.has_mappings():
            return chunk
        
        # Add chunk to buffer
        self.buffer += chunk
        
        # Try to find and replace pseudo-values in buffer
        for pseudo, real in self.ctx.pseudo_to_real.items():
            if pseudo in self.buffer:
                self.buffer = self.buffer.replace(pseudo, real)
                logger.info("pii_stream_restored", session_id=self.session_id, 
                           pseudo_len=len(pseudo), real_len=len(real))
        
        # If buffer is shorter than max pseudo length, don't emit yet
        # (might be start of a pseudo-value)
        if len(self.buffer) <= self.max_pseudo_len:
            return ""
        
        # Emit safe portion, keep potential partial match in buffer
        # The safe portion is everything except the last max_pseudo_len chars
        safe_end = len(self.buffer) - self.max_pseudo_len
        output = self.buffer[:safe_end]
        self.buffer = self.buffer[safe_end:]
        
        return output
    
    def flush(self) -> str:
        """
        Flush remaining buffer at stream end.
        
        Applies full restoration to any remaining content.
        MUST be called when stream completes to avoid data loss.
        """
        if not self.ctx.has_mappings():
            result = self.buffer
            self.buffer = ""
            return result
        
        # Restore any remaining pseudo-values in buffer
        for pseudo, real in self.ctx.pseudo_to_real.items():
            if pseudo in self.buffer:
                self.buffer = self.buffer.replace(pseudo, real)
                logger.info("pii_stream_flush_restored", session_id=self.session_id)
        
        result = self.buffer
        self.buffer = ""
        return result


def create_streaming_parser(ctx: PIIContext, session_id: str) -> StreamingParser:
    """Factory to create a streaming parser."""
    return StreamingParser(ctx, session_id)


