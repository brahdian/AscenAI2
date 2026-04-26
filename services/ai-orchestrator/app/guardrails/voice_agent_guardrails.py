"""
Voice-First AI Agent Guardrails
================================

Produced from adversarial QA stress-test analysis (23 test cases, 6 categories).

This module contains:
  1. VOICE_AGENT_SYSTEM_PROMPT  — revised base system prompt for voice-first agents
  2. GLOBAL_GUARDRAILS          — rules the agent MUST always follow, regardless of
                                   operator customisation
  3. ANTIFRAILTY_CHECKLIST      — testing checklist for future QA regression sprints

Use build_voice_system_prompt() to compose the full prompt with agent-specific context.

Adversarial QA Categories Addressed
-------------------------------------
A. Speech / audio edge cases        (TC-A01 | TC-A04)
B. Prompt injection                 (TC-B01 | TC-B05)
C. Conversation robustness          (TC-C01 | TC-C04)
D. Tool misuse / confirmation       (TC-D01 | TC-D04)
E. Safety / boundary enforcement    (TC-E01 | TC-E05)
F. Performance / concurrency stress (TC-F01 | TC-F04)
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. Revised Voice-First System Prompt
# ---------------------------------------------------------------------------


# Mapping of ISO 639-1 codes to their respective "please speak in [language]" phrases.
from sqlalchemy.ext.asyncio import AsyncSession
from app.services import pii_service
from app.services.settings_service import SettingsService


async def generate_multilingual_greeting(
    db: AsyncSession, 
    primary_language: str | None = None,
    supported_languages: list[str] | None = None,
    custom_greeting: str | None = None,
    redact: bool = True
) -> str:
    """
    Generate the audible MANDATORY OPENING string based on selected languages and platform settings.
    Redacts PII from custom greetings for safety.
    """
    import app.services.pii_service as pii_service
    # 1. Fetch config from Platform Settings (with cache in SettingsService)
    lang_config = await SettingsService.get_setting(db, "global_language_config", {})
    
    # Ensure primary language is always considered in the set of supported languages
    primary_lang = primary_language or "en"
    langs = list(supported_languages) if supported_languages else []
    if primary_lang not in langs:
        langs.insert(0, primary_lang)
    
    # 2. Filter out languages we don't have phrases for
    greeting_map = lang_config.get("greetings", {})
    prefix_map = lang_config.get("assist_prefixes", {})
    lang_data = lang_config.get("languages", [])
    
    # Check against the base language (e.g., 'fr-CA' -> 'fr') to see if we have a phrase
    active_langs = []
    for l in langs:
        base = l.split("-")[0]
        if base in greeting_map and l not in active_langs:
            active_langs.append(l)

    if not active_langs:
        base_primary = primary_lang.split("-")[0]
        active_langs = [primary_lang] if base_primary in greeting_map else ["en"]

    # Map codes to labels (prefer native_label for speech)
    lang_labels = {}
    for item in lang_data:
        code = item.get("code")
        label = item.get("native_label") or item.get("label") or code
        lang_labels[code] = label
    
    # Generate the set of language names to be mentioned
    names = []
    for l in active_langs:
        label = lang_labels.get(l, l)
        # Strip parentheticals like "English (Global)" -> "English"
        clean_label = label.split("(")[0].strip()
        if clean_label not in names:
            names.append(clean_label)

    # Pick the lead greeting prefix localized to the primary language
    lead_lang_base = primary_lang.split("-")[0]
    
    if custom_greeting and custom_greeting.strip():
        greeting_prefix_phrase = custom_greeting.strip()
        if redact:
            greeting_prefix_phrase = pii_service.redact(greeting_prefix_phrase)
    else:
        greeting_prefix_phrase = greeting_map.get(lead_lang_base, greeting_map.get("en", "Thank you for calling.")).strip()
        
    if greeting_prefix_phrase.endswith("."):
        greeting_prefix_phrase = greeting_prefix_phrase[:-1]

    # The Multi-lingual assist strings and extra phrases have been removed from the greeting.
    # They are now properly handled by the IVR phase (generate_ivr_language_prompt)
    greeting = greeting_prefix_phrase
    
    # Standardize redaction for audible strings (Round 9 Hardening)
    if redact:
        return pii_service.redact(greeting.strip())
    return greeting.strip()

# Mapping for "I didn't catch that" fallback phrases.
LANGUAGE_FALLBACK_MAP = {
    "en": "Sorry, I didn't quite catch that. Could you say that again?",
    "fr": "Désolé, je n'ai pas bien compris. Pourriez-vous répéter?",
    "zh": "对不起，我没听清。请再说一遍。",
    "es": "Lo siento, no he entendido bien. ¿Podría repetir?",
    "de": "Entschuldigung, das habe ich nicht verstanden. Könnten Sie das bitte wiederholen?",
    "it": "Scusa, non ho capito bene. Potresti ripetere?",
    "pt": "Desculpe, não entendi bem. Você poderia repetir?",
    "hi": "क्षमा करें, मुझे समझ नहीं आया। क्या आप फिर से कह सकते हैं?",
    "tl": "Pasensya na, hindi ko nakuha iyon. Maaari mo bang sabihin muli?",
}

async def generate_multilingual_fallback(
    db: AsyncSession, 
    supported_languages: list[str] | None = None,
    redact: bool = True
) -> str:
    """
    Generate the multilingual "I didn't catch that" message based on selected languages and platform settings.
    """
    lang_config = await SettingsService.get_setting(db, "global_language_config", {})
    fallback_map = lang_config.get("fallbacks", {})  # Check if in dynamic config first
    
    langs = supported_languages or ["en"]
    if not isinstance(langs, list):
        langs = ["en"]
    
    # Merge with static map as safety
    merged_map = {**LANGUAGE_FALLBACK_MAP, **fallback_map}
    
    active_langs = [l for l in langs if l in merged_map]
    if not active_langs:
        active_langs = ["en"]

    phrases = [merged_map[l] for l in active_langs if l in merged_map]
    # Standardize redaction for audible fallout strings
    if redact:
        return pii_service.redact(" ".join(phrases))
    return " ".join(phrases)

# ---------------------------------------------------------------------------
# 1.5 Mandatory Base Protocols
# ---------------------------------------------------------------------------

DEFAULT_CORE_VOICE_PROTOCOL = """\
## CORE VOICE PERFORMANCE PROTOCOL
- **STRICT CONCISION**: Prioritize brevity. Use short, punchy sentences. Avoid nested clauses.
- **NATURAL TURN-TAKING**: End your turns with clear cues or questions to signal the user it is their turn to speak.
- **AUDIO ADAPTATION**: Do not use markdown like bolding or bullet points in your speech as it may confuse the TTS engine. Use punctuation (commas, periods) to control cadence.
- **CONFIRMATION FLOW**: For critical actions (payments, bookings), always repeat the key details back to the user for verbal confirmation before proceeding.
"""

async def generate_ivr_language_prompt(
    db: AsyncSession,
    supported_languages: list[str] | None = None
) -> str:
    """
    Generate an IVR language-selection prompt based on supported languages.
    Example: "For English, press 1. Pour le français, appuyez sur 2."
    """
    if not supported_languages or len(supported_languages) <= 1:
        return ""

    lang_config = await SettingsService.get_setting(db, "global_language_config", {})
    lang_data = lang_config.get("languages", [])
    
    # Map codes to labels (prefer native_label for speech)
    lang_labels = {}
    for item in lang_data:
        code = item.get("code")
        label = item.get("native_label") or item.get("label") or code
        lang_labels[code] = label

    prompts = []
    for i, code in enumerate(supported_languages, 1):
        label = lang_labels.get(code, code)
        # Strip parentheticals
        clean_label = label.split("(")[0].strip()
        
        # We assume a standard mapping for "index" to words in major languages or just use digits
        # For now, we'll use a simple multi-lingual template
        if code.startswith("en"):
            prompts.append(f"For {clean_label}, press {i}.")
        elif code.startswith("fr"):
            prompts.append(f"Pour le {clean_label}, appuyez sur {i}.")
        elif code.startswith("es"):
            prompts.append(f"Para {clean_label}, presione {i}.")
        elif code.startswith("hi"):
            prompts.append(f"{clean_label} के लिए, {i} दबाएं।")
        else:
            # Generic fallback
            prompts.append(f"For {clean_label}, press {i}.")

    # Standardize redaction for IVR prompts
    return pii_service.redact(" ".join(prompts))


async def get_dynamic_voice_protocol(
    db: AsyncSession,
    supported_languages: list[str] | None = None,
    redact: bool = True
) -> str:
    """Return the IVR & Multi-lingual Protocol block using dynamic templates from Platform Settings."""
    opening = await generate_multilingual_greeting(db, supported_languages=supported_languages, redact=redact)
    all_langs = ", ".join(supported_languages) if supported_languages else "English"

    # Fetch template from settings
    protocol_setting = await SettingsService.get_setting(db, "voice_protocol_template", {})
    template = protocol_setting.get("template")

    if not template:
        # Fallback to hardcoded if not in DB
        template = """\
