"""
EvalService — LLM-as-judge evaluation framework.

Scoring dimensions (each 0.0–1.0):
  relevance   — is the response on-topic and relevant to the query?
  accuracy    — is the factual content correct given expected output?
  tone        — does the response match the expected tone / rubric?
  rubric      — does the response comply with any freeform rubric?

Weighted composite: 0.1*intent_match + 0.3*tool_match + 0.3*content + 0.3*rubric
Pass threshold: composite >= 0.7

CI/CD gate: pass_rate >= 0.8 across all cases in a run.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.eval import EvalCase, EvalRun, EvalScore

logger = structlog.get_logger(__name__)

_PASS_THRESHOLD = 0.7
_GATE_PASS_RATE = 0.8

_JUDGE_SYSTEM_PROMPT = """You are an expert AI evaluator. Evaluate the assistant's response against the expected criteria.

Respond with valid JSON only — no markdown, no explanation outside the JSON.

Return:
{
  "relevance_score": <0.0-1.0>,
  "accuracy_score": <0.0-1.0>,
  "tone_score": <0.0-1.0>,
  "rubric_score": <0.0-1.0>,
  "reasoning": "<brief explanation>"
}

Scoring guide:
- relevance_score: Does the response directly address the user's question?
- accuracy_score: Is the factual content correct? Compare against expected_response_contains if provided.
- tone_score: Is the tone appropriate and professional?
- rubric_score: If a rubric is provided, how well does the response comply? Default 1.0 if no rubric.
"""


class EvalService:
    """
    Runs evaluation cases against an agent and scores them using an LLM judge.

    :param db: SQLAlchemy async session
    :param llm_client: LLM client with generate() method
    """

    def __init__(self, db: AsyncSession, llm_client: Any) -> None:
        self._db = db
        self._llm = llm_client

    # ── Public API ────────────────────────────────────────────────────────────

    async def run_eval(
        self,
        agent_id: uuid.UUID,
        tenant_id: uuid.UUID,
        prompt_version_id: Optional[str] = None,
        trigger: str = "manual",
        case_ids: Optional[list[uuid.UUID]] = None,
        agent_runner=None,
    ) -> EvalRun:
        """
        Execute an evaluation run.

        :param agent_runner: async callable (input_text, history) → (response, tools_called)
                             If None, scores are set to 0 (useful for dry-run registration).
        """
        # Fetch cases
        query = select(EvalCase).where(
            EvalCase.agent_id == agent_id,
            EvalCase.tenant_id == tenant_id,
            EvalCase.is_active.is_(True),
        )
        if case_ids:
            query = query.where(EvalCase.id.in_(case_ids))
        result = await self._db.execute(query)
        cases = result.scalars().all()

        run = EvalRun(
            tenant_id=tenant_id,
            agent_id=agent_id,
            prompt_version_id=prompt_version_id,
            trigger=trigger,
            status="running",
            total_cases=len(cases),
        )
        self._db.add(run)
        await self._db.flush()

        if not cases:
            run.status = "completed"
            run.pass_rate = 1.0
            await self._db.flush()
            return run

        scores: list[EvalScore] = []
        passed = 0

        for case in cases:
            score = await self._score_case(run=run, case=case, agent_runner=agent_runner)
            scores.append(score)
            self._db.add(score)
            if score.passed:
                passed += 1

        # Aggregate metrics
        run.passed_cases = passed
        run.failed_cases = len(cases) - passed
        run.pass_rate = passed / len(cases) if cases else 0.0
        run.avg_relevance_score = _avg(s.relevance_score for s in scores)
        run.avg_accuracy_score = _avg(s.accuracy_score for s in scores)
        run.avg_tone_score = _avg(s.tone_score for s in scores)
        run.avg_rubric_score = _avg(s.rubric_score for s in scores)
        run.avg_composite_score = _avg(s.composite_score for s in scores)
        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc)

        await self._db.flush()
        logger.info(
            "eval_run_completed",
            run_id=str(run.id),
            total=len(cases),
            passed=passed,
            pass_rate=round(run.pass_rate, 4),
        )
        return run

    async def gate_check(
        self,
        agent_id: uuid.UUID,
        tenant_id: uuid.UUID,
        prompt_version_id: Optional[str] = None,
    ) -> dict:
        """
        Return CI/CD gate result for the latest eval run for this agent.

        Used by ``GET /evals/gate`` — returns pass/fail + metrics.
        """
        query = select(EvalRun).where(
            EvalRun.agent_id == agent_id,
            EvalRun.tenant_id == tenant_id,
            EvalRun.status == "completed",
        )
        if prompt_version_id:
            query = query.where(EvalRun.prompt_version_id == prompt_version_id)
        query = query.order_by(EvalRun.completed_at.desc()).limit(1)

        result = await self._db.execute(query)
        run = result.scalar_one_or_none()

        if not run:
            return {
                "gate": "no_data",
                "pass": False,
                "message": "No completed eval run found.",
                "pass_rate": 0.0,
                "threshold": _GATE_PASS_RATE,
            }

        gate_pass = run.pass_rate >= _GATE_PASS_RATE
        return {
            "gate": "pass" if gate_pass else "fail",
            "pass": gate_pass,
            "run_id": str(run.id),
            "pass_rate": round(run.pass_rate, 4),
            "threshold": _GATE_PASS_RATE,
            "total_cases": run.total_cases,
            "passed_cases": run.passed_cases,
            "avg_composite_score": round(run.avg_composite_score, 4),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

    # ── Per-case scoring ──────────────────────────────────────────────────────

    async def _score_case(
        self,
        run: EvalRun,
        case: EvalCase,
        agent_runner,
    ) -> EvalScore:
        actual_response = ""
        actual_tools: list = []
        actual_intent: Optional[str] = None
        error_msg: Optional[str] = None

        if agent_runner:
            try:
                actual_response, actual_tools, actual_intent = await agent_runner(
                    input_text=case.input_text,
                    history=case.conversation_history or [],
                )
            except Exception as exc:
                error_msg = str(exc)
                logger.warning("eval_agent_runner_error", case_id=str(case.id), error=error_msg)

        # Compute dimension scores
        dim_scores = await self._judge(
            case=case,
            actual_response=actual_response,
            actual_tools=actual_tools,
            actual_intent=actual_intent,
        )

        # Intent match bonus
        intent_match = 0.0
        if case.expected_intent and actual_intent:
            intent_match = 1.0 if case.expected_intent.lower() == actual_intent.lower() else 0.0
        elif not case.expected_intent:
            intent_match = 1.0

        # Tool match score
        tool_match = 1.0
        if case.expected_tools:
            expected_set = set(case.expected_tools)
            actual_set = set(actual_tools)
            if expected_set:
                tool_match = len(expected_set & actual_set) / len(expected_set)

        composite = (
            0.1 * intent_match
            + 0.3 * tool_match
            + 0.3 * dim_scores["accuracy_score"]
            + 0.3 * dim_scores["rubric_score"]
        )

        passed = composite >= _PASS_THRESHOLD

        return EvalScore(
            run_id=run.id,
            case_id=case.id,
            actual_response=actual_response,
            actual_tools_called=actual_tools,
            actual_intent=actual_intent,
            relevance_score=dim_scores["relevance_score"],
            accuracy_score=dim_scores["accuracy_score"],
            tone_score=dim_scores["tone_score"],
            rubric_score=dim_scores["rubric_score"],
            composite_score=composite,
            passed=passed,
            judge_reasoning=dim_scores.get("reasoning"),
            error_message=error_msg,
        )

    async def _judge(
        self,
        case: EvalCase,
        actual_response: str,
        actual_tools: list,
        actual_intent: Optional[str],
    ) -> dict:
        """Call LLM-as-judge to score the response."""
        judge_prompt = (
            f"User input:\n{case.input_text}\n\n"
            f"Assistant response:\n{actual_response or '(no response)'}\n\n"
        )
        if case.expected_response_contains:
            judge_prompt += f"Expected response should contain:\n{case.expected_response_contains}\n\n"
        if case.rubric:
            judge_prompt += f"Scoring rubric:\n{case.rubric}\n\n"

        try:
            raw = await self._llm.generate(
                messages=[{"role": "user", "content": judge_prompt}],
                system_prompt=_JUDGE_SYSTEM_PROMPT,
                temperature=0.0,
                max_tokens=300,
            )
            # Strip markdown fences
            cleaned = re.sub(r"^```[a-z]*\n?", "", raw.strip()).rstrip("`").strip()
            scores = json.loads(cleaned)
            return {
                "relevance_score": float(scores.get("relevance_score", 0.5)),
                "accuracy_score": float(scores.get("accuracy_score", 0.5)),
                "tone_score": float(scores.get("tone_score", 0.5)),
                "rubric_score": float(scores.get("rubric_score", 1.0)),
                "reasoning": scores.get("reasoning", ""),
            }
        except Exception as exc:
            logger.warning("eval_judge_error", case_id=str(case.id), error=str(exc))
            return {
                "relevance_score": 0.0,
                "accuracy_score": 0.0,
                "tone_score": 0.0,
                "rubric_score": 0.0,
                "reasoning": f"Judge error: {exc}",
            }


def _avg(iterable) -> float:
    items = list(iterable)
    return sum(items) / len(items) if items else 0.0
