"""
ModelRouter — routes each LLM request to the optimal model based on complexity.

Complexity tiers
----------------
low     — simple factual / single-step queries
          → Gemini Flash-lite / GPT-4o-mini
medium  — multi-turn, moderate reasoning
          → Gemini Flash / GPT-4o
high    — complex reasoning, long context, agentic chains
          → Gemini Pro / GPT-4o (with max context)

Complexity is estimated by a lightweight heuristic:
  - token count of the conversation context
  - presence of tool-call history in this turn
  - LLM-step calls from a playbook (always medium/high)

Tenants can override the routing via ``agent.llm_config.model_override``.
"""
from __future__ import annotations

import re
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Model tiers (configurable via environment / settings)
# ---------------------------------------------------------------------------

_GEMINI_TIERS = {
    "low":    "gemini-2.0-flash-lite",
    "medium": "gemini-2.0-flash",
    "high":   "gemini-1.5-pro",
}

_OPENAI_TIERS = {
    "low":    "gpt-4o-mini",
    "medium": "gpt-4o",
    "high":   "gpt-4o",
}

# Approximate token thresholds that trigger tier promotion
_LOW_TOKEN_LIMIT = 800
_HIGH_TOKEN_LIMIT = 4000


def _rough_token_count(text: str) -> int:
    """Very fast word-based token approximation (1 word ≈ 1.3 tokens)."""
    return int(len(text.split()) * 1.3)


def _messages_token_count(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += _rough_token_count(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    total += _rough_token_count(str(part.get("text", "")))
    return total


class ModelRouter:
    """
    Selects the appropriate LLM model for a given request.

    :param provider: "gemini" | "openai" | "vertex"
    :param settings: application settings object (for default model names)
    """

    def __init__(self, provider: str, settings: Any) -> None:
        self._provider = provider
        self._settings = settings

    def select(
        self,
        messages: list[dict],
        system_prompt: str = "",
        tool_calls_in_turn: int = 0,
        is_playbook_llm_step: bool = False,
        agent_llm_config: Optional[dict] = None,
    ) -> str:
        """
        Return the model name to use for this request.

        :param messages: conversation messages array
        :param system_prompt: system prompt string
        :param tool_calls_in_turn: number of tool calls made so far this turn
        :param is_playbook_llm_step: whether this call is from a PlaybookEngine LLMStep
        :param agent_llm_config: agent.llm_config dict (may contain overrides)
        :returns: model identifier string
        """
        config = agent_llm_config or {}

        # Tenant override always wins
        override = config.get("model_override") or config.get("model")
        if override and isinstance(override, str):
            logger.debug("model_router_override", model=override)
            return override

        complexity = self._classify(
            messages=messages,
            system_prompt=system_prompt,
            tool_calls_in_turn=tool_calls_in_turn,
            is_playbook_llm_step=is_playbook_llm_step,
            config=config,
        )

        model = self._tier_model(complexity)
        logger.debug("model_router_selected", complexity=complexity, model=model)
        return model

    # ── Internal ──────────────────────────────────────────────────────────────

    def _classify(
        self,
        messages: list[dict],
        system_prompt: str,
        tool_calls_in_turn: int,
        is_playbook_llm_step: bool,
        config: dict,
    ) -> str:
        # Explicit tier override
        explicit = config.get("complexity_tier")
        if explicit in ("low", "medium", "high"):
            return explicit

        total_tokens = _rough_token_count(system_prompt) + _messages_token_count(messages)

        if total_tokens >= _HIGH_TOKEN_LIMIT or tool_calls_in_turn >= 2:
            return "high"

        if (
            total_tokens >= _LOW_TOKEN_LIMIT
            or tool_calls_in_turn >= 1
            or is_playbook_llm_step
            or len(messages) > 10
        ):
            return "medium"

        return "low"

    def _tier_model(self, tier: str) -> str:
        if self._provider in ("gemini", "vertex"):
            return _GEMINI_TIERS.get(tier, _GEMINI_TIERS["medium"])
        if self._provider == "openai":
            return _OPENAI_TIERS.get(tier, _OPENAI_TIERS["medium"])
        # Unknown provider — return whatever the settings default is
        return getattr(self._settings, "GEMINI_MODEL", _GEMINI_TIERS["medium"])
