import re
from typing import Optional, Tuple
import structlog

from app.models.agent import Agent
from app.services import pii_service
from app.services.pii_service import PIIContext

logger = structlog.get_logger(__name__)

_PROFANITY_LIST = frozenset([
    "fuck", "shit", "bitch", "asshole", "cunt", "bastard",
])

_EMERGENCY_KEYWORDS = frozenset([
    "911", "emergency", "chest pain", "can't breathe", "cannot breathe",
    "heart attack", "stroke", "overdose", "suicidal", "suicide", "seizure",
    "unconscious", "not breathing", "choking", "severe bleeding", "anaphylaxis",
    "allergic reaction", "call ambulance", "dying", "help me please",
])
_EMERGENCY_BUSINESS_TYPES = frozenset([
    "clinic", "medical", "healthcare", "dental", "pharmacy", "hospital",
    "health", "therapy", "mental_health",
])
_EMERGENCY_RESPONSE = (
    "This sounds like a medical emergency. Please call 911 immediately "
    "or go to your nearest emergency room. Do not wait for online assistance. "
    "If someone is in immediate danger, call emergency services now."
)

_ROLE_INJECTION_PATTERN = re.compile(
    r"(\[SYSTEM\]|\[INST\]|<system>|<\/system>|\[\/INST\]"
    r"|<<SYS>>|<</SYS>>|\[ASSISTANT\]|\[USER\])",
    re.IGNORECASE,
)

_JAILBREAK_PATTERN = re.compile(
    r"(ignore (all |your )?(previous |prior )?instructions?"
    r"|you are now (in )?(developer|jailbreak|dan|unrestricted|god) mode"
    r"|pretend (you are|you're|to be) (an? )?(evil|unrestricted|uncensored|unfiltered)"
    r"|act as if you (have no|without) (rules|restrictions|guidelines)"
    r"|disregard (your|all) (training|guidelines|rules|instructions)"
    r"|bypass (your|all) (safety|content|ethical) (filters?|guidelines?)"
    r"|you (have|has) no (restrictions|limits|rules|guidelines)"
    r"|enter (jailbreak|developer|unrestricted) mode)",
    re.IGNORECASE,
)

_PROFESSIONAL_CLAIM_PHRASES = [
    "as your doctor", "as a doctor", "i diagnose", "my diagnosis is",
    "you should take this medication", "i prescribe", "this is legal advice",
    "as your lawyer", "as a legal expert", "as your financial advisor",
    "i guarantee your investment",
]
_PROFESSIONAL_DISCLAIMER = (
    " Note: I am an AI assistant, not a licensed professional. "
    "Please consult a qualified professional for medical, legal, or financial guidance."
)

_CREDENTIAL_SCRUB_PATTERN = re.compile(
    r"(Bearer\s+[A-Za-z0-9\-._~+/]+=*"
    r"|sk-[A-Za-z0-9]{20,}"
    r"|AIza[A-Za-z0-9\-_]{35}"
    r"|(?:key|token|secret|password)[_\-]?[A-Za-z0-9]{16,})",
    re.IGNORECASE,
)

