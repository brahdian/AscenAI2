"""
Builder utilities for Zenith State template seeding.
Variable syntax: $vars:key (never $[vars:key])
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional


def _build_instructions(
    role: str,
    objective: str,
    context: str,
    rules: List[str],
    tool_usage: str,
    escalation: str,
    safety: str,
    compliance: str,
    conversation_style: str,
    edge_cases: Optional[Dict[str, str]] = None,
) -> str:
    """
    Build a Gemini-optimized XML instruction block.
    dos/donts/scenarios are stored separately in config — NOT duplicated here.
    """
    rules_str = "\n".join(f"  - {r}" for r in rules)

    edge_str = ""
    if edge_cases:
        items = "\n".join(f"  - {k}: {v}" for k, v in edge_cases.items())
        edge_str = f"\n<edge_cases>\n{items}\n</edge_cases>"

    return f"""<role>{role}</role>
<objective>{objective}</objective>
<context>{context}</context>
<rules>
{rules_str}
</rules>
<tool_usage>{tool_usage}</tool_usage>
<escalation>{escalation}</escalation>
<safety>{safety}</safety>
<compliance>{compliance}</compliance>
<conversation_style>{conversation_style}</conversation_style>{edge_str}""".strip()


def _create_playbook(
    name: str,
    description: str,
    instructions: str,
    tone: str,
    dos: List[str],
    donts: List[str],
    scenarios: List[Dict[str, Any]],
    trigger_condition: Dict[str, Any],
    fallback_response: str,
    out_of_scope_response: str,
    is_default: bool = False,
) -> Dict[str, Any]:
    """Factory ensuring all 10 required playbook fields are present."""
    return {
        "name": name,
        "description": description,
        "instructions": instructions.strip(),
        "tone": tone,
        "dos": dos,
        "donts": donts,
        "scenarios": scenarios,
        "trigger_condition": trigger_condition,
        "fallback_response": fallback_response,
        "out_of_scope_response": out_of_scope_response,
        "is_default": is_default,
    }
