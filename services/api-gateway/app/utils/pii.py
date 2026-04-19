import re
import uuid
from typing import Any, Dict, List, Union

# Robust regex-based patterns for common PII
# These are used as a first-line defense in the Gateway before storage.
# The AI-Orchestrator uses more advanced NLP (Microsoft Presidio) for chat processing.
PII_PATTERNS = {
    "EMAIL": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
    "PHONE": r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
    "CREDIT_CARD": r"\b(?:\d[ -]*?){13,16}\b",
    "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
    "IPV4": r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
}

# Keys that are explicitly allowed even if they contain potentially sensitive terms
ALLOWED_TECHNICAL_KEYS = {
    "id", "trace_id", "request_id", "turn_id", "session_id", "agent_id", 
    "tenant_id", "user_id", "execution_id", "message_id"
}

SENSITIVE_KEYS = {
    "password", "hashed_password", "token", "access_token", "refresh_token",
    "secret", "client_secret", "key", "api_key", "internal_key",
    "authorization", "cookie", "cvv", "card_number", "ssn", "phi", "pii"
}

# Values matching these patterns will be redacted regardless of the key name
# Focused on high-entropy standard secret formats (Stripe, GitHub, etc)
SECRET_PATTERNS = [
    r"sk_(live|test)_[a-zA-Z0-9]{24,}",      
    r"pk_(live|test)_[a-zA-Z0-9]{24,}",      
    r"bearer\s+[a-zA-Z0-9\-\._~+/]{32,}", 
    r"ghp_[a-zA-Z0-9]{20,}",          
    r"shk_[a-zA-Z0-9]{20,}",
    r"auth0\|[a-zA-Z0-9]{24,}",
    r"ey[a-zA-Z0-9_-]{10,}\.ey[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}", # JWT
]

_RE_SECRETS = re.compile("|".join(SECRET_PATTERNS), re.IGNORECASE)

def mask_technical_id(id_val: Union[str, uuid.UUID]) -> str:
    """Partial masking for technical IDs: trc_...1234. (Zenith Pillar 2)"""
    s = str(id_val)
    if len(s) <= 8:
        return "****"
    prefix = s[:4]
    suffix = s[-4:]
    return f"{prefix}...{suffix}"

def redact_text(text: str) -> str:
    """Redact common PII patterns from a string."""
    if not text:
        return text
    
    redacted = text
    # 1. Check for specific high-entropy secrets first (Zenith Pillar 2)
    if _RE_SECRETS.search(redacted):
        return "[REDACTED SECRET]"

    # 2. Specialized Anonymization for structured strings
    # We use the specialized functions instead of generic [LABEL] for better forensic context
    if re.match(PII_PATTERNS["EMAIL"], redacted):
        return anonymize_email(redacted)
    if re.match(PII_PATTERNS["IPV4"], redacted):
        return anonymize_ip(redacted)

    # 3. Fallback pattern-based PII redaction for embedded text
    for label, pattern in PII_PATTERNS.items():
        if label in ("EMAIL", "IPV4"): continue # Handled above for full strings
        redacted = re.sub(pattern, f"[{label}]", redacted)
    return redacted

def mask_pii(data: Any, deep: bool = True) -> Any:
    """
    ZENITH PILLAR 2: Recursive deep masking utility.
    - Masks Technical IDs partially.
    - Fully redacts secrets, tokens, and credentials.
    - Recursive traversal of dicts and lists.
    """
    if data is None:
        return None
        
    if isinstance(data, (uuid.UUID, str)):
        s = str(data)
        # Check if it's a known secret pattern first
        if _RE_SECRETS.search(s):
            return "[REDACTED SECRET]"
        # Check standard PII
        return redact_text(s)
        
    if isinstance(data, dict):
        new_dict = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if k_lower in SENSITIVE_KEYS:
                new_dict[k] = "[REDACTED]"
            elif k_lower in ALLOWED_TECHNICAL_KEYS:
                new_dict[k] = mask_technical_id(v) if deep else v
            else:
                new_dict[k] = mask_pii(v, deep=deep)
        return new_dict
        
    if isinstance(data, list):
        return [mask_pii(item, deep=deep) for item in data]
        
    return data

# Legacy alias for backward compatibility
mask_sensitive_data = mask_pii

def anonymize_email(email: str) -> str:
    """Standardize email masking: u***@example.com"""
    if not email or "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) > 1:
        return f"{local[0]}***@{domain}"
    return f"*@{domain}"

def anonymize_ip(ip: str) -> str:
    """Mask the last octet of an IP address for GDPR-compliant display."""
    if not ip or ip == "unknown":
        return ip
    if ":" in ip:
        # IPv6: Mask the last segment
        parts = ip.split(":")
        if len(parts) > 1:
            parts[-1] = "xxxx"
            return ":".join(parts)
        return ip
    # IPv4: Mask the last octet
    parts = ip.split(".")
    if len(parts) == 4:
        parts[-1] = "xxx"
        return ".".join(parts)
    return ip
