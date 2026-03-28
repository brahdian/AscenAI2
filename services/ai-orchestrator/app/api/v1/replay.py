"""
Conversation replay API.

Endpoints:
  GET  /sessions/{session_id}/replay          — list all turns with summaries
  GET  /sessions/{session_id}/replay/{turn}   — full detail for one turn
  GET  /sessions/{session_id}/replay/{turn}/why — human-readable explanation
"""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Session as AgentSession
from app.models.trace import ConversationTrace

logger = structlog.get_logger(__name__)
router = APIRouter()


def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


async def _verify_session(session_id: str, tenant_id: str, db: AsyncSession) -> AgentSession:
    result = await db.execute(
        select(AgentSession).where(
            AgentSession.id == session_id,
            AgentSession.tenant_id == uuid.UUID(tenant_id),
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session


@router.get("/sessions/{session_id}/replay")
async def list_replay_turns(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    List all conversation turns for replay.

    Returns a summary of each turn: user message, tools called,
    guardrail actions, response excerpt, and latency breakdown.
    """
    tenant_id = _tenant_id(request)
    await _verify_session(session_id, tenant_id, db)

    result = await db.execute(
        select(ConversationTrace)
        .where(
            ConversationTrace.session_id == session_id,
            ConversationTrace.tenant_id == uuid.UUID(tenant_id),
        )
        .order_by(ConversationTrace.turn_index.asc())
    )
    traces = result.scalars().all()

    return {
        "session_id": session_id,
        "total_turns": len(traces),
        "turns": [t.to_summary_dict() for t in traces],
    }


@router.get("/sessions/{session_id}/replay/{turn_index}")
async def get_replay_turn(
    session_id: str,
    turn_index: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Full detail for a single conversation turn.

    Returns the complete artifact: system prompt, memory snapshot,
    retrieved chunks, messages sent to LLM, raw LLM response,
    tool calls, guardrail actions, final response, and latency breakdown.
    """
    tenant_id = _tenant_id(request)
    await _verify_session(session_id, tenant_id, db)

    result = await db.execute(
        select(ConversationTrace).where(
            ConversationTrace.session_id == session_id,
            ConversationTrace.tenant_id == uuid.UUID(tenant_id),
            ConversationTrace.turn_index == turn_index,
        )
    )
    trace = result.scalar_one_or_none()
    if not trace:
        raise HTTPException(status_code=404, detail=f"Turn {turn_index} not found.")

    return trace.to_full_dict()


@router.get("/sessions/{session_id}/replay/{turn_index}/why")
async def explain_turn(
    session_id: str,
    turn_index: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Human-readable explanation of why the agent responded as it did.

    Synthesizes the trace artifacts into a plain-English summary covering:
    - Which system prompt / prompt version was active
    - What memory context was loaded
    - How many knowledge base chunks were retrieved (and their top score)
    - What tools were called and why
    - Which guardrail actions fired
    - What PII entity types were detected
    - Latency breakdown
    """
    tenant_id = _tenant_id(request)
    await _verify_session(session_id, tenant_id, db)

    result = await db.execute(
        select(ConversationTrace).where(
            ConversationTrace.session_id == session_id,
            ConversationTrace.tenant_id == uuid.UUID(tenant_id),
            ConversationTrace.turn_index == turn_index,
        )
    )
    trace = result.scalar_one_or_none()
    if not trace:
        raise HTTPException(status_code=404, detail=f"Turn {turn_index} not found.")

    explanation_parts: list[str] = []

    # Prompt
    pv = trace.prompt_version_id or "agent default"
    prompt_excerpt = (trace.system_prompt or "")[:200].replace("\n", " ")
    explanation_parts.append(
        f"**System Prompt** (version: {pv}): \"{prompt_excerpt}...\""
        if len(trace.system_prompt or "") > 200
        else f"**System Prompt** (version: {pv}): \"{prompt_excerpt}\""
    )

    # Memory
    mem = trace.memory_snapshot or {}
    short_term_count = len(mem.get("short_term", []))
    has_summary = bool(mem.get("summary"))
    ltm_keys = len(mem.get("long_term", {}))
    explanation_parts.append(
        f"**Memory**: {short_term_count} short-term turns loaded"
        + (", conversation summary present" if has_summary else "")
        + (f", {ltm_keys} long-term facts" if ltm_keys else "")
    )

    # Knowledge base
    chunks = trace.retrieved_chunks or []
    if chunks:
        top_score = max((c.get("score", 0) for c in chunks), default=0)
        explanation_parts.append(
            f"**Knowledge Base**: {len(chunks)} chunks retrieved "
            f"(top score: {top_score:.3f})"
            + (" — grounding prompt injected" if trace.grounding_used else "")
        )
    else:
        explanation_parts.append("**Knowledge Base**: No chunks retrieved.")

    # Tools
    tool_calls = trace.tool_calls or []
    if tool_calls:
        tool_names = [tc.get("tool", "unknown") for tc in tool_calls]
        total_tool_ms = sum(tc.get("latency_ms", 0) for tc in tool_calls)
        explanation_parts.append(
            f"**Tools Called**: {', '.join(tool_names)} "
            f"(total {total_tool_ms:.0f} ms)"
        )
    else:
        explanation_parts.append("**Tools**: No tools were called.")

    # Guardrails
    actions = trace.guardrail_actions or []
    if actions:
        explanation_parts.append(f"**Guardrail Actions**: {', '.join(actions)}")
    else:
        explanation_parts.append("**Guardrails**: No guardrail actions triggered.")

    # PII
    pii_types = trace.pii_entity_types or []
    if pii_types:
        explanation_parts.append(
            f"**PII Detected**: {', '.join(pii_types)} "
            f"(pseudonymized before LLM call)"
        )

    # Input guardrail check
    if trace.guardrail_input_check:
        explanation_parts.append(
            f"**Input Guardrail Block**: {trace.guardrail_input_check}"
        )

    # Latency
    latency = trace.latency_breakdown or {}
    if latency:
        breakdown_str = ", ".join(
            f"{k.replace('_ms', '')}: {v:.0f} ms"
            for k, v in sorted(latency.items())
        )
        explanation_parts.append(f"**Latency**: {breakdown_str}")

    # LLM
    explanation_parts.append(
        f"**LLM**: {trace.llm_provider} / {trace.llm_model}, "
        f"{trace.tokens_used} tokens used"
    )

    return {
        "session_id": session_id,
        "turn_index": turn_index,
        "explanation": "\n\n".join(explanation_parts),
        "trace_id": str(trace.id),
        "final_response": trace.final_response,
    }
