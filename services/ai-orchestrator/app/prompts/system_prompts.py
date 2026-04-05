from __future__ import annotations
import re
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.agent import Agent, AgentPlaybook
    from app.models.variable import AgentVariable

from app.guardrails.voice_agent_guardrails import build_voice_system_prompt

# ---------------------------------------------------------------------------
# Tone templates
# ---------------------------------------------------------------------------
TONE_DESCRIPTIONS = {
    "professional": "You are professional, precise, and formal. Use complete sentences and avoid slang.",
    "friendly": "You are warm, approachable, and conversational. Use a casual but polite tone.",
    "casual": "You are relaxed and informal. Keep responses short and natural.",
    "empathetic": "You are empathetic and patient. Acknowledge the customer's feelings before responding.",
}

# Mapping of ISO codes to natural language names for prompting
LANG_NAMES = {
    "en": "English",
    "en-US": "English",
    "en-GB": "English",
    "en-CA": "English",
    "fr": "French",
    "fr-CA": "French",
    "es": "Spanish",
    "es-MX": "Spanish",
    "es-ES": "Spanish",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "pt-BR": "Portuguese",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "ru": "Russian",
    "pl": "Polish",
    "nl": "Dutch",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "hi": "Hindi",
    "ar": "Arabic",
}

def get_natural_lang(code: str) -> str:
    if not code: return "English"
    if code in LANG_NAMES: return LANG_NAMES[code]
    base = code.split("-")[0].lower()
    return LANG_NAMES.get(base, code)


def expand_playbook_references(
    text: str,
    variables: list["AgentVariable"] = None,
    session_metadata: dict = None,
    agent_tools: list[dict] = None,
    agent: "Agent" = None
) -> str:
    """
    Parse $[tools:name], $[vars:name], $[rag:id] syntax in instructions.
    Replaces them with context-aware descriptions or values.
    """
    if not text:
        return ""

    variables = variables or []
    session_metadata = session_metadata or {}
    runtime_vars = session_metadata.get("variables", {})
    agent_tools = agent_tools or []

    # 1. Expand variables: $[vars:name] or $vars:name
    def var_sub(match):
        name = match.group(1) or match.group(2)
        val = runtime_vars.get(name)
        if val is None:
            v_obj = next((v for v in variables if v.name == name), None)
            if v_obj and isinstance(v_obj.default_value, dict):
                val = v_obj.default_value.get("value")
        
        if val is not None:
            return f"{val} (variable: {name})"
        return f"[unknown variable: {name}]"

    text = re.sub(r'\$\[vars:(\w+)\]|\$vars:(\w+)', var_sub, text)

    # 2. Expand tools: $[tools:name] or $tools:name
    def tool_sub(match):
        name = match.group(1) or match.group(2)
        found = any(t.get("name") == name if isinstance(t, dict) else t.name == name for t in agent_tools)
        if found:
            return f"the `{name}` tool"
        return f"[unregistered tool: {name}]"

    text = re.sub(r'\$\[tools:(\w+)\]|\$tools:(\w+)', tool_sub, text)

    # 3. Expand RAG: $[rag:name] or $rag:name
    def rag_sub(match):
        name = match.group(1) or match.group(2)
        return f"the '{name}' knowledge base"

    text = re.sub(r'\$\[rag:(\w+)\]|\$rag:(\w+)', rag_sub, text)
    return text


