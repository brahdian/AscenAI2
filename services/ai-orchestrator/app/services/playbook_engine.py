"""
PlaybookEngine — state-machine executor for declarative playbooks.

Each call to ``advance()`` executes one step of the playbook:
- Pure steps (deterministic, condition, goto) are executed immediately.
- LLM steps call the LLM and store the result.
- Tool steps call the MCP tool executor.
- WaitInput steps pause execution and return ``awaiting_input=True``.
- End steps mark the session complete.

State is persisted:
  - Redis: ``playbook_state:{session_id}`` (24 h TTL) — fast read/write between turns
  - PostgreSQL: ``playbook_executions`` row — durable checkpoint on every step

Usage:
    engine = PlaybookEngine(redis_client, db, llm_client, mcp_client)
    result = await engine.advance(
        session_id="...",
        playbook=REFUND_PLAYBOOK,
        user_input="ORD-12345",
        tenant_id=uuid,
        agent=agent,
    )
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.playbook import (
    AnyStep,
    ConditionStep,
    DeterministicStep,
    EndStep,
    GotoStep,
    LLMStep,
    PlaybookAdvanceResult,
    PlaybookDefinition,
    PlaybookState,
    StepHistoryEntry,
    StepResult,
    ToolStep,
    WaitInputStep,
)

logger = structlog.get_logger(__name__)

# Safety guard: max steps per advance() call to prevent infinite loops
_MAX_STEPS_PER_ADVANCE = 50
# Redis TTL for playbook state (24 hours)
_STATE_TTL = 86_400


# ---------------------------------------------------------------------------
# Advance result type aliases (imported from schemas for convenience)
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redis_key(session_id: str) -> str:
    return f"playbook_state:{session_id}"


def _substitute_vars(template: str, variables: dict[str, Any]) -> str:
    """
    Replace ``{{var_name}}`` placeholders in *template* with values from *variables*.

    Supports simple dotted-path access: ``{{order_details.amount}}``
    resolves as ``variables['order_details']['amount']``.
    """
    def _resolve(match: re.Match) -> str:
        path = match.group(1).strip()
        parts = path.split(".")
        value: Any = variables
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part, "")
            else:
                value = getattr(value, part, "")
        return str(value) if value is not None else ""

    return re.sub(r"\{\{([^}]+)\}\}", _resolve, template)


def _safe_eval(expression: str, variables: dict[str, Any]) -> bool:
    """
    Evaluate a boolean expression against *variables* using simpleeval.

    simpleeval is a purpose-built restricted evaluator that only permits
    arithmetic, comparisons, boolean logic, and safe built-ins. It does NOT
    allow attribute access, subscript chains, imports, or dunder escapes —
    unlike ``eval()`` with ``__builtins__: {}``, which is NOT a safe sandbox
    (see CVE-style: str.__class__.__mro__[1].__subclasses__() chain).

    Returns False on any evaluation error (fail-closed).
    """
    try:
        from simpleeval import EvalWithCompoundTypes, FeatureNotAvailable, InvalidExpression
    except ImportError:
        logger.error(
            "simpleeval_not_installed",
            detail="Install simpleeval to enable playbook condition evaluation",
        )
        return False

    safe_names = {
        **variables,
        "True": True, "False": False, "None": None,
    }
    safe_functions = {
        "int": int, "float": float, "str": str, "bool": bool,
        "len": len, "abs": abs, "min": min, "max": max,
    }
    try:
        evaluator = EvalWithCompoundTypes(names=safe_names, functions=safe_functions)
        result = evaluator.eval(expression)
        return bool(result)
    except (FeatureNotAvailable, InvalidExpression) as exc:
        logger.warning(
            "playbook_condition_forbidden_expression",
            expression=expression,
            error=str(exc),
        )
        return False
    except Exception as exc:
        logger.warning(
            "playbook_condition_eval_error",
            expression=expression,
            error=str(exc),
        )
        return False


class PlaybookEngine:
    """
    Executes declarative playbook state machines.

    :param redis_client: async Redis client (used for state storage)
    :param db: SQLAlchemy async session (used for durable checkpoints)
    :param llm_client: LLM client that exposes ``generate()``
    :param mcp_client: MCP tool executor that exposes ``execute_tool()``
    """

    def __init__(
        self,
        redis_client: Any,
        db: AsyncSession,
        llm_client: Any,
        mcp_client: Any,
    ) -> None:
        self._redis = redis_client
        self._db = db
        self._llm = llm_client
        self._mcp = mcp_client

    # ── Public API ────────────────────────────────────────────────────────────

    async def advance(
        self,
        session_id: str,
        playbook: PlaybookDefinition,
        user_input: Optional[str],
        tenant_id: uuid.UUID,
        agent: Any,
    ) -> PlaybookAdvanceResult:
        """
        Advance the playbook by one or more steps.

        If the current step is ``wait_input`` and *user_input* is provided,
        validate it and store it, then continue executing until the next
        ``wait_input`` or ``end`` step.

        Returns a :class:`~app.schemas.playbook.PlaybookAdvanceResult` that
        the orchestrator can relay directly to the user.
        """
        # Load (or initialise) state
        state = await self._load_state(session_id)
        if state is None:
            state = PlaybookState(
                session_id=session_id,
                playbook_id=playbook.id,
                current_step_id=playbook.initial_step_id,
                created_at=_now_iso(),
                updated_at=_now_iso(),
            )

        if state.status in ("completed", "failed", "escalated"):
            return PlaybookAdvanceResult(
                session_id=session_id,
                status=state.status,
                message=f"Playbook already in terminal state: {state.status}",
                awaiting_input=False,
                completed=True,
            )

        steps_executed = 0
        last_message: str = ""
        awaiting = False

        while steps_executed < _MAX_STEPS_PER_ADVANCE:
            current_step = playbook.steps.get(state.current_step_id)
            if not current_step:
                logger.error(
                    "playbook_missing_step",
                    session_id=session_id,
                    step_id=state.current_step_id,
                )
                state.status = "failed"
                state.error_message = f"Missing step: {state.current_step_id}"
                break

            result = await self._execute_step(
                step=current_step,
                state=state,
                user_input=user_input if state.awaiting_input else None,
                agent=agent,
            )

            # Record history
            state.history.append(
                StepHistoryEntry(
                    step_id=current_step.id,
                    step_type=current_step.type,
                    executed_at=_now_iso(),
                    result_summary=result.message[:200] if result.message else None,
                    variables_snapshot=dict(state.variables),
                    error=result.error,
                )
            )
            state.step_count += 1
            steps_executed += 1

            if result.error and not result.continue_on_error:
                state.status = "failed"
                state.error_message = result.error
                last_message = f"An error occurred: {result.error}"
                break

            if result.message:
                last_message = result.message

            # Transition
            if result.terminal:
                state.status = result.terminal_status or "completed"
                state.completed_at = _now_iso()
                break

            if result.awaiting_input:
                state.awaiting_input = True
                awaiting = True
                # Prompt to user comes from the step result
                last_message = result.message or last_message
                # user_input consumed — clear for next call
                user_input = None
                break

            # Advance to next step
            if result.next_step_id:
                state.current_step_id = result.next_step_id
                state.awaiting_input = False
                user_input = None
            else:
                # No next step → treat as end
                state.status = "completed"
                state.completed_at = _now_iso()
                break

        else:
            # Loop guard hit
            logger.error("playbook_loop_guard", session_id=session_id)
            state.status = "failed"
            state.error_message = "Maximum steps exceeded — possible infinite loop"
            last_message = "I'm sorry, something went wrong processing your request."

        state.updated_at = _now_iso()

        # Persist state
        await self._save_state(state)
        await self._checkpoint_db(state, tenant_id, agent)

        return PlaybookAdvanceResult(
            session_id=session_id,
            status=state.status,
            message=last_message,
            awaiting_input=awaiting and state.status == "active",
            completed=state.status in ("completed", "failed", "escalated"),
            variables=dict(state.variables),
            step_count=state.step_count,
            current_step_id=state.current_step_id,
        )

    async def get_state(self, session_id: str) -> Optional[PlaybookState]:
        """Return the current playbook state for *session_id*, or None."""
        return await self._load_state(session_id)

    async def reset(self, session_id: str) -> None:
        """Delete state from Redis (DB row is kept for audit)."""
        await self._redis.delete(_redis_key(session_id))

    # ── Step executors ────────────────────────────────────────────────────────

    async def _execute_step(
        self,
        step: AnyStep,
        state: PlaybookState,
        user_input: Optional[str],
        agent: Any,
    ) -> StepResult:
        try:
            if isinstance(step, WaitInputStep):
                return await self._exec_wait_input(step, state, user_input)
            elif isinstance(step, DeterministicStep):
                return self._exec_deterministic(step, state)
            elif isinstance(step, ConditionStep):
                return self._exec_condition(step, state)
            elif isinstance(step, LLMStep):
                return await self._exec_llm(step, state, agent)
            elif isinstance(step, ToolStep):
                return await self._exec_tool(step, state)
            elif isinstance(step, GotoStep):
                return StepResult(next_step_id=step.target_step_id)
            elif isinstance(step, EndStep):
                return self._exec_end(step, state)
            else:
                return StepResult(
                    error=f"Unknown step type: {step.type}",
                    continue_on_error=False,
                )
        except Exception as exc:
            logger.exception(
                "playbook_step_error",
                step_id=step.id,
                step_type=step.type,
                session_id=state.session_id,
                error=str(exc),
            )
            return StepResult(
                error=str(exc),
                continue_on_error=False,
            )

    async def _exec_wait_input(
        self,
        step: WaitInputStep,
        state: PlaybookState,
        user_input: Optional[str],
    ) -> StepResult:
        prompt = _substitute_vars(step.prompt_to_user, state.variables)

        if not state.awaiting_input or user_input is None:
            # First visit — show prompt, pause
            return StepResult(
                message=prompt,
                awaiting_input=True,
                next_step_id=step.id,  # stay on this step
            )

        # User replied — validate
        raw = user_input.strip()
        if step.validation_regex:
            if not re.match(step.validation_regex, raw, re.IGNORECASE):
                error_msg = step.error_message or "Invalid input. Please try again."
                return StepResult(
                    message=error_msg,
                    awaiting_input=True,
                    next_step_id=step.id,  # retry same step
                )

        # Store value and advance
        state.variables[step.variable_to_store] = raw
        return StepResult(
            message=None,
            next_step_id=step.next_step_id,
        )

    def _exec_deterministic(
        self,
        step: DeterministicStep,
        state: PlaybookState,
    ) -> StepResult:
        if step.action == "set_variable":
            var = step.params.get("variable", "")
            value = step.params.get("value", "")
            if isinstance(value, str):
                value = _substitute_vars(value, state.variables)
            state.variables[var] = value
            return StepResult(next_step_id=step.next_step_id)

        elif step.action == "format_message":
            template = step.params.get("template", "")
            out_var = step.params.get("output_variable", "formatted_message")
            rendered = _substitute_vars(template, state.variables)
            state.variables[out_var] = rendered
            return StepResult(next_step_id=step.next_step_id)

        return StepResult(
            error=f"Unknown deterministic action: {step.action}",
            continue_on_error=False,
        )

    def _exec_condition(
        self,
        step: ConditionStep,
        state: PlaybookState,
    ) -> StepResult:
        result = _safe_eval(step.expression, state.variables)
        next_id = step.then_step_id if result else step.else_step_id
        logger.debug(
            "playbook_condition",
            step_id=step.id,
            expression=step.expression,
            result=result,
            next_step=next_id,
        )
        return StepResult(next_step_id=next_id)

    async def _exec_llm(
        self,
        step: LLMStep,
        state: PlaybookState,
        agent: Any,
    ) -> StepResult:
        prompt = _substitute_vars(step.prompt_template, state.variables)
        messages = [{"role": "user", "content": prompt}]

        raw_response = await self._llm.generate(
            messages=messages,
            system_prompt=(
                f"You are a helpful assistant following a structured workflow. "
                f"Step: {step.id}. "
                f"Respond concisely and directly."
            ),
            temperature=step.temperature,
            max_tokens=step.max_tokens,
        )

        text = raw_response.strip()

        if step.extract_json:
            try:
                # Strip markdown code fences if present
                cleaned = re.sub(r"^```[a-z]*\n?", "", text).rstrip("`").strip()
                parsed = json.loads(cleaned)
                state.variables[step.output_variable] = parsed
            except (json.JSONDecodeError, ValueError):
                # Fall back to raw text
                state.variables[step.output_variable] = text
        else:
            state.variables[step.output_variable] = text

        return StepResult(
            message=text,
            next_step_id=step.next_step_id,
        )

    async def _exec_tool(
        self,
        step: ToolStep,
        state: PlaybookState,
    ) -> StepResult:
        # Build arguments with variable substitution
        args: dict[str, Any] = {}
        for k, v in step.argument_mapping.items():
            if isinstance(v, str):
                args[k] = _substitute_vars(v, state.variables)
            else:
                args[k] = v

        last_error: Optional[str] = None
        attempts = 1
        if step.on_error == "retry":
            attempts = step.retry_attempts

        for attempt in range(1, attempts + 1):
            try:
                t0 = time.monotonic()
                result = await self._mcp.execute_tool(step.tool_name, args)
                elapsed_ms = (time.monotonic() - t0) * 1000

                logger.info(
                    "playbook_tool_executed",
                    step_id=step.id,
                    tool=step.tool_name,
                    elapsed_ms=round(elapsed_ms, 1),
                )

                if step.output_variable:
                    state.variables[step.output_variable] = (
                        result if isinstance(result, dict) else {"result": result}
                    )
                return StepResult(next_step_id=step.next_step_id)

            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "playbook_tool_error",
                    step_id=step.id,
                    tool=step.tool_name,
                    attempt=attempt,
                    error=last_error,
                )
                if attempt < attempts:
                    await asyncio.sleep(step.retry_delay_seconds * attempt)

        # All attempts exhausted
        if step.on_error == "continue" or (
            step.on_error == "retry" and step.on_retry_exhausted == "continue"
        ):
            if step.output_variable:
                state.variables[step.output_variable] = {"error": last_error}
            return StepResult(
                error=last_error,
                continue_on_error=True,
                next_step_id=step.next_step_id,
            )

        return StepResult(
            error=last_error,
            continue_on_error=False,
        )

    def _exec_end(
        self,
        step: EndStep,
        state: PlaybookState,
    ) -> StepResult:
        message = _substitute_vars(step.final_message_template, state.variables)
        state.variables["_final_message"] = message
        return StepResult(
            message=message,
            terminal=True,
            terminal_status=step.status,
        )

    # ── State persistence ─────────────────────────────────────────────────────

    async def _load_state(self, session_id: str) -> Optional[PlaybookState]:
        try:
            raw = await self._redis.get(_redis_key(session_id))
            if raw:
                return PlaybookState.model_validate_json(raw)
        except Exception as exc:
            logger.warning("playbook_state_load_error", session_id=session_id, error=str(exc))
        return None

    async def _save_state(self, state: PlaybookState) -> None:
        try:
            await self._redis.set(
                _redis_key(state.session_id),
                state.model_dump_json(),
                ex=_STATE_TTL,
            )
        except Exception as exc:
            logger.error("playbook_state_save_error", session_id=state.session_id, error=str(exc))

    async def _checkpoint_db(
        self,
        state: PlaybookState,
        tenant_id: uuid.UUID,
        agent: Any,
    ) -> None:
        """Upsert a PlaybookExecution row in PostgreSQL."""
        try:
            from app.models.agent import PlaybookExecution

            result = await self._db.execute(
                select(PlaybookExecution).where(
                    PlaybookExecution.session_id == state.session_id,
                    PlaybookExecution.playbook_id == state.playbook_id,
                )
            )
            execution = result.scalar_one_or_none()

            if execution is None:
                execution = PlaybookExecution(
                    session_id=state.session_id,
                    playbook_id=state.playbook_id,
                    tenant_id=tenant_id,
                    agent_id=agent.id,
                    status=state.status,
                    current_step_id=state.current_step_id,
                    variables=state.variables,
                    history=[h.model_dump() for h in state.history],
                    step_count=state.step_count,
                    error_message=state.error_message,
                )
                self._db.add(execution)
            else:
                execution.status = state.status
                execution.current_step_id = state.current_step_id
                execution.variables = state.variables
                execution.history = [h.model_dump() for h in state.history]
                execution.step_count = state.step_count
                execution.error_message = state.error_message
                if state.completed_at:
                    execution.completed_at = datetime.fromisoformat(state.completed_at)

            await self._db.flush()
        except Exception as exc:
            logger.error(
                "playbook_checkpoint_error",
                session_id=state.session_id,
                error=str(exc),
            )
