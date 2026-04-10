from __future__ import annotations
import re
import html
from typing import Any, Optional, TYPE_CHECKING
import structlog

if TYPE_CHECKING:
    from app.models.agent import Agent, AgentPlaybook
    from app.models.variable import AgentVariable

from app.guardrails.voice_agent_guardrails import build_voice_system_prompt

logger = structlog.get_logger(__name__)

TONE_DESCRIPTIONS = {
    "professional": "You are professional, precise, and formal. Use complete sentences and avoid slang.",
    "friendly": "You are warm, approachable, and conversational. Use a casual but polite tone.",
    "casual": "You are relaxed and informal. Keep responses short and natural.",
    "empathetic": "You are empathetic and patient. Acknowledge the customer's feelings before responding.",
}

LANG_NAMES = {
    "en": "English", "en-US": "English", "en-GB": "English", "en-CA": "English",
    "fr": "French", "fr-CA": "French", "es": "Spanish", "es-MX": "Spanish",
    "es-ES": "Spanish", "de": "German", "it": "Italian", "pt": "Portuguese",
    "pt-BR": "Portuguese", "zh": "Chinese", "ja": "Japanese", "ko": "Korean",
    "ru": "Russian", "pl": "Polish", "nl": "Dutch", "tr": "Turkish",
    "vi": "Vietnamese", "hi": "Hindi", "ar": "Arabic",
}

MAX_TOKEN_THRESHOLD = 6000
TRUNCATE_SUFFIX = "... [truncated for token limit]"


def get_natural_lang(code: str) -> str:
    if not code:
        return "English"
    if code in LANG_NAMES:
        return LANG_NAMES[code]
    base = code.split("-")[0].lower()
    return LANG_NAMES.get(base, code)


def _escape_xml(text: str) -> str:
    if not text:
        return ""
    return html.escape(text, quote=False)


def _truncate_text(text: str, max_chars: int = 2000) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars - len(TRUNCATE_SUFFIX)] + TRUNCATE_SUFFIX


def expand_playbook_references(
    text: str,
    variables: list["AgentVariable"] = None,
    session_metadata: dict = None,
    agent_tools: list[dict] = None,
    agent: "Agent" = None
) -> str:
    if not text:
        return ""

    variables = variables or []
    session_metadata = session_metadata or {}
    runtime_vars = session_metadata.get("variables", {})
    agent_tools = agent_tools or []

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

    def tool_sub(match):
        name = match.group(1) or match.group(2)
        found = any(t.get("name") == name if isinstance(t, dict) else t.name == name for t in agent_tools)
        if found:
            return f"the `{name}` tool"
        return f"[unregistered tool: {name}]"

    text = re.sub(r'\$\[tools:(\w+)\]|\$tools:(\w+)', tool_sub, text)

    def rag_sub(match):
        name = match.group(1) or match.group(2)
        return f"the '{name}' knowledge base"

    text = re.sub(r'\$\[rag:(\w+)\]|\$rag:(\w+)', rag_sub, text)
    return text


