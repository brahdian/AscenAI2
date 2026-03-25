"""
Build the dynamic system prompt injected at the start of every LLM call.

Layers (in order):
1. Base persona (name, personality, business type)
2. Playbook instructions, tone, dos/don'ts, scenarios
3. Retrieved knowledge-base / history context items
4. Operator corrections from past reviews
5. Customer profile (if present)
"""
from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.agent import Agent, AgentPlaybook


# ---------------------------------------------------------------------------
# Tone templates
# ---------------------------------------------------------------------------
TONE_DESCRIPTIONS = {
    "professional": "You are professional, precise, and formal. Use complete sentences and avoid slang.",
    "friendly": "You are warm, approachable, and conversational. Use a casual but polite tone.",
    "casual": "You are relaxed and informal. Keep responses short and natural.",
    "empathetic": "You are empathetic and patient. Acknowledge the customer's feelings before responding.",
}


def build_system_prompt(
    agent: "Agent",
    context_items: list = None,
    business_info: dict = None,
    playbook: Optional["AgentPlaybook"] = None,
    corrections: list[dict] = None,
    guardrails=None,
) -> str:
    """
    Assemble the full system prompt for an agent turn.

    Args:
        agent:        ORM Agent instance
        context_items: List of ContextItem dicts from MCP
        business_info: Dict with customer_profile, intent, etc.
        playbook:     Optional AgentPlaybook ORM instance
        corrections:  List of {user_message, ideal_response} dicts from Redis
    """
    context_items = context_items or []
    business_info = business_info or {}
    corrections = corrections or []

    parts: list[str] = []

    # ------------------------------------------------------------------ #
    # 1. Base persona
    # ------------------------------------------------------------------ #
    agent_name = agent.name or "Assistant"
    business_type = (agent.business_type or "general").replace("_", " ").title()

    parts.append(f"You are {agent_name}, an AI assistant for a {business_type} business.")

    if agent.personality:
        parts.append(f"\nPersonality: {agent.personality}")

    if agent.system_prompt:
        parts.append(f"\n{agent.system_prompt}")

    parts.append(f"\nAlways respond in language: {agent.language or 'en'}.")

    # ------------------------------------------------------------------ #
    # 2. Playbook instructions
    # ------------------------------------------------------------------ #
    if playbook:
        tone_key = (playbook.tone or "professional").lower()
        tone_desc = TONE_DESCRIPTIONS.get(tone_key, TONE_DESCRIPTIONS["professional"])
        parts.append(f"\n## Tone & Style\n{tone_desc}")

        if playbook.instructions:
            parts.append(f"\n## Operator Instructions\n{playbook.instructions}")

        dos = playbook.dos or []
        donts = playbook.donts or []
        if dos or donts:
            parts.append("\n## Rules")
            if dos:
                parts.append("Always:\n" + "\n".join(f"- {d}" for d in dos))
            if donts:
                parts.append("Never:\n" + "\n".join(f"- {d}" for d in donts))

        scenarios = playbook.scenarios or []
        if scenarios:
            parts.append("\n## Scenario Playbook")
            for s in scenarios:
                trigger = s.get("trigger", "")
                response = s.get("response", "")
                if trigger and response:
                    parts.append(f'If the user asks about "{trigger}":\n→ {response}')

        if playbook.out_of_scope_response:
            parts.append(
                f"\n## Out-of-scope\nIf asked something outside your scope, say:\n"
                f'"{playbook.out_of_scope_response}"'
            )

        if playbook.fallback_response:
            parts.append(
                f"\n## Fallback\nIf you don't know the answer, say:\n"
                f'"{playbook.fallback_response}"'
            )

    # ------------------------------------------------------------------ #
    # 2b. Guardrails — content policy injected into prompt
    # ------------------------------------------------------------------ #
    if guardrails and guardrails.is_active:
        gr_parts: list[str] = []

        if guardrails.allowed_topics:
            topics_str = ", ".join(guardrails.allowed_topics)
            off_msg = guardrails.off_topic_message or "I can only help with topics related to our service."
            gr_parts.append(
                f"You are ONLY permitted to discuss these topics: {topics_str}. "
                f'For anything outside this list, respond with: "{off_msg}"'
            )
        elif guardrails.blocked_topics:
            topics_str = ", ".join(guardrails.blocked_topics)
            off_msg = guardrails.off_topic_message or "I cannot help with that topic."
            gr_parts.append(
                f"You must REFUSE to discuss the following topics: {topics_str}. "
                f'If asked, say: "{off_msg}"'
            )

        if guardrails.require_disclaimer:
            gr_parts.append(
                f'Always end your response with this disclaimer: "{guardrails.require_disclaimer}"'
            )

        if gr_parts:
            parts.append("\n## Content Policy\n" + "\n".join(gr_parts))

    # ------------------------------------------------------------------ #
    # 3. Retrieved context
    # ------------------------------------------------------------------ #
    knowledge_items = [c for c in context_items if getattr(c, "type", None) == "knowledge"]
    if knowledge_items:
        parts.append("\n## Knowledge Base Context")
        for item in knowledge_items[:5]:
            content = getattr(item, "content", "")
            if content:
                parts.append(f"- {content[:500]}")

    history_items = [c for c in context_items if getattr(c, "type", None) == "history"]
    if history_items:
        parts.append("\n## Relevant Past Interactions")
        for item in history_items[:3]:
            content = getattr(item, "content", "")
            if content:
                parts.append(f"- {content[:300]}")

    # ------------------------------------------------------------------ #
    # 4. Operator corrections (few-shot examples from reviewed chats)
    # ------------------------------------------------------------------ #
    if corrections:
        parts.append("\n## Corrections from Previous Reviews")
        parts.append(
            "These are examples of how you SHOULD have responded in past conversations. "
            "Use them as guidance:"
        )
        for c in corrections[-10:]:  # max 10 most recent
            user_msg = c.get("user_message", "")
            ideal = c.get("ideal_response", "")
            if user_msg and ideal:
                parts.append(f'When asked: "{user_msg[:200]}"\nIdeal answer: "{ideal[:400]}"')

    # ------------------------------------------------------------------ #
    # 5. Customer profile
    # ------------------------------------------------------------------ #
    customer_profile = business_info.get("customer_profile", {})
    if customer_profile:
        name = customer_profile.get("name", "")
        prefs = customer_profile.get("preferences", {})
        if name:
            parts.append(f"\n## Customer\nYou are speaking with {name}.")
        if prefs:
            parts.append(f"Known preferences: {prefs}")

    return "\n".join(parts)
