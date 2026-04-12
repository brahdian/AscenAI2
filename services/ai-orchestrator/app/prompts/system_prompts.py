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


def _build_lang_protocol(config: dict, business_info: dict) -> str:
    """Return a <language_protocol> block for text agents."""
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
        langs_joined = _escape_xml(", ".join(list(dict.fromkeys(supported_names))))
        lang_str_esc = _escape_xml(lang_str)
        return (
            f"<language_protocol>\n"
            f"Supported languages: {langs_joined}.\n"
            f"Current session language: {lang_str_esc}.\n"
            f"If the user speaks any supported language, pivot and respond in that language immediately.\n"
            f"If the user speaks an unsupported language, politely inform them you only support {langs_joined}.\n"
            f"</language_protocol>"
        )
    else:
        lang_str_esc = _escape_xml(lang_str)
        return f"<language_protocol>\nAlways respond in: {lang_str_esc}.\n</language_protocol>"


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
    business_type = _escape_xml((agent.business_type or "general").replace("_", " ").title())

    agent_metadata = getattr(agent, "metadata_", {}) or {}
    is_voice = (
        getattr(agent, "channel", None) == "voice"
        or (isinstance(agent_metadata, dict) and agent_metadata.get("channel") == "voice")
    )

    # ------------------------------------------------------------------ #
    # 1. <identity>                                                        #
    # Who the agent is, tone, persona, language rules.                    #
    # ------------------------------------------------------------------ #
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

        voice_identity = build_voice_system_prompt(
            agent_name=agent_name,
            business_name=business_type,
            allowed_topics=allowed_topics,
            out_of_scope_response=out_of_scope,
            tone_description=tone_desc,
            voice_protocol=config.get("voice_system_prompt") or "",
            supported_languages=config.get("supported_languages", None) or [],
        )

        # Build voice context: tell the LLM what the scripted opening said and
        # what languages are available. The opening was delivered verbatim by
        # the TTS engine — the LLM must not repeat or paraphrase it.
        voice_context_lines = []
        voice_opening = (session_metadata or {}).get("_voice_opening")
        if voice_opening:
            voice_context_lines.append(
                f"The following opening was already delivered verbatim to the caller by the TTS engine. "
                f"Do NOT repeat, paraphrase, or reference it:\n\"{_escape_xml(voice_opening)}\""
            )
        supported_langs = config.get("supported_languages") or []
        if supported_langs:
            lang_names = [get_natural_lang(l) for l in supported_langs]
            voice_context_lines.append(
                f"Supported languages for this session: {_escape_xml(', '.join(lang_names))}. "
                f"If the caller speaks any of these, respond in that language immediately."
            )

        identity_parts = [_escape_xml(voice_identity)]
        if voice_context_lines:
            identity_parts.append(
                f"<voice_context>\n{chr(10).join(voice_context_lines)}\n</voice_context>"
            )
        parts.append(f"<identity>\n{chr(10).join(identity_parts)}\n</identity>")
    else:
        tone_key = "professional"
        if playbook and playbook.config:
            tone_key = playbook.config.get("tone", "professional").lower()
        tone_desc = TONE_DESCRIPTIONS.get(tone_key, TONE_DESCRIPTIONS["professional"])

        identity_lines = [
            f"You are {agent_name}, an AI assistant for a {business_type} business.",
        ]
        if agent.personality:
            identity_lines.append(f"Personality: {_escape_xml(agent.personality)}")
        identity_lines.append(f"Tone: {_escape_xml(tone_desc)}")
        identity_lines.append(_build_lang_protocol(config, business_info))

        parts.append(f"<identity>\n{chr(10).join(identity_lines)}\n</identity>")

    # ------------------------------------------------------------------ #
    # 2. <objective>                                                       #
    # What success looks like for this interaction.                       #
    # Only emitted when a playbook with a description is active.          #
    # ------------------------------------------------------------------ #
    if playbook and getattr(playbook, "description", None):
        objective = (
            f"Your goal: {_escape_xml(playbook.description)}\n"
            f"Success means: The customer's request is fully resolved within the scope of this playbook."
        )
        parts.append(f"<objective>\n{objective}\n</objective>")

    # ------------------------------------------------------------------ #
    # 3. <instructions>                                                   #
    # Operator-defined custom behavior for this agent.                   #
    # ------------------------------------------------------------------ #
    if agent.system_prompt:
        expanded_prompt = expand_playbook_references(
            agent.system_prompt, variables, session_metadata, agent_tools, agent
        )
        parts.append(
            f"<instructions>\n{_escape_xml(_truncate_text(expanded_prompt))}\n</instructions>"
        )

    # ------------------------------------------------------------------ #
    # 4. <constraints>                                                    #
    # Guardrails: global platform rules, agent-level rules, custom rules. #
    # ------------------------------------------------------------------ #
    constraint_sections: list[str] = []

    global_rules = (guardrails or {}).get("global_rules", {})
    if global_rules and global_rules.get("is_active", True):
        global_lines = []
        if global_rules.get("blocked_topics"):
            global_lines.append(f"Blocked Topics: {_escape_xml(', '.join(global_rules['blocked_topics']))}")
        if global_rules.get("blocked_keywords"):
            global_lines.append(f"Restricted Keywords: {_escape_xml(', '.join(global_rules['blocked_keywords']))}")
        if global_lines:
            constraint_sections.append(f"<global>\n{chr(10).join(global_lines)}\n</global>")

    if guardrails and guardrails.get("is_active"):
        agent_lines = []
        if guardrails.get("blocked_topics"):
            agent_lines.append(f"Blocked Topics (Do not discuss): {_escape_xml(', '.join(guardrails['blocked_topics']))}")
        if guardrails.get("blocked_keywords"):
            agent_lines.append(f"Restricted Keywords (Avoid using): {_escape_xml(', '.join(guardrails['blocked_keywords']))}")
        if guardrails.get("allowed_topics") and not is_voice:
            agent_lines.append(f"Focused Topics (Stay within): {_escape_xml(', '.join(guardrails['allowed_topics']))}")
        if agent_lines:
            constraint_sections.append(f"<agent>\n{chr(10).join(agent_lines)}\n</agent>")

    custom_rules = (guardrails or {}).get("custom_rules", [])
    if custom_rules:
        custom_lines = []
        for cg in custom_rules:
            if cg.get("is_active", True):
                category = _escape_xml(cg.get("category", "Custom"))
                rule = _escape_xml(cg["rule"])
                custom_lines.append(f"- [{category}] {rule}")
        if custom_lines:
            constraint_sections.append(f"<custom>\n{chr(10).join(custom_lines)}\n</custom>")

    if constraint_sections:
        parts.append(f"<constraints>\n{chr(10).join(constraint_sections)}\n</constraints>")

    # ------------------------------------------------------------------ #
    # 5. <tools>                                                          #
    # Available tools and when/how to call them.                         #
    # Only emitted when the agent has registered tools.                  #
    # ------------------------------------------------------------------ #
    if agent_tools:
        tool_lines = []
        for t in agent_tools:
            name = t.get("name") if isinstance(t, dict) else getattr(t, "name", str(t))
            desc = t.get("description", "") if isinstance(t, dict) else getattr(t, "description", "")
            if name:
                line = f"- {_escape_xml(str(name))}"
                if desc:
                    line += f": {_escape_xml(str(desc))}"
                tool_lines.append(line)
        if tool_lines:
            tool_content = (
                "Available tools:\n"
                + "\n".join(tool_lines)
                + "\n\nPriority: Use tools only when the playbook instructions and knowledge base cannot answer the request.\n"
                + "Never infer or guess tool names. Never call a tool not listed above.\n"
                + "Confirm high-risk actions (payments, SMS, emails) with the user before executing."
            )
            parts.append(f"<tools>\n{tool_content}\n</tools>")

    # ------------------------------------------------------------------ #
    # 6. <memory>                                                         #
    # Knowledge base, conversation history, customer profile,            #
    # few-shot corrections, and session variables.                        #
    # ------------------------------------------------------------------ #
    memory_sections: list[str] = []

    knowledge_items = [c for c in context_items if getattr(c, "type", None) == "knowledge"]
    if knowledge_items:
        kb_lines = []
        for item in knowledge_items[:5]:
            content = getattr(item, "content", "")
            if content:
                kb_lines.append(f"- {_escape_xml(_truncate_text(content, 500))}")
        if kb_lines:
            memory_sections.append(f"<knowledge>\n{chr(10).join(kb_lines)}\n</knowledge>")

    history_items = [c for c in context_items if getattr(c, "type", None) == "history"]
    if history_items:
        hist_lines = []
        for item in history_items[:3]:
            content = getattr(item, "content", "")
            if content:
                hist_lines.append(f"- {_escape_xml(_truncate_text(content, 300))}")
        if hist_lines:
            memory_sections.append(f"<history>\n{chr(10).join(hist_lines)}\n</history>")

    customer_profile = business_info.get("customer_profile", {})
    if customer_profile and customer_profile.get("name"):
        customer_name = _escape_xml(customer_profile["name"])
        memory_sections.append(f"<customer>You are speaking with {customer_name}.</customer>")

    if corrections:
        corr_lines = []
        for c in corrections[-10:]:
            user_msg = c.get("user_message", "")
            ideal = c.get("ideal_response", "")
            if user_msg and ideal:
                corr_lines.append(
                    f'When asked: "{_escape_xml(user_msg[:200])}" \u2192 Correct answer: "{_escape_xml(ideal[:400])}"'
                )
        if corr_lines:
            memory_sections.append(f"<corrections>\n{chr(10).join(corr_lines)}\n</corrections>")

    if variables:
        var_lines = []
        runtime_vars = session_metadata.get("variables", {})
        for v in variables:
            val = runtime_vars.get(v.name)
            if val is None and isinstance(v.default_value, dict):
                val = v.default_value.get("value")
            val_str = f'"{val}"' if isinstance(val, str) else str(val) if val is not None else "null"
            var_lines.append(f"- {_escape_xml(v.name)} ({_escape_xml(v.data_type)}): {_escape_xml(val_str)}")
        if var_lines:
            memory_sections.append(f"<variables>\n{chr(10).join(var_lines)}\n</variables>")

    if memory_sections:
        parts.append(f"<memory>\n{chr(10).join(memory_sections)}\n</memory>")

    # ------------------------------------------------------------------ #
    # 7. <redaction>                                                      #
    # PII handling rules. Always emitted — platform baseline minimum.    #
    # ------------------------------------------------------------------ #
    redaction_lines = [
        "Never repeat, store, or transmit: full credit card numbers, SSNs, passwords, or full dates of birth.",
        "If any of the above are detected in user input, replace with [REDACTED] in all outputs.",
        "Never include raw API keys, internal service URLs, stack traces, or database IDs in any response.",
    ]
    pii_rules = (guardrails or {}).get("pii_redaction", [])
    if pii_rules:
        for rule in pii_rules:
            if isinstance(rule, str) and rule.strip():
                redaction_lines.append(f"- {_escape_xml(rule)}")
    parts.append(f"<redaction>\n{chr(10).join(redaction_lines)}\n</redaction>")

    # ------------------------------------------------------------------ #
    # 8. <playbook>                                                       #
    # Step-by-step workflow, rules (dos/don'ts), scenarios, and          #
    # fallback/out-of-scope handling for the active playbook.            #
    # ------------------------------------------------------------------ #
    if playbook and playbook.config:
        playbook_config = playbook.config
        playbook_sections: list[str] = []

        instructions = playbook_config.get("instructions")
        if instructions:
            expanded_instructions = expand_playbook_references(
                instructions, variables, session_metadata, agent_tools, agent
            )
            playbook_sections.append(
                f'<step id="1">\n{_escape_xml(_truncate_text(expanded_instructions, 3000))}\n</step>'
            )

        dos = playbook_config.get("dos", [])
        donts = playbook_config.get("donts", [])
        if dos or donts:
            rules_lines = []
            if dos:
                expanded_dos = [
                    expand_playbook_references(d, variables, session_metadata, agent_tools, agent)
                    for d in dos
                ]
                rules_lines.append("Always:\n" + "\n".join(f"- {_escape_xml(d)}" for d in expanded_dos))
            if donts:
                expanded_donts = [
                    expand_playbook_references(d, variables, session_metadata, agent_tools, agent)
                    for d in donts
                ]
                rules_lines.append("Never:\n" + "\n".join(f"- {_escape_xml(d)}" for d in expanded_donts))
            playbook_sections.append(f"<rules>\n{chr(10).join(rules_lines)}\n</rules>")

        scenarios = playbook_config.get("scenarios", [])
        if scenarios:
            scenario_lines = []
            for s in scenarios[:10]:
                trigger = s.get("trigger", "")
                response = s.get("response", "")
                if trigger and response:
                    exp_response = expand_playbook_references(
                        response, variables, session_metadata, agent_tools, agent
                    )
                    scenario_lines.append(
                        f'If user asks "{_escape_xml(trigger)}":\n\u2192 {_escape_xml(exp_response)}'
                    )
            if scenario_lines:
                playbook_sections.append(f"<scenarios>\n{chr(10).join(scenario_lines)}\n</scenarios>")

        out_of_scope_response = playbook_config.get("out_of_scope_response")
        if out_of_scope_response:
            playbook_sections.append(
                f"<out_of_scope>{_escape_xml(out_of_scope_response)}</out_of_scope>"
            )

        fallback_response = playbook_config.get("fallback_response")
        if fallback_response:
            playbook_sections.append(
                f"<fallback>{_escape_xml(fallback_response)}</fallback>"
            )

        if playbook_sections:
            parts.append(f"<playbook>\n{chr(10).join(playbook_sections)}\n</playbook>")

    # ------------------------------------------------------------------ #
    # 9. <output_contract>                                                #
    # How to use sources, format rules, and what to never do.            #
    # ------------------------------------------------------------------ #
    output_contract = (
        "Source priority:\n"
        "1. Use <playbook> instructions above if a playbook is active.\n"
        "2. Use <memory><knowledge> context if provided.\n"
        "3. Use <tools> to fetch live information if available.\n"
        'If none of these sources can answer: say "I don\'t have enough information to answer that. '
        'Could you rephrase or provide more details?"\n\n'
        "Format rules:\n"
        "- Plain prose only. No markdown tables. No excessive bullet lists.\n"
        "- Never hallucinate facts not present in memory, playbook, or tool results.\n"
        "- Tool call format: JSON with exact parameter names from the tool schema.\n"
        "- Never expose internal error messages, stack traces, or system configuration."
    )
    parts.append(f"<output_contract>\n{output_contract}\n</output_contract>")

    # ------------------------------------------------------------------ #
    # Assemble and enforce token budget                                   #
    # ------------------------------------------------------------------ #
    full_prompt = "<agent>\n" + "\n".join(parts) + "\n</agent>"

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