class GuardrailService:
    def __init__(self, redis_client=None):
        self.redis = redis_client

    async def get_pii_context(self, session_id: str) -> PIIContext:
        """Always load PII context to ensure PII pseudonymization applies."""
        return await pii_service.load_context(session_id, self.redis)

    async def save_pii_context(self, session_id: str, pii_ctx: PIIContext):
        """Save updated PII context."""
        await pii_service.save_context(session_id, pii_ctx, self.redis)

    def redact_user_message(self, user_message: str, pii_ctx: PIIContext, session_id: str) -> str:
        """Always redact PII on the user message."""
        return pii_service.redact_pii(user_message, pii_ctx, session_id)

    def check_input_guardrails(self, user_message: str, guardrails) -> Optional[str]:
        """Return a block reason string if message should be blocked, else None."""
        if not guardrails:
            return None
        msg_lower = user_message.lower()

        for kw in (guardrails.blocked_keywords or []):
            if kw.lower() in msg_lower:
                return f"blocked_keyword:{kw}"

        if guardrails.profanity_filter:
            for word in _PROFANITY_LIST:
                if word in msg_lower:
                    return "profanity"

        return None

    def apply_output_guardrails(
        self,
        response: str,
        guardrails,
        pii_ctx: Optional[PIIContext] = None,
        session_id: str = "unknown",
    ) -> Tuple[str, list[str]]:
        actions: list[str] = []
        
        # Step 1: Restore any remaining PII tokens in the response always if context exists
        if pii_ctx is not None:
            parser = pii_service.create_streaming_parser(pii_ctx, session_id)
            restored = parser.process_chunk(response) + parser.flush()
            if restored != response:
                response = restored
                actions.append("pii_pseudonymization_restored")

        if not guardrails:
            return response, actions

        if guardrails.max_response_length and len(response) > guardrails.max_response_length:
            response = response[:guardrails.max_response_length].rstrip() + "…"
            actions.append("length_cap")

        if guardrails.pii_redaction:
            redacted = pii_service.redact(response)
            if redacted != response:
                response = redacted
                actions.append("pii_redacted")

        if guardrails.require_disclaimer:
            response = response + "\n\n" + guardrails.require_disclaimer
            actions.append("disclaimer_appended")

        return response, actions
        
    def check_emergency(self, user_message: str, agent: Agent) -> Optional[str]:
        business_type = (agent.business_type or "").lower().replace(" ", "_")
        if business_type not in _EMERGENCY_BUSINESS_TYPES:
            return None
        msg_lower = user_message.lower()
        for kw in _EMERGENCY_KEYWORDS:
            if kw in msg_lower:
                logger.warning(
                    "emergency_keyword_detected",
                    keyword=kw,
                    agent_id=str(agent.id),
                    business_type=business_type,
                )
                return _EMERGENCY_RESPONSE
        return None

    @staticmethod
    def sanitize_user_message(text: str) -> str:
        sanitized = _ROLE_INJECTION_PATTERN.sub("", text).strip()
        if sanitized != text:
            logger.warning("role_injection_stripped", original_len=len(text))
        return sanitized

    def check_jailbreak(self, user_message: str, agent: Agent) -> Optional[str]:
        if _JAILBREAK_PATTERN.search(user_message):
            business_type = (agent.business_type or "our business").replace("_", " ").title()
            logger.warning(
                "jailbreak_attempt_detected",
                agent_id=str(agent.id),
                snippet=user_message[:80],
            )
            return (
                f"I'm only here to help with {business_type} services. "
                "How can I assist you today?"
            )
        return None

    @staticmethod
    def check_professional_claims(response: str) -> str:
        res_lower = response.lower()
        for claim in _PROFESSIONAL_CLAIM_PHRASES:
            if claim in res_lower:
                if _PROFESSIONAL_DISCLAIMER.strip() not in response:
                    return response + _PROFESSIONAL_DISCLAIMER
                break
        return response

    @staticmethod
    def scrub_credentials(text: str) -> str:
        return _CREDENTIAL_SCRUB_PATTERN.sub("[REDACTED_CREDENTIAL]", text)

    _TOOL_OUTPUT_INJECTION_PATTERN = re.compile(
        r"(\[SYSTEM\]|\[INST\]|<system>|<\/system>|\[\/INST\]"
        r"|<<SYS>>|<</SYS>>|\[ASSISTANT\]|\[USER\]"
        r"|ignore (previous|all|above)|disregard instructions"
        r"|you are now|pretend to be|override|jailbreak"
        r"|<script|javascript:|base64|IMPORTANT:|CRITICAL:)"
        r"|ALERT:|WARNING:|NOTE:|SYSTEM MESSAGE:|NEW INSTRUCTIONS:",
        re.IGNORECASE,
    )

    @staticmethod
    def sanitize_tool_output(text: str) -> str:
        sanitized = GuardrailService._TOOL_OUTPUT_INJECTION_PATTERN.sub("[FILTERED]", text)
        if len(sanitized) > 4000:
            sanitized = sanitized[:4000] + "...[truncated]"
        if sanitized != text:
            logger.warning("tool_output_sanitized", original_len=len(text), sanitized_len=len(sanitized))
        return sanitized

    _TOOL_OUTPUT_INJECTION_PATTERN = re.compile(
        r"(\[SYSTEM\]|\[INST\]|<system>|<\/system>|\[\/INST\]"
        r"|<<SYS>>|<</SYS>>|\[ASSISTANT\]|\[USER\]"
        r"|ignore (previous|all|above)|disregard instructions"
        r"|you are now|pretend to be|override|jailbreak"
        r"|<script|javascript:|base64|IMPORTANT:|CRITICAL:)"
        r"|ALERT:|WARNING:|NOTE:|SYSTEM MESSAGE:|NEW INSTRUCTIONS:",
        re.IGNORECASE,
    )

    @staticmethod
    def sanitize_tool_output(text: str) -> str:
        sanitized = GuardrailService._TOOL_OUTPUT_INJECTION_PATTERN.sub("[FILTERED]", text)
        if len(sanitized) > 4000:
            sanitized = sanitized[:4000] + "...[truncated]"
        if sanitized != text:
            logger.warning("tool_output_sanitized", original_len=len(text), sanitized_len=len(sanitized))
        return sanitized
