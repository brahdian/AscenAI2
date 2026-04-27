import structlog
from typing import List, Tuple
from .llm_client import LLMClient
from .schemas.chat import SourceCitation

logger = structlog.get_logger(__name__)

class GroundingService:
    """
    Provides Natural Language Inference (NLI) checks to verify that an LLM's response
    is factually grounded in the retrieved source citations.
    """
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def verify_grounding(self, response: str, sources: List[SourceCitation]) -> Tuple[bool, str]:
        """
        Verify if the given response is fully supported by the provided sources.
        Returns a tuple of (is_grounded, explanation).
        """
        if not sources:
            # If no sources were retrieved but a response was generated, we skip grounding check
            # unless the response is asserting specific facts. For now, assume it's conversational.
            return True, "No sources provided, assumed conversational."

        # Phase 8 — Gap 5: Cap input sizes to protect token budget and context limit
        safe_response = (response or "")[:2000]
        
        # Prepare and cap source text
        source_excerpts = [f"Source {i+1}: {s.excerpt}" for i, s in enumerate(sources) if s.excerpt]
        source_texts = "\n\n".join(source_excerpts)
        if len(source_texts) > 3000:
            source_texts = source_texts[:3000] + "... [TRUNCATED]"
        
        if not source_texts.strip():
            return True, "Sources had no excerpt text."

        system_prompt = (
            "You are a strict Natural Language Inference (NLI) verifier. "
            "Your task is to determine if the CLAIM is fully SUPPORTED by the SOURCES. "
            "If the CLAIM contains facts, numbers, or assertions that are NOT present in the SOURCES, "
            "you must output 'GROUNDING_FAILED'. Otherwise, output 'GROUNDING_PASSED'. "
            "Provide a brief one sentence explanation for your decision after your output."
        )

        user_prompt = f"SOURCES:\n{source_texts}\n\nCLAIM:\n{safe_response}"

        try:
            nli_response = await self.llm_client.complete(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0, # Must be deterministic
                max_tokens=100
            )
            
            content = nli_response.content or ""
            is_grounded = "GROUNDING_PASSED" in content.upper()
            
            # Simple parsing for explanation
            explanation = content.replace("GROUNDING_PASSED", "").replace("GROUNDING_FAILED", "").strip()

            if not is_grounded:
                logger.warning("grounding_check_failed", explanation=explanation)

            return is_grounded, explanation

        except Exception as exc:
            # Fail open if the verifier itself fails to not block traffic
            logger.error("grounding_verification_error", error=str(exc))
            return True, "Verification failed due to error."