def build_xml_system_prompt(
    agent: "Agent",
    context_items: list = None,
    business_info: dict = None,
    playbook: Optional["AgentPlaybook"] = None,
    corrections: list[dict] = None,
    guardrails: Optional[dict] = None,
    variables: list["AgentVariable"] = None,
    session_metadata: dict = None,
) -> str:
    context_items = context_items or []
    business_info = business_info or {}
    corrections = corrections or []
    variables = variables or []
    session_metadata = session_metadata or {}

    config = agent.agent_config or {}
    agent_tools = config.get("tools", []) or []
    parts: list[str] = []

    agent_name = _escape_xml(agent.name or "Assistant")
    business_type = (agent.business_type or "general").replace("_", " ").title()

    agent_metadata = getattr(agent, "metadata_", {}) or {}
    is_voice = (
        getattr(agent, "channel", None) == "voice"
        or (isinstance(agent_metadata, dict) and agent_metadata.get("channel") == "voice")
    )

    if is_voice:
        tone_key = "friendly"
        if playbook and playbook.config:
            tone_key = playbook.config.get("tone", "friendly").lower()
        tone_desc = TONE_DESCRIPTIONS.get(tone_key, TONE_DESCRIPTIONS["friendly"])

        allowed_topics = business_type + " services"
        if guardrails and guardrails.get("allowed_topics"):
            allowed_topics = ", ".join(guardrails["allowed_topics"])

        out_of_scope = "I can only help with topics related to our service."
        if playbook and playbook.config and playbook.config.get("out_of_scope_response"):
            out_of_scope = playbook.config.get("out_of_scope_response")

        voice_prompt = build_voice_system_prompt(
            agent_name=agent_name,
            business_name=business_type,
            allowed_topics=allowed_topics,
            out_of_scope_response=out_of_scope,
            tone_description=tone_desc,
            voice_protocol=config.get("voice_system_prompt") or "",
            supported_languages=config.get("supported_languages", None) or [],
        )
        parts.append(f"<agent_voice>\n{_escape_xml(voice_prompt)}\n</agent_voice>")
    else:
        identity = f"You are {agent_name}, an AI assistant for a {business_type} business."
        if agent.personality:
            identity += f"\nPersonality: {agent.personality}"
        parts.append(f"<agent_identity>\n{_escape_xml(identity)}\n</agent_identity>")

    if agent.system_prompt:
        expanded_prompt = expand_playbook_references(
            agent.system_prompt, variables, session_metadata, agent_tools, agent
        )
        parts.append(f"<agent_custom_instructions>\n{_escape_xml(_truncate_text(expanded_prompt))}\n</agent_custom_instructions>")

    session_lang = business_info.get("session_language")
    auto_detect = config.get("auto_detect_language", False)

    if auto_detect and session_lang:
        lang_str = get_natural_lang(session_lang)
    else:
        lang_str = get_natural_lang(config.get("language", "en") or "en")

    if auto_detect:
        supported_langs = config.get("supported_languages", None) or []
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

    parts.append(f"<language_protocol>\n{_escape_xml(lang_instruction)}\n</language_protocol>")

    if playbook and playbook.config:
        playbook_config = playbook.config
        tone_key = playbook_config.get("tone", "professional").lower()
        tone_desc = TONE_DESCRIPTIONS.get(tone_key, TONE_DESCRIPTIONS["professional"])
        parts.append(f"<communication_style>\n{_escape_xml(tone_desc)}\n</communication_style>")

        instructions = playbook_config.get("instructions")
        if instructions:
            expanded_instructions = expand_playbook_references(
                instructions, variables, session_metadata, agent_tools, agent
            )
            parts.append(f"<active_playbook>\n{_escape_xml(_truncate_text(expanded_instructions, 3000))}\n</active_playbook>")

        dos = playbook_config.get("dos", [])
        donts = playbook_config.get("donts", [])
        if dos or donts:
            rules_parts = []
            if dos:
                expanded_dos = [expand_playbook_references(d, variables, session_metadata, agent_tools, agent) for d in dos]
                rules_parts.append("Always:\n" + "\n".join(f"- {_escape_xml(d)}" for d in expanded_dos))
            if donts:
                expanded_donts = [expand_playbook_references(d, variables, session_metadata, agent_tools, agent) for d in donts]
                rules_parts.append("Never:\n" + "\n".join(f"- {_escape_xml(d)}" for d in expanded_donts))
            parts.append(f"<playbook_rules>\n{chr(10).join(rules_parts)}\n</playbook_rules>")

        scenarios = playbook_config.get("scenarios", [])
        if scenarios:
            scenario_parts = []
            for s in scenarios[:10]:
                trigger = s.get("trigger", "")
                response = s.get("response", "")
                if trigger and response:
                    exp_response = expand_playbook_references(response, variables, session_metadata, agent_tools, agent)
                    scenario_parts.append(f'If the user asks about "{_escape_xml(trigger)}":\n→ {_escape_xml(exp_response)}')
            if scenario_parts:
                parts.append(f"<playbook_scenarios>\n{chr(10).join(scenario_parts)}\n</playbook_scenarios>")

        out_of_scope_response = playbook_config.get("out_of_scope_response")
        if out_of_scope_response:
            parts.append(f"<out_of_scope>\n{_escape_xml(out_of_scope_response)}\n</out_of_scope>")

        fallback_response = playbook_config.get("fallback_response")
        if fallback_response:
            parts.append(f"<fallback_response>\n{_escape_xml(fallback_response)}\n</fallback_response>")

    knowledge_items = [c for c in context_items if getattr(c, "type", None) == "knowledge"]
    if knowledge_items:
        kb_parts = []
        for item in knowledge_items[:5]:
            content = getattr(item, "content", "")
            if content:
                kb_parts.append(f"- {_escape_xml(_truncate_text(content, 500))}")
        if kb_parts:
            parts.append(f"<knowledge_base>\n{chr(10).join(kb_parts)}\n</knowledge_base>")

    history_items = [c for c in context_items if getattr(c, "type", None) == "history"]
    if history_items:
        history_parts = []
        for item in history_items[:3]:
            content = getattr(item, "content", "")
            if content:
                history_parts.append(f"- {_escape_xml(_truncate_text(content, 300))}")
        if history_parts:
            parts.append(f"<conversation_history>\n{chr(10).join(history_parts)}\n</conversation_history>")

    global_rules = (guardrails or {}).get("global_rules", {})
    if global_rules and global_rules.get("is_active", True):
        rules_parts = []
        if global_rules.get("blocked_topics"):
            rules_parts.append(f"Blocked Topics: {', '.join(global_rules['blocked_topics'])}")
        if global_rules.get("blocked_keywords"):
            rules_parts.append(f"Restricted Keywords (Global): {', '.join(global_rules['blocked_keywords'])}")
        if rules_parts:
            parts.append(f"<global_guardrails>\n{chr(10).join(rules_parts)}\n</global_guardrails>")

    if guardrails and guardrails.get("is_active"):
        guardrail_parts = []
        if guardrails.get("blocked_topics"):
            guardrail_parts.append(f"Blocked Topics (Do not discuss): {', '.join(guardrails['blocked_topics'])}")
        if guardrails.get("blocked_keywords"):
            guardrail_parts.append(f"Restricted Keywords (Avoid using): {', '.join(guardrails['blocked_keywords'])}")
        if guardrails.get("allowed_topics") and not is_voice:
            guardrail_parts.append(f"Focused Topics (Stay within): {', '.join(guardrails['allowed_topics'])}")
        if guardrail_parts:
            parts.append(f"<safety_policies>\n{chr(10).join(guardrail_parts)}\n</safety_policies>")

    custom_rules = (guardrails or {}).get("custom_rules", [])
    if custom_rules:
        custom_parts = []
        for cg in custom_rules:
            if cg.get("is_active", True):
                custom_parts.append(f"- [{cg.get('category', 'Custom')}] {_escape_xml(cg['rule'])}")
        if custom_parts:
            parts.append(f"<custom_guardrails>\n{chr(10).join(custom_parts)}\n</custom_guardrails>")

    parts.append("<data_source_priority>\nYou MUST use available data sources in this order:\n1. First, use the PLAYBOOK instructions above if one is matched\n2. Second, use the KNOWLEDGE BASE CONTEXT if provided\n3. Third, use any TOOLS available to you to fetch information\nIf none of these sources can answer the question, respond with: \"I don't have enough information to answer that. Could you rephrase or provide more details?\"\n</data_source_priority>")

    if corrections:
        corr_parts = []
        for c in corrections[-10:]:
            user_msg = c.get("user_message", "")
            ideal = c.get("ideal_response", "")
            if user_msg and ideal:
                corr_parts.append(f'When asked: "{_escape_xml(user_msg[:200])}" -> Correct answer: "{_escape_xml(ideal[:400])}"')
        if corr_parts:
            parts.append(f"<corrections>\n{chr(10).join(corr_parts)}\n</corrections>")

    customer_profile = business_info.get("customer_profile", {})
    if customer_profile:
        name = customer_profile.get("name", "")
        if name:
            parts.append(f"<customer_context>\nYou are speaking with {_escape_xml(name)}.\n</customer_context>")

    if variables:
        var_parts = []
        runtime_vars = session_metadata.get("variables", {})
        for v in variables:
            val = runtime_vars.get(v.name)
            if val is None and isinstance(v.default_value, dict):
                val = v.default_value.get("value")
            val_str = f'"{val}"' if isinstance(val, str) else str(val) if val is not None else "null"
            var_parts.append(f"- {v.name} ({v.data_type}): {val_str}")
        if var_parts:
            parts.append(f"<context_variables>\n{chr(10).join(var_parts)}\n</context_variables>")

    full_prompt = "\n".join(parts)
    
    if len(full_prompt) > MAX_TOKEN_THRESHOLD * 4:
        full_prompt = _truncate_text(full_prompt, MAX_TOKEN_THRESHOLD * 4)
        logger.warning("prompt_truncated", agent_id=str(agent.id), original_length=len(parts))

    return full_prompt


def build_system_prompt(
    agent: "Agent",
    context_items: list = None,
    business_info: dict = None,
    playbook: Optional["AgentPlaybook"] = None,
    corrections: list[dict] = None,
    guardrails: Optional[dict] = None,
    variables: list["AgentVariable"] = None,
    session_metadata: dict = None,
) -> str:
    return build_xml_system_prompt(
        agent=agent,
        context_items=context_items,
        business_info=business_info,
        playbook=playbook,
        corrections=corrections,
        guardrails=guardrails,
        variables=variables,
        session_metadata=session_metadata,
    )