## Multi-lingual & IVR Operational Protocol
- **ACTIVE SESSION CONTEXT**: The call has already been initialized with a greeting and language-selection prompt. Use the user's first response to confirm their preferred tongue.
- **DYNAMIC LANGUAGE ADAPTATION**: You are globally configured to handle the following languages: {all_langs}.
- **PROTOCOL**: Upon detecting ANY of the supported languages, pivot your response language immediately to match the user without requesting procedural confirmation (e.g., avoid "Would you like to speak French?").
- **CONTEXTUAL METADATA**: Ensure the `language` field in your response metadata accurately identifies the communication language used in the current turn.
"""

    # Standardize redaction for protocol templates (Round 9)
    result = template.replace("{all_langs}", all_langs)
    if redact:
        return pii_service.redact(result)
    return result


async def get_or_compute_voice_strings(
    db: AsyncSession,
    agent,
) -> tuple[str, str, str]:
    """
    Return (greeting, protocol, fallback) for a voice agent.

    On the first call the strings are computed from platform settings and
    cached inside agent.agent_config under the keys:
        _cached_greeting, _cached_protocol, _cached_fallback, _cached_langs

    On subsequent calls they are returned from the cache, skipping DB/Redis
    lookups entirely.  The cache is invalidated automatically when
    supported_languages changes (the stored lang list is compared).

    Returns a tuple: (greeting, protocol, fallback)
    """
    cfg = agent.agent_config or {}
    supported_langs: list[str] = cfg.get("supported_languages") or []
    cached_langs: list[str] = cfg.get("_cached_langs") or []

    # Cache hit: same language list and all strings present
    if (
        cached_langs == supported_langs
        and cfg.get("_cached_greeting")
        and cfg.get("_cached_protocol")
        and cfg.get("_cached_fallback")
        and cfg.get("_cached_preset_protocol")
    ):
        return (
            cfg["_cached_greeting"],
            cfg["_cached_protocol"],
            cfg["_cached_fallback"],
        )

    # Cache miss: compute and persist (Unredacted for TTS and Preview)
    primary_lang = getattr(agent, 'language', None) or 'en'
    greeting  = await generate_multilingual_greeting(db, primary_lang, supported_langs, redact=False)
    protocol  = await get_dynamic_voice_protocol(db, supported_langs, redact=False)
    fallback  = await generate_multilingual_fallback(db, supported_langs, redact=False)
    
    # Ensure Core Protocol is always injected (Mandatory)
    preset_protocol = DEFAULT_CORE_VOICE_PROTOCOL
    global_presets = await SettingsService.get_setting(db, "global_voice_protocols", default=[])
    for p in global_presets:
        if p.get("template"):
            preset_protocol += "\n\n" + p.get("template", "")

    # Write back into agent_config (JSONB MutableDict — SQLAlchemy tracks the mutation)
    new_cfg = dict(cfg)
    new_cfg["_cached_greeting"] = greeting
    new_cfg["_cached_protocol"] = protocol
    new_cfg["_cached_fallback"] = fallback
    new_cfg["_cached_langs"] = supported_langs
    new_cfg["_cached_preset_protocol"] = preset_protocol
    agent.agent_config = new_cfg

    return greeting, protocol, fallback

# ---------------------------------------------------------------------------
# 2. Global Guardrails
#    These rules are applied in code (orchestrator.py + proxy.py) and ALSO
#    injected into the system prompt. Code-level enforcement is the primary
#    safety layer; prompt-level is the secondary UX layer.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 3. Custom Guardrail Enforcement
#    Rules authored by the operator via the dashboard per-agent.
# ---------------------------------------------------------------------------

def format_custom_guardrails(rules: list[dict]) -> str:
    """Format custom rules into a system-prompt XML block."""
    if not rules:
        return ""
    
    active_rules = [r.get("rule") for r in rules if r.get("is_active", True) and r.get("rule")]
    if not active_rules:
        return ""
    
    rule_items = "\n".join(f"  - {rule}" for rule in active_rules)
    return f"""<custom_guardrails>
