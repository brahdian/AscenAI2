"""
Evaluation framework API.

Endpoints:
  POST /agents/{agent_id}/evals/cases         — create an eval case
  GET  /agents/{agent_id}/evals/cases         — list eval cases
  PUT  /agents/{agent_id}/evals/cases/{id}    — update a case
  DELETE /agents/{agent_id}/evals/cases/{id}  — delete a case

  POST /agents/{agent_id}/evals/runs          — trigger an eval run
  GET  /agents/{agent_id}/evals/runs          — list eval runs
  GET  /agents/{agent_id}/evals/runs/{run_id} — get run detail + scores
  GET  /agents/{agent_id}/evals/gate          — CI/CD gate endpoint
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Agent
from app.models.eval import EvalCase, EvalRun, EvalScore
from shared.orchestration.eval_service import EvalService

logger = structlog.get_logger(__name__)
router = APIRouter()


def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


def _restricted_agent_id(request: Request) -> uuid.UUID | None:
    """Extract optional agent restriction passed by the API Gateway proxy."""
    raid = request.headers.get("X-Restricted-Agent-ID")
    if raid:
        try:
            return uuid.UUID(raid)
        except ValueError:
            return None
    return None


async def _verify_agent(agent_id: str, tenant_id: str, db: AsyncSession, request: Request | None = None) -> Agent:
    agent_uuid = uuid.UUID(agent_id)
    
    # Apply isolation (CRIT-005)
    if request:
        raid = _restricted_agent_id(request)
        if raid and agent_uuid != raid:
            raise HTTPException(status_code=404, detail="Agent not found.")

    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_uuid,
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return agent


# ── Request schemas ───────────────────────────────────────────────────────────

class EvalCaseCreate(BaseModel):
    input_text: str = Field(..., min_length=1)
    conversation_history: list = Field(default_factory=list)
    expected_intent: Optional[str] = None
    expected_tools: list[str] = Field(default_factory=list)
    expected_response_contains: Optional[str] = None
    rubric: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    description: Optional[str] = None


class EvalRunCreate(BaseModel):
    prompt_version_id: Optional[str] = None
    trigger: str = Field(default="manual")
    case_ids: Optional[list[uuid.UUID]] = None


# ── Case CRUD ────────────────────────────────────────────────────────────────

@router.post("/{agent_id}/evals/cases", status_code=201)
async def create_eval_case(
    agent_id: str,
    body: EvalCaseCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_id(request)
    agent = await _verify_agent(agent_id, tenant_id, db, request)

    case = EvalCase(
        tenant_id=agent.tenant_id,
        agent_id=agent.id,
        input_text=body.input_text,
        conversation_history=body.conversation_history,
        expected_intent=body.expected_intent,
        expected_tools=body.expected_tools,
        expected_response_contains=body.expected_response_contains,
        rubric=body.rubric,
        tags=body.tags,
        description=body.description,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    logger.info("eval_case_created", agent_id=agent_id, case_id=str(case.id))
    return case.to_dict()


@router.get("/{agent_id}/evals/cases")
async def list_eval_cases(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db, request)

    result = await db.execute(
        select(EvalCase)
        .where(
            EvalCase.agent_id == uuid.UUID(agent_id),
            EvalCase.tenant_id == uuid.UUID(tenant_id),
        )
        .order_by(EvalCase.created_at.desc())
    )
    return [c.to_dict() for c in result.scalars().all()]


@router.put("/{agent_id}/evals/cases/{case_id}")
async def update_eval_case(
    agent_id: str,
    case_id: str,
    body: EvalCaseCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db, request)

    result = await db.execute(
        select(EvalCase).where(
            EvalCase.id == uuid.UUID(case_id),
            EvalCase.agent_id == uuid.UUID(agent_id),
        )
    )
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Eval case not found.")

    case.input_text = body.input_text
    case.conversation_history = body.conversation_history
    case.expected_intent = body.expected_intent
    case.expected_tools = body.expected_tools
    case.expected_response_contains = body.expected_response_contains
    case.rubric = body.rubric
    case.tags = body.tags
    case.description = body.description

    await db.commit()
    await db.refresh(case)
    return case.to_dict()


@router.delete("/{agent_id}/evals/cases/{case_id}", status_code=204)
async def delete_eval_case(
    agent_id: str,
    case_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db, request)

    result = await db.execute(
        select(EvalCase).where(
            EvalCase.id == uuid.UUID(case_id),
            EvalCase.agent_id == uuid.UUID(agent_id),
        )
    )
    case = result.scalar_one_or_none()
    if case:
        await db.delete(case)
        await db.commit()


# ── Run management ───────────────────────────────────────────────────────────

@router.post("/{agent_id}/evals/runs", status_code=201)
async def trigger_eval_run(
    agent_id: str,
    body: EvalRunCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Trigger an evaluation run (scores without an agent runner — registers the run)."""
    tenant_id = _tenant_id(request)
    agent = await _verify_agent(agent_id, tenant_id, db, request)

    svc = EvalService(db=db, llm_client=None)
    run = await svc.run_eval(
        agent_id=agent.id,
        tenant_id=agent.tenant_id,
        prompt_version_id=body.prompt_version_id,
        trigger=body.trigger,
        case_ids=body.case_ids,
        agent_runner=None,
    )
    await db.commit()
    logger.info("eval_run_triggered", agent_id=agent_id, run_id=str(run.id))
    return run.to_dict()


@router.get("/{agent_id}/evals/runs")
async def list_eval_runs(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db, request)

    result = await db.execute(
        select(EvalRun)
        .where(
            EvalRun.agent_id == uuid.UUID(agent_id),
            EvalRun.tenant_id == uuid.UUID(tenant_id),
        )
        .order_by(EvalRun.created_at.desc())
        .limit(50)
    )
    return [r.to_dict() for r in result.scalars().all()]


@router.get("/{agent_id}/evals/runs/{run_id}")
async def get_eval_run(
    agent_id: str,
    run_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db, request)

    result = await db.execute(
        select(EvalRun).where(
            EvalRun.id == uuid.UUID(run_id),
            EvalRun.agent_id == uuid.UUID(agent_id),
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Eval run not found.")

    # Include per-case scores
    scores_result = await db.execute(
        select(EvalScore).where(EvalScore.run_id == run.id).order_by(EvalScore.created_at.asc())
    )
    scores = scores_result.scalars().all()

    return {
        **run.to_dict(),
        "scores": [s.to_dict() for s in scores],
    }


@router.get("/{agent_id}/evals/gate")
async def eval_gate(
    agent_id: str,
    request: Request,
    prompt_version_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    CI/CD gate endpoint.

    Returns ``{"gate": "pass", "pass": true}`` if the latest completed eval
    run for this agent meets the 0.8 pass-rate threshold.
    Returns HTTP 200 in both cases; CI scripts should check ``"pass"`` field.
    """
    tenant_id = _tenant_id(request)
    agent = await _verify_agent(agent_id, tenant_id, db, request)

    svc = EvalService(db=db, llm_client=None)
    return await svc.gate_check(
        agent_id=agent.id,
        tenant_id=agent.tenant_id,
        prompt_version_id=prompt_version_id,
    )
