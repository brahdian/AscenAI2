import re
from typing import Optional, Tuple
import structlog

from app.models.agent import Agent, GuardrailEvent
from app.services import pii_service
from app.services.pii_service import PIIContext
from sqlalchemy.ext.asyncio import AsyncSession

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
    def __init__(self, redis_client=None, db: Optional[AsyncSession] = None):
        self.redis = redis_client
        self.db = db

    async def record_event(
        self, agent: Agent, session_id: str, event_type: str, details: dict,
        request_id: Optional[str] = None, tokens: int = 0, latency_ms: int = 0
    ):
        """Record a security event to the database with forensic telemetry."""
        if not self.db:
            logger.debug("guardrail_event_skipped_no_db", event_type=event_type, agent_id=str(agent.id))
            return
            
        try:
            # Enrich details with telemetry
            event_details = dict(details)
            if request_id:
                event_details["request_id"] = request_id
            if tokens:
                event_details["tokens"] = tokens
            if latency_ms:
                event_details["latency_ms"] = latency_ms

            event = GuardrailEvent(
                tenant_id=agent.tenant_id,
                agent_id=agent.id,
                session_id=session_id,
                event_type=event_type,
                details=event_details
            )
            self.db.add(event)
            await self.db.commit()
            logger.info("guardrail_event_recorded", event_type=event_type, agent_id=str(agent.id), session_id=session_id, request_id=request_id)
        except Exception as e:
            logger.error("failed_to_record_guardrail_event", error=str(e), event_type=event_type)

    async def get_pii_context(self, session_id: str, tenant_id: str = "") -> PIIContext:
        """Always load PII context to ensure PII pseudonymization applies."""
        return await pii_service.load_context(session_id, self.redis, tenant_id=tenant_id)

    async def save_pii_context(self, session_id: str, pii_ctx: PIIContext):
        """Save updated PII context."""
        await pii_service.save_context(session_id, pii_ctx, self.redis)

    def redact_user_message(self, user_message: str, pii_ctx: PIIContext, session_id: str, hipaa_mode: bool = False) -> str:
        """Always redact PII on the user message."""
        return pii_service.redact_pii(user_message, pii_ctx, session_id, hipaa_mode=hipaa_mode)

    async def check_input_guardrails(
        self, user_message: str, agent: Agent, session_id: str, 
        guardrails: Optional[dict], platform_guardrails: Optional[dict] = None,
        request_id: Optional[str] = None
    ) -> Optional[str]:
        """Return a block reason string if message should be blocked, else None."""
        msg_lower = user_message.lower()

        # Check Agent-specific guardrails
        if guardrails and guardrails.get("is_active", True):
            for kw in (guardrails.get("blocked_keywords", [])):
                if kw.lower() in msg_lower:
                    await self.record_event(agent, session_id, "input_blocked_keyword", {"keyword": kw, "snippet": user_message[:100]}, request_id=request_id)
                    return f"agent_blocked_keyword:{kw}"

            # Extended agent topics
            for topic in (guardrails.get("blocked_topics", [])):
                if topic.lower() in msg_lower:
                    await self.record_event(agent, session_id, "input_blocked_topic", {"topic": topic, "snippet": user_message[:100]}, request_id=request_id)
                    return f"agent_blocked_topic:{topic}"

            if guardrails.get("profanity_filter", True):
                for word in _PROFANITY_LIST:
                    if word in msg_lower:
                        await self.record_event(agent, session_id, "input_profanity_block", {"word_detected": True, "snippet": user_message[:100]}, request_id=request_id)
                        return "agent_profanity_block"

        # Check Platform-level guardrails
        if platform_guardrails:
            for kw in platform_guardrails.get("blocked_keywords", []):
                if kw.lower() in msg_lower:
                    await self.record_event(agent, session_id, "platform_input_blocked_keyword", {"keyword": kw}, request_id=request_id)
                    return f"platform_blocked_keyword:{kw}"
            
            for topic in platform_guardrails.get("blocked_topics", []):
                if topic.lower() in msg_lower:
                    await self.record_event(agent, session_id, "platform_input_blocked_topic", {"topic": topic}, request_id=request_id)
                    return f"platform_blocked_topic:{topic}"

        return None

    async def apply_output_guardrails(
        self, text: str, agent: Agent, guardrails: Optional[dict],
        platform_guardrails: Optional[dict], pii_ctx: PIIContext,
        session_id: str, hipaa_mode: bool = False,
        request_id: Optional[str] = None
    ) -> tuple[str, list[dict]]:
        """Apply output sanitization, PII restoration, and record triggers."""
        actions_taken: list[dict] = []
        response = text

        # Step 1: Always restore PII pseudo-values back to real values in the output
        if pii_ctx is not None and pii_ctx.has_mappings():
            response = pii_service.restore_pii(response, pii_ctx, session_id)

        # Step 2: Agent-level output guardrails
        if guardrails and guardrails.get("is_active", True):
            for kw in (guardrails.get("blocked_keywords") or []):
                if kw.lower() in response.lower():
                    response = response.replace(kw, "[REDACTED]")
                    actions_taken.append({"type": "blocked_keyword_redacted", "keyword": kw})
                    await self.record_event(
                        agent, session_id, "output_keyword_redacted",
                        {"keyword": kw}, request_id=request_id
                    )
            for topic in (guardrails.get("blocked_topics") or []):
                if topic.lower() in response.lower():
                    await self.record_event(
                        agent, session_id, "output_leak_prevented_topic",
                        {"topic": topic}, request_id=request_id
                    )
                    return "I cannot provide information on that topic.", [{"type": "output_blocked_topic"}]

            max_len = guardrails.get("max_response_length")
            if max_len and len(response) > max_len:
                response = response[:max_len].rstrip() + "…"
                actions_taken.append({"type": "length_cap"})



            disclaimer = guardrails.get("require_disclaimer")
            if disclaimer:
                response = response + "\n\n" + disclaimer
                actions_taken.append({"type": "disclaimer_appended"})

        # Step 3: Platform-level output guardrails
        if platform_guardrails:
            for kw in (platform_guardrails.get("blocked_keywords") or []):
                if kw.lower() in response.lower():
                    await self.record_event(
                        agent, session_id, "platform_output_leak_prevented",
                        {"keyword": kw}, request_id=request_id
                    )
                    return "I am unable to assist with this request.", [{"type": "platform_output_blocked"}]

        return response, actions_taken
        
    async def check_emergency(self, user_message: str, agent: Agent, session_id: str, request_id: Optional[str] = None) -> Optional[str]:
        business_type = (agent.business_type or "").lower().replace(" ", "_")
        if business_type not in _EMERGENCY_BUSINESS_TYPES:
            return None
        msg_lower = user_message.lower()
        for kw in _EMERGENCY_KEYWORDS:
            if kw in msg_lower:
                await self.record_event(agent, session_id, "emergency_keyword_detected", {"keyword": kw, "business_type": business_type}, request_id=request_id)
                logger.warning(
                    "emergency_keyword_detected",
                    keyword=kw,
                    agent_id=str(agent.id),
                    business_type=business_type,
                    request_id=request_id
                )
                return _EMERGENCY_RESPONSE
        return None

    @staticmethod
    def sanitize_user_message(text: str) -> str:
        sanitized = _ROLE_INJECTION_PATTERN.sub("", text).strip()
        if sanitized != text:
            logger.warning("role_injection_stripped", original_len=len(text))
        return sanitized

    async def check_jailbreak(self, user_message: str, agent: Agent, session_id: str, request_id: Optional[str] = None) -> Optional[str]:
        if _JAILBREAK_PATTERN.search(user_message):
            business_type = (agent.business_type or "our business").replace("_", " ").title()
            await self.record_event(agent, session_id, "jailbreak_attempt_detected", {"snippet": user_message[:100]}, request_id=request_id)
            logger.warning(
                "jailbreak_attempt_detected",
                agent_id=str(agent.id),
                snippet=user_message[:80],
                request_id=request_id
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
        r"|ignore\s+(previous|all|above)|disregard\s+instructions"
        r"|you\s+are\s+now|pretend\s+to\s+be|override|jailbreak"
        r"|<script|javascript:|base64|IMPORTANT:|CRITICAL:)"
        r"|ALERT:|WARNING:|NOTE:|SYSTEM\s+MESSAGE:|NEW\s+INSTRUCTIONS:",
        re.IGNORECASE,
    )

    _KNOWLEDGE_HIJACK_PATTERN = re.compile(
        r"(ignore\s+(all\s+)?(your\s+)?(previous\s+|prior\s+)?instructions?"
        r"|disregard\s+(your|all)\s+(guidelines|rules|instructions)"
        r"|you\s+are\s+now|pretend\s+to\s+be|override|jailbreak|system\s+update"
        r"|IMPORTANT:|CRITICAL:|SYSTEM\s+MESSAGE:|NEW\s+INSTRUCTIONS:)"
        r"|\[SYSTEM\]|\[INST\]|<system>|<</system>|\[\/INST\]",
        re.IGNORECASE,
    )

    @staticmethod
    def sanitize_tool_output(text: str) -> str:
        sanitized = GuardrailService._TOOL_OUTPUT_INJECTION_PATTERN.sub("[FILTERED]", text)
        if len(sanitized) > 4000:
            sanitized = sanitized[:4000] + "...[truncated]"
        return sanitized

    async def sanitize_and_log_knowledge(
        self, text: str, agent: Agent, session_id: str, 
        metadata: Optional[dict] = None, request_id: Optional[str] = None
    ) -> str:
        """Sanitize a knowledge chunk and record if injection was detected (Zero Trust RAG)."""
        if not text:
            return ""
        
        if self._KNOWLEDGE_HIJACK_PATTERN.search(text):
            event_details = {"snippet": text[:200]}
            if metadata:
                # Forensic enrichment: capture source metadata
                event_details.update({
                    "document_id": metadata.get("document_id"),
                    "source_url": metadata.get("source_url"),
                    "title": metadata.get("title")
                })

            await self.record_event(
                agent, 
                session_id, 
                "poisoned_knowledge_detected", 
                event_details,
                request_id=request_id
            )
            # Neutralize hijacking by replacing malicious patterns
            sanitized = self._KNOWLEDGE_HIJACK_PATTERN.sub("[FILTERED_INSTRUCTION]", text)
            logger.warning("poisoned_knowledge_sanitized", agent_id=str(agent.id), session_id=session_id, request_id=request_id)
            return sanitized
            
        return text