Always adhere to these specific operational rules:
{rule_items}
</custom_guardrails>"""


# ---------------------------------------------------------------------------
# 4. Builder — compose full voice system prompt
# ---------------------------------------------------------------------------

def build_voice_system_prompt(
    base_prompt_template: str,
    agent_name: str = "Assistant",
    business_name: str = "our business",
    allowed_topics: str = "our services",
    out_of_scope_response: str = "I can only help with topics related to our service.",
    tone_description: str = "Be warm, concise, and natural.",
    voice_protocol: str = "",
    custom_guardrails: list[dict] = None,
) -> str:
    """
    Return the voice-specific identity content string.

    This output is inserted into the <identity> section of the <agent> XML
    prompt by build_xml_system_prompt() in app/prompts/system_prompts.py.
    It is NOT a standalone prompt — the caller wraps it with the full
    9-section <agent> structure (constraints, tools, memory, etc.).
    """
    if not base_prompt_template:
        base_prompt_template = "You are $[vars:agent_name], a voice-first AI assistant for $[vars:business_name].\n"

    # Use a safe replacement approach to avoid issues with literal braces {} in the template
    prompt = base_prompt_template
    replacements = {
        "{agent_name}": "$[vars:agent_name]", # support legacy placeholders in existing templates
        "{business_name}": "$[vars:business_name]",
        "{allowed_topics}": "$[vars:allowed_topics]",
        "{out_of_scope_response}": "$[vars:out_of_scope_response]",
        "{tone_description}": tone_description,
    }
    for k, v in replacements.items():
        prompt = prompt.replace(k, str(v))
    
    # We also resolve the provided arguments directly if they were originally intended for format()
    # but now we prefer expansion in expansion_playbook_references. 
    # However, tone_description is often a large snippet, so we replace it here.
    
    if voice_protocol:
        prompt += f"\n\n{voice_protocol}"
    
    return prompt