def build_system_prompt(
    agent: "Agent",
    context_items: list = None,
    business_info: dict = None,
    playbook: Optional["AgentPlaybook"] = None,
    corrections: list[dict] = None,
    guardrails=None,
    variables: list["AgentVariable"] = None,
    session_metadata: dict = None,
) -> str:
    """
    Assemble the full system prompt for an agent turn.
    """
    context_items = context_items or []
    business_info = business_info or {}
    corrections = corrections or []
    variables = variables or []
    session_metadata = session_metadata or {}

    agent_tools = agent.tools or []
    parts: list[str] = []

    agent_name = agent.name or "Assistant"
    business_type = (agent.business_type or "general").replace("_", " ").title()

    agent_metadata = agent.metadata_ if hasattr(agent, "metadata_") else {}
    is_voice = (
        getattr(agent, "channel", None) == "voice"
        or (isinstance(agent_metadata, dict) and agent_metadata.get("channel") == "voice")
    )

    if is_voice:
        tone_key = "friendly"
        if playbook:
            tone_key = (playbook.tone or "friendly").lower()
        tone_desc = TONE_DESCRIPTIONS.get(tone_key, TONE_DESCRIPTIONS["friendly"])

        allowed_topics = business_type + " services"
        if guardrails and guardrails.allowed_topics:
            allowed_topics = ", ".join(guardrails.allowed_topics)

        out_of_scope = "I can only help with topics related to our service."
        if playbook and playbook.out_of_scope_response:
            out_of_scope = playbook.out_of_scope_response

        parts.append(build_voice_system_prompt(
            agent_name=agent_name,
            business_name=business_type,
            allowed_topics=allowed_topics,
            out_of_scope_response=out_of_scope,
            tone_description=tone_desc,
            voice_protocol=getattr(agent, "voice_system_prompt", "") or "",
            supported_languages=getattr(agent, "supported_languages", None) or [],
        ))
    else:
        parts.append(f"You are {agent_name}, an AI assistant for a {business_type} business.")

    if agent.personality:
        parts.append(f"\nPersonality: {agent.personality}")

    if agent.system_prompt:
        expanded_prompt = expand_playbook_references(
            agent.system_prompt, variables, session_metadata, agent_tools, agent
        )
        parts.append(f"\n{expanded_prompt}")

    session_lang = business_info.get("session_language")
    auto_detect = getattr(agent, "auto_detect_language", False)
    
    if auto_detect and session_lang:
        lang_str = get_natural_lang(session_lang)
    else:
        lang_str = get_natural_lang(agent.language or "en")

    if auto_detect:
        supported_langs = getattr(agent, "supported_languages", None) or []
        supported_names = [get_natural_lang(l) for l in supported_langs]
        if not supported_names:
            supported_names = [lang_str]
        
        langs_joined = ", ".join(list(dict.fromkeys(supported_names)))
        lang_instruction = (
            f"\n## Language Protocol\n"
            f"- You are configured to support: {langs_joined}.\n"
            f"- The current session language is detected as: {lang_str}.\n"
            f"- If the user speaks any of the supported languages ({langs_joined}), you MUST pivot and respond in that language immediately.\n"
            f"- If the user speaks a language NOT in this list, politely inform them you only support {langs_joined}."
        )
    else:
        lang_instruction = f"\nAlways respond in language: {lang_str}."
    
    parts.append(lang_instruction)

    if playbook:
        tone_key = (playbook.tone or "professional").lower()
        tone_desc = TONE_DESCRIPTIONS.get(tone_key, TONE_DESCRIPTIONS["professional"])
        parts.append(f"\n## Tone & Style\n{tone_desc}")

        if playbook.instructions:
            expanded_instructions = expand_playbook_references(
                playbook.instructions, variables, session_metadata, agent_tools, agent
            )
            parts.append(f"\n## Operator Instructions\n{expanded_instructions}")

        dos = playbook.dos or []
        donts = playbook.donts or []
        if dos or donts:
            parts.append("\n## Rules")
            if dos:
                expanded_dos = [expand_playbook_references(d, variables, session_metadata, agent_tools, agent) for d in dos]
                parts.append("Always:\n" + "\n".join(f"- {d}" for d in expanded_dos))
            if donts:
                expanded_donts = [expand_playbook_references(d, variables, session_metadata, agent_tools, agent) for d in donts]
                parts.append("Never:\n" + "\n".join(f"- {d}" for d in expanded_donts))

        scenarios = playbook.scenarios or []
        if scenarios:
            parts.append("\n## Scenario Playbook")
            for s in scenarios:
                trigger = s.get("trigger", "")
                response = s.get("response", "")
                if trigger and response:
                    exp_response = expand_playbook_references(response, variables, session_metadata, agent_tools, agent)
                    parts.append(f'If the user asks about "{trigger}":\n→ {exp_response}')

        if playbook.out_of_scope_response:
            parts.append(f"\n## Out-of-scope\nIf asked something outside your scope, say:\n\"{playbook.out_of_scope_response}\"")

        if playbook.fallback_response:
            parts.append(f"\n## Fallback\nIf you don't know the answer, say:\n\"{playbook.fallback_response}\"")

    knowledge_items = [c for c in context_items if getattr(c, "type", None) == "knowledge"]
    if knowledge_items:
        parts.append("\n## Knowledge Base Context")
        for item in knowledge_items[:5]:
            content = getattr(item, "content", "")
            if content: parts.append(f"- {content[:500]}")

    history_items = [c for c in context_items if getattr(c, "type", None) == "history"]
    if history_items:
        parts.append("\n## Relevant Past Interactions")
        for item in history_items[:3]:
            content = getattr(item, "content", "")
            if content: parts.append(f"- {content[:300]}")

    parts.append("\n## Data Source Priority")
    parts.append("You MUST use available data sources in this order:")
    parts.append("1. First, use the PLAYBOOK instructions above if one is matched")
    parts.append("2. Second, use the KNOWLEDGE BASE CONTEXT if provided")
    parts.append("3. Third, use any TOOLS available to you to fetch information")
    parts.append("If none of these sources can answer the question, respond with: \"I don't have enough information to answer that. Could you rephrase or provide more details?\"")

    if corrections:
        parts.append("\n## Corrections from Previous Reviews")
        for c in corrections[-10:]:
            user_msg = c.get("user_message", "")
            ideal = c.get("ideal_response", "")
            if user_msg and ideal:
                parts.append(f'When asked: "{user_msg[:200]}" -> Correct answer: "{ideal[:400]}"')

    customer_profile = business_info.get("customer_profile", {})
    if customer_profile:
        name = customer_profile.get("name", "")
        if name: parts.append(f"\n## Customer\nYou are speaking with {name}.")

    if variables:
        parts.append("\n## Context Variables (State)")
        runtime_vars = session_metadata.get("variables", {})
        for v in variables:
            val = runtime_vars.get(v.name)
            if val is None and isinstance(v.default_value, dict):
                val = v.default_value.get("value")
            val_str = f'"{val}"' if isinstance(val, str) else str(val) if val is not None else "null"
            parts.append(f"- {v.name} ({v.data_type}): {val_str}")

    return "\n".join(parts)
