import re
import html
from typing import TYPE_CHECKING, Optional
import structlog
import app.services.pii_service as pii_service

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.variable import AgentVariable

logger = structlog.get_logger(__name__)

def resolve_agent_variables(
    text: str,
    agent: "Agent",
    variables: list["AgentVariable"] = None,
    clean: bool = True,
    redact: bool = True
) -> str:
    """
    Expand $vars:name placeholders in a string using agent attributes and variables.
    
    If clean=True: returns just the value (e.g. "My Business").
    If clean=False: returns the value with meta hint (e.g. "My Business (variable: business_name)").
    """
    if not text:
        return ""

    variables = variables or []

    def var_sub(match):
        name = match.group(1) or match.group(2)
        val = None
        
        # 1. Built-in agent attributes
        if agent:
            if name == 'agent_name':
                val = agent.name
            elif name in ['business_name', 'clinic_name', 'company_name', 'firm_name', 'business_type']:
                # Fallback to business_type if specific name isn't set
                val = (agent.business_type or "general").replace("_", " ").title()
            elif name == 'tone' or name == 'personality':
                val = agent.personality or (agent.agent_config or {}).get("tone", "professional")
            
        # 2. Agent Variables (Persistent)
        if val is None:
            # Handle business name aliases
            BUSINESS_ALIASES = ['business_name', 'clinic_name', 'company_name', 'firm_name', 'company']
            search_names = [name]
            if name in BUSINESS_ALIASES:
                search_names = BUSINESS_ALIASES + ['business_type']
            
            v_obj = None
            for s_name in search_names:
                v_obj = next((v for v in variables if v.name == s_name), None)
                if v_obj:
                    break
            
            if v_obj:
                # AgentVariable.default_value is stored as JSONB; extract it directly.
                # If it's a dict, we return it as a stringified JSON unless it's a simple wrapper.
                val = v_obj.default_value
                if isinstance(val, dict) and "value" in val and len(val) == 1:
                    val = val["value"]
            elif name in BUSINESS_ALIASES and agent:
                val = (agent.business_type or "general").replace("_", " ").title()

        if val is not None:
            # FIX-06: Scrub PII from variable values before they leave this function.
            # This protects greetings, IVR text, and preview API results — none of
            # which go through the system_prompts.py <variables> block redaction.
            scrubbed = str(val)
            if redact:
                scrubbed = pii_service.redact(scrubbed)
            # FIX-06: Apply XML structural isolation for transcript safety.
            # While TTS handles raw text, these strings are saved to the Message
            # table and rendered in the dashboard.
            val_esc = html.escape(scrubbed, quote=False)
            if clean:
                return val_esc
            return f"{val_esc} (variable: {name})"

        # FIX-11: Log unresolved placeholders so operators can detect misconfigured templates
        logger.warning(
            "variable_placeholder_unresolved",
            name=name,
            agent_id=str(agent.id) if agent else "unknown",
        )
        return f"[unknown variable: {name}]"

    # Support both $[vars:name] and $vars:name - ensured name starts with a letter.
    result = re.sub(r'\$\[vars:([a-zA-Z][a-zA-Z0-9_]*)\]|\$vars:([a-zA-Z][a-zA-Z0-9_]*)', var_sub, text)
    return result
