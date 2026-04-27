"""General-purpose workflow execution engine.

Core loop
---------
WorkflowEngine.advance(execution_id, user_input, event_payload)
  1. Load execution (SELECT FOR UPDATE — prevents concurrent advance)
  2. Load workflow definition → WorkflowDefinition
  3. Walk nodes until AWAITING_INPUT, AWAITING_EVENT, or terminal state
  4. Checkpoint after every node (idempotent via step_executions)
  5. Return WorkflowAdvanceResult

Idempotency
-----------
Every node execution writes a WorkflowStepExecution row with
idempotency_key = "{execution_id}:{node_id}". Before executing a node:
  - If a COMPLETED row already exists for that key, skip and return cached output.
This makes every node safe to re-run on crash/replay.

Node dispatch table
-------------------
INPUT          — collect user variable (two-pass: show prompt / receive input)
SET_VARIABLE   — assign/transform context variable
VALIDATION     — validate var against regex; branch yes/no
CONDITION      — evaluate boolean expression; branch yes/no
TOOL_CALL      — call MCP tool via mcp_client; store output in context
LLM_CALL       — call LLM with prompt template; store result in context
ACTION         — HTTP POST to external endpoint
SEND_SMS       — fire SMS via SMSWorkflowEngine; optionally await reply
DELAY          — set AWAITING_EVENT with TTL; expiry worker re-advances
HUMAN_HANDOFF  — escalate session (sets status COMPLETED + message)
END            — terminal; emit final_message
"""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import structlog
import shared.pii as pii_service
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import (
    ExecutionStatus,
    StepStatus,
    WorkflowEvent,
    WorkflowExecution,
    WorkflowStepExecution,
)
from app.models.workflow import Workflow
from .schemas.workflow import (
    NodeResult,
    NodeType,
    WorkflowAdvanceResult,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
)

logger = structlog.get_logger(__name__)

# Maximum nodes to process in a single advance() call — prevents infinite loops
_MAX_STEPS = 50
# Maximum sub-workflow recursion depth to prevent infinite call chains
_MAX_CALL_DEPTH = 5
# Redis key prefix for WAIT_FOR_SIGNAL correlation
_SIGNAL_KEY_PREFIX = "wf:signal:"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _substitute_vars(template: str, context: dict) -> str:
    """Replace {{variable}} patterns with values from context.

    Handles nested dict access via dot notation: {{booking_result.status}}
    """
    def _replace(match: re.Match) -> str:
        key = match.group(1).strip()
        parts = key.split(".")
        val: Any = context
        for part in parts:
            if isinstance(val, dict):
                val = val.get(part, match.group(0))
            else:
                return match.group(0)
        return str(val) if val != match.group(0) else match.group(0)

    # FIX-04: Apply PII scrubbing to the final substituted string for defense-in-depth
    return pii_service.redact(re.sub(r"\{\{([^}]+)\}\}", _replace, str(template)))


def _resolve_template_dict(d: dict, context: dict) -> dict:
    """Recursively substitute {{vars}} in all string values of a dict."""
    result = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = _substitute_vars(v, context)
        elif isinstance(v, dict):
            result[k] = _resolve_template_dict(v, context)
        else:
            result[k] = v
    return result


def _eval_expression(expr: str, context: dict) -> bool:
    """Evaluate a simple boolean expression against context.

    Uses simpleeval for safe expression evaluation.
    Falls back to False on any error to fail safely.
    """
    try:
        from simpleeval import simple_eval
        return bool(simple_eval(
            expr,
            names=dict(context),
            functions={
                "int": int,
                "float": float,
                "str": str,
                "bool": bool,
                "len": len,
            }
        ))
    except Exception as exc:
        logger.warning("workflow_expression_eval_failed", expr=expr, error=str(exc))
        return False


class WorkflowNotFoundError(Exception):
    pass


class ExecutionNotFoundError(Exception):
    pass


class WorkflowEngine:
    """Advances a WorkflowExecution through the DAG node by node."""

    def __init__(
        self,
        db: AsyncSession,
        mcp_client=None,
        llm_client=None,
        redis=None,
    ) -> None:
        self.db = db
        self.mcp_client = mcp_client
        self._llm_client = llm_client
        self._redis = redis

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_execution(
        self,
        workflow_id: uuid.UUID,
        session_id: str,
        tenant_id: uuid.UUID,
        initial_context: dict,
        customer_phone: str = "",
    ) -> WorkflowExecution:
        """Create a new WorkflowExecution at the workflow's entry node."""
        wf = await self.db.scalar(
            select(Workflow).where(Workflow.id == workflow_id)
        )
        if not wf:
            raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")

        definition = WorkflowDefinition.model_validate(wf.definition)

        # Merge initial context with workflow-level variable defaults
        context = {**definition.variables, **initial_context}

        execution = WorkflowExecution(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            session_id=session_id,
            customer_phone=customer_phone,
            current_node_id=definition.entry_node_id,
            status=ExecutionStatus.RUNNING,
            context=context,
            history=[],
        )
        self.db.add(execution)
        await self.db.flush()

        await self._record_event(
            execution=execution,
            event_type="EXECUTION_CREATED",
            payload={"workflow_id": str(workflow_id), "entry_node_id": definition.entry_node_id},
        )
        return execution

    async def advance(
        self,
        execution_id: uuid.UUID,
        user_input: Optional[str] = None,
        event_payload: Optional[dict] = None,
    ) -> WorkflowAdvanceResult:
        """Advance a workflow execution by one or more steps.

        - Loads execution with row lock to prevent concurrent advances
        - Processes nodes until AWAITING_INPUT, AWAITING_EVENT, or terminal
        - Persists state after every node
        """
        # SELECT FOR UPDATE — prevents concurrent advance() on same execution
        result = await self.db.execute(
            select(WorkflowExecution)
            .where(WorkflowExecution.id == execution_id)
            .with_for_update()
        )
        execution = result.scalar_one_or_none()
        if not execution:
            raise ExecutionNotFoundError(f"Execution {execution_id} not found")

        # If already terminal, return current state
        if execution.status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.EXPIRED):
            return WorkflowAdvanceResult(
                execution_id=execution.id,
                status=execution.status,
                completed=True,
                context=execution.context,
                current_node_id=execution.current_node_id,
            )

        was_terminal = False  # Track if we transition to terminal in this run

        # Load workflow definition
        wf = await self.db.scalar(
            select(Workflow).where(Workflow.id == execution.workflow_id)
        )
        if not wf:
            raise WorkflowNotFoundError(f"Workflow {execution.workflow_id} not found")

        definition = WorkflowDefinition.model_validate(wf.definition)
        node_map = {n.id: n for n in definition.nodes}
        edge_map: dict[str, list[WorkflowEdge]] = {}
        for edge in definition.edges:
            edge_map.setdefault(edge.source, []).append(edge)

        # Resume AWAITING_INPUT / AWAITING_EVENT states
        if execution.status in (ExecutionStatus.AWAITING_INPUT, ExecutionStatus.AWAITING_EVENT):
            execution.status = ExecutionStatus.RUNNING
            if event_payload:
                execution.context = {**execution.context, **event_payload}

        last_message: Optional[str] = None
        steps_taken = 0
        MAX_EXECUTION_DURATION = timedelta(hours=24)
        
        # Enforce maximum execution duration
        if _utcnow() - execution.created_at > MAX_EXECUTION_DURATION:
            logger.error("workflow_max_duration_exceeded", execution_id=str(execution_id))
            execution.status = ExecutionStatus.FAILED
            execution.error_message = "Execution exceeded maximum allowed duration (24 hours)"
            await self._checkpoint(execution)
            return WorkflowAdvanceResult(
                execution_id=execution.id,
                status=execution.status,
                completed=True,
                context=execution.context,
                current_node_id=execution.current_node_id,
            )

        while steps_taken < _MAX_STEPS:
            if execution.status != ExecutionStatus.RUNNING:
                break

            node_id = execution.current_node_id
            if not node_id or node_id not in node_map:
                # No more nodes — completed
                await self._complete(execution)
                break

            node = node_map[node_id]
            steps_taken += 1

            try:
                node_result = await self._execute_node(
                    node=node,
                    execution=execution,
                    definition=definition,
                    edge_map=edge_map,
                    user_input=user_input,
                )
            except Exception as exc:
                logger.error(
                    "workflow_node_error",
                    execution_id=str(execution_id),
                    node_id=node_id,
                    error=str(exc),
                )
                execution.status = ExecutionStatus.FAILED
                execution.error_message = f"Node {node_id} ({node.type}): {exc}"
                await self._record_event(
                    execution=execution,
                    event_type="EXECUTION_FAILED",
                    payload={"node_id": node_id, "error": str(exc)},
                )
                break

            # Merge node outputs into context
            if node_result.output:
                execution.context = {**execution.context, **node_result.output}
                # Guard against runaway context growth (1 MB limit)
                import json as _json
                if len(_json.dumps(execution.context)) > 1_000_000:
                    execution.status = ExecutionStatus.FAILED
                    execution.error_message = "Execution context exceeded 1 MB limit"
                    await self._checkpoint(execution)
                    break

            if node_result.message:
                last_message = node_result.message

            # user_input is consumed on first AWAITING_INPUT resumption
            user_input = None

            if node_result.awaiting_input:
                execution.status = ExecutionStatus.AWAITING_INPUT
                execution.current_node_id = node_id  # stay on this node
                await self._checkpoint(execution)
                break

            if node_result.awaiting_event:
                execution.status = ExecutionStatus.AWAITING_EVENT
                execution.current_node_id = node_id
                if node_result.event_ttl_seconds:
                    execution.expiry_time = _utcnow() + timedelta(seconds=node_result.event_ttl_seconds)
                await self._checkpoint(execution)
                break

            # Advance to next node (or None if no outgoing edge)
            execution.current_node_id = node_result.next_node_id
            if node_result.next_node_id is None:
                await self._complete(execution)
                break

            await self._checkpoint(execution)

        if steps_taken >= _MAX_STEPS and execution.status == ExecutionStatus.RUNNING:
            logger.error("workflow_max_steps_exceeded", execution_id=str(execution_id))
            execution.status = ExecutionStatus.FAILED
            execution.error_message = f"Exceeded maximum step limit ({_MAX_STEPS})"
            await self._checkpoint(execution)

        is_terminal = execution.status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.EXPIRED)
        
        # ---------------------------------------------------------------------
        # Asynchronous Promise Resolution (Sub-Workflow Wakeup)
        # ---------------------------------------------------------------------
        if not was_terminal and is_terminal and execution.parent_execution_id:
            logger.debug(
                "workflow_promise_resolve_trigger", 
                child_id=str(execution.id), 
                parent_id=str(execution.parent_execution_id),
                status=execution.status.value,
            )
            # DEADLOCK AVOIDANCE: The parent execution row might currently be locked 
            # by its own `advance` transaction (especially in PARALLEL branches). 
            # We spawn a background process with a slight delay and a fresh 
            # Database Session to gracefully "poke" the parent and trigger re-entry.
            from app.core.database import AsyncSessionLocal
            import asyncio

            async def _wake_parent(parent_id: uuid.UUID):
                await asyncio.sleep(0.5)  # Allow child transaction to fully commit
                async with AsyncSessionLocal() as parent_db:
                    try:
                        wake_engine = WorkflowEngine(db=parent_db, redis=self._redis)
                        await wake_engine.advance(execution_id=parent_id)
                        await parent_db.commit()
                    except Exception as exc:
                        await parent_db.rollback()
                        logger.error("promise_resolve_wakeup_failed", parent_id=str(parent_id), error=str(exc))
                        
            task = asyncio.create_task(_wake_parent(execution.parent_execution_id))
            # Optional: maintain reference to avoid garbage collection
            self._bg_tasks = getattr(self, "_bg_tasks", set())
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)

        return WorkflowAdvanceResult(
            execution_id=execution.id,
            status=execution.status,
            message=last_message,
            awaiting_input=execution.status == ExecutionStatus.AWAITING_INPUT,
            completed=execution.status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.EXPIRED),
            context=execution.context,
            current_node_id=execution.current_node_id,
            error=execution.error_message,
        )

    # ------------------------------------------------------------------
    # Node dispatchers
    # ------------------------------------------------------------------

    async def _execute_node(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        definition: WorkflowDefinition,
        edge_map: dict[str, list[WorkflowEdge]],
        user_input: Optional[str],
    ) -> NodeResult:
        """Check idempotency cache, then dispatch to node-type handler."""
        # FOR_EACH visits the same node_id on every iteration — include the
        # iteration counter so each loop pass gets its own idempotency slot.
        if node.type == NodeType.FOR_EACH:
            iteration = int(execution.context.get(f"_foreach_{node.id}_index", 0))
            idem_key = f"{execution.id}:{node.id}:{iteration}"
        else:
            idem_key = f"{execution.id}:{node.id}"

        # Check for a previously completed step (crash replay safety)
        existing = await self.db.scalar(
            select(WorkflowStepExecution).where(
                WorkflowStepExecution.idempotency_key == idem_key,
                WorkflowStepExecution.status == StepStatus.COMPLETED,
            )
        )
        if existing:
            logger.debug("workflow_node_idempotent_skip", node_id=node.id, idem_key=idem_key)
            next_node = self._resolve_next(edge_map, node.id, "default")
            return NodeResult(
                output=existing.output_snapshot,
                next_node_id=next_node,
            )

        dispatchers = {
            NodeType.INPUT:           self._exec_input,
            NodeType.SET_VARIABLE:    self._exec_set_variable,
            NodeType.VALIDATION:      self._exec_validation,
            NodeType.CONDITION:       self._exec_condition,
            NodeType.SWITCH:          self._exec_switch,
            NodeType.FOR_EACH:        self._exec_for_each,
            NodeType.TOOL_CALL:       self._exec_tool_call,
            NodeType.LLM_CALL:        self._exec_llm_call,
            NodeType.ACTION:          self._exec_action,
            NodeType.SEND_SMS:        self._exec_send_sms,
            NodeType.DELAY:           self._exec_delay,
            NodeType.HUMAN_HANDOFF:   self._exec_human_handoff,
            NodeType.END:             self._exec_end,
            # ── Orchestrator nodes ──
            NodeType.CALL_WORKFLOW:   self._exec_call_workflow,
            NodeType.PARALLEL:        self._exec_parallel,
            NodeType.WAIT_FOR_SIGNAL: self._exec_wait_for_signal,
            NodeType.CODE_EXEC:       self._exec_code_exec,
        }
        handler = dispatchers.get(node.type)
        if not handler:
            raise ValueError(f"Unknown node type: {node.type}")

        start_ms = int(time.monotonic() * 1000)
        await self._record_event(
            execution=execution,
            event_type="NODE_STARTED",
            payload={"node_id": node.id, "node_type": node.type},
        )

        result = await handler(node, execution, edge_map, user_input)

        duration_ms = int(time.monotonic() * 1000) - start_ms
        await self._persist_step(
            execution=execution,
            node=node,
            status=StepStatus.COMPLETED,
            input_snapshot={"user_input": user_input},
            output_snapshot=result.output,
            duration_ms=duration_ms,
            idem_key=idem_key,
        )
        await self._record_event(
            execution=execution,
            event_type="NODE_COMPLETED",
            payload={
                "node_id": node.id,
                "node_type": node.type,
                "duration_ms": duration_ms,
                "awaiting_input": result.awaiting_input,
                "awaiting_event": result.awaiting_event,
            },
        )
        return result

    # -- INPUT ----------------------------------------------------------------

    async def _exec_input(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        edge_map: dict,
        user_input: Optional[str],
    ) -> NodeResult:
        """Two-pass node: first pass returns prompt, second pass stores input."""
        cfg = node.config
        variable = cfg.get("variable", "input")
        prompt = _substitute_vars(cfg.get("prompt", ""), execution.context)

        if user_input is None:
            # First pass: surface prompt to user and pause
            return NodeResult(
                message=prompt,
                awaiting_input=True,
            )

        # Second pass: validate and store
        validation_regex = cfg.get("validation_regex")
        if validation_regex:
            if not re.fullmatch(validation_regex, user_input.strip()):
                error_msg = cfg.get("error_message", f"Invalid input. Please try again.\n\n{prompt}")
                return NodeResult(
                    message=_substitute_vars(error_msg, execution.context),
                    awaiting_input=True,
                )

        return NodeResult(
            output={variable: user_input},
            next_node_id=self._resolve_next(edge_map, node.id, "default"),
        )

    # -- SET_VARIABLE ---------------------------------------------------------

    async def _exec_set_variable(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        edge_map: dict,
        user_input: Optional[str],
    ) -> NodeResult:
        cfg = node.config
        variable = cfg.get("variable", "result")
        value = _substitute_vars(str(cfg.get("value", "")), execution.context)
        return NodeResult(
            output={variable: value},
            next_node_id=self._resolve_next(edge_map, node.id, "default"),
        )

    # -- VALIDATION -----------------------------------------------------------

    async def _exec_validation(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        edge_map: dict,
        user_input: Optional[str],
    ) -> NodeResult:
        cfg = node.config
        variable = cfg.get("variable", "")
        value = str(execution.context.get(variable, ""))
        pattern = cfg.get("regex", ".*")
        passed = bool(re.fullmatch(pattern, value))
        handle = "yes" if passed else "no"
        return NodeResult(
            output={"_validation_passed": passed},
            next_node_id=self._resolve_next(edge_map, node.id, handle),
        )

    # -- CONDITION ------------------------------------------------------------

    async def _exec_condition(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        edge_map: dict,
        user_input: Optional[str],
    ) -> NodeResult:
        cfg = node.config
        expression = cfg.get("expression", "False")
        result_bool = _eval_expression(expression, execution.context)
        handle = "yes" if result_bool else "no"
        return NodeResult(
            output={"_condition_result": result_bool},
            next_node_id=self._resolve_next(edge_map, node.id, handle),
        )

    # -- SWITCH ---------------------------------------------------------------

    async def _exec_switch(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        edge_map: dict,
        user_input: Optional[str],
    ) -> NodeResult:
        """N-way branch based on a variable value (match/case style).

        Config
        ------
        variable      : context key to match against
        cases         : [{"value": "book", "handle": "book"},
                         {"value": "cancel", "handle": "cancel"}]
        default_handle: edge handle used when no case matches (default: "default")

        Edge convention — edges out of a SWITCH node use source_handle = the
        case "handle" string, e.g. "book", "cancel", "reschedule", "default".
        """
        cfg = node.config
        variable = cfg.get("variable", "")
        value = str(execution.context.get(variable, "")).strip().lower()
        cases: list[dict] = cfg.get("cases", [])
        default_handle: str = cfg.get("default_handle", "default")

        matched_handle = default_handle
        for case in cases:
            case_value = str(case.get("value", "")).strip().lower()
            # Support exact match, list-of-values, or simple regex
            case_match = case.get("match", "exact")
            if case_match == "exact" and value == case_value:
                matched_handle = case["handle"]
                break
            elif case_match == "contains" and case_value in value:
                matched_handle = case["handle"]
                break
            elif case_match == "regex":
                if re.search(case_value, value):
                    matched_handle = case["handle"]
                    break

        return NodeResult(
            output={"_switch_matched": matched_handle},
            next_node_id=self._resolve_next(edge_map, node.id, matched_handle),
        )

    # -- FOR_EACH -------------------------------------------------------------

    async def _exec_for_each(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        edge_map: dict,
        user_input: Optional[str],
    ) -> NodeResult:
        """Iterate over a list stored in context; run body nodes per item.

        Config
        ------
        items_variable  : context key that holds the list to iterate
        item_variable   : context key to inject per-iteration (default: "item")
        index_variable  : context key to inject iteration index (default: "loop_index")
        body_entry_node : first node ID of the loop body (must be in same workflow)
        max_iterations  : safety cap (default: 50)

        Execution model
        ---------------
        FOR_EACH is a meta-node: on each call it pops the next item off a
        internal queue stored in context["_foreach_{node_id}_queue"], injects
        item + index into context, and routes to body_entry_node. When the
        queue is empty it routes to the "done" handle (post-loop edge).

        The loop body eventually routes back to this FOR_EACH node via a
        "loop_back" edge, which re-enters the handler for the next iteration.
        This creates a cycle: FOR_EACH → body → ... → FOR_EACH → done.

        Example edges:
          {source: "for_each_1", target: "send_sms", source_handle: "body"}
          {source: "for_each_1", target: "summarise", source_handle: "done"}
        """
        cfg = node.config
        items_variable  = cfg.get("items_variable", "items")
        item_variable   = cfg.get("item_variable", "item")
        index_variable  = cfg.get("index_variable", "loop_index")
        max_iterations  = int(cfg.get("max_iterations", 50))

        queue_key   = f"_foreach_{node.id}_queue"
        counter_key = f"_foreach_{node.id}_index"

        # Initialise queue on first entry (queue_key not yet in context)
        if queue_key not in execution.context:
            items = execution.context.get(items_variable, [])
            if not isinstance(items, list):
                # Gracefully handle non-list (wrap scalar in list)
                items = [items] if items else []
            # Cap iterations for safety
            items = items[:max_iterations]
            execution.context = {
                **execution.context,
                queue_key:   list(items),   # mutable copy
                counter_key: 0,
            }

        queue: list = list(execution.context.get(queue_key, []))
        index: int  = int(execution.context.get(counter_key, 0))

        if not queue:
            # Queue exhausted — route to "done" handle
            cleanup = {queue_key: [], counter_key: 0}
            return NodeResult(
                output=cleanup,
                next_node_id=self._resolve_next(edge_map, node.id, "done"),
            )

        # Pop next item and inject into context
        current_item = queue.pop(0)
        updates = {
            queue_key:    queue,
            counter_key:  index + 1,
            item_variable:  current_item,
            index_variable: index,
        }
        return NodeResult(
            output=updates,
            next_node_id=self._resolve_next(edge_map, node.id, "body"),
        )

    # -- TOOL_CALL ------------------------------------------------------------

    async def _exec_tool_call(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        edge_map: dict,
        user_input: Optional[str],
    ) -> NodeResult:
        cfg = node.config
        tool_name = cfg.get("tool_name", "")
        output_variable = cfg.get("output_variable", "tool_result")
        argument_mapping = cfg.get("argument_mapping", {})
        retry_attempts = int(cfg.get("retry_attempts", 1))
        on_error = cfg.get("on_error", "fail")  # "fail" | "retry" | "skip"

        # Resolve argument templates
        resolved_args = _resolve_template_dict(argument_mapping, execution.context)

        last_error: Optional[Exception] = None
        for attempt in range(max(retry_attempts, 1)):
            try:
                if self.mcp_client is None:
                    raise RuntimeError("MCP client not available in workflow engine")
                result = await self.mcp_client.call_tool(tool_name, resolved_args)
                return NodeResult(
                    output={output_variable: result},
                    next_node_id=self._resolve_next(edge_map, node.id, "default"),
                )
            except Exception as exc:
                last_error = exc
                if attempt < retry_attempts - 1:
                    await asyncio.sleep(min(2 ** attempt, 8))

        if on_error == "skip":
            return NodeResult(
                output={output_variable: None},
                next_node_id=self._resolve_next(edge_map, node.id, "default"),
            )
        raise last_error or RuntimeError(f"Tool call '{tool_name}' failed")

    # -- LLM_CALL -------------------------------------------------------------

    async def _exec_llm_call(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        edge_map: dict,
        user_input: Optional[str],
    ) -> NodeResult:
        cfg = node.config
        prompt_template = cfg.get("prompt_template", "")
        output_variable = cfg.get("output_variable", "llm_result")
        extract_json = cfg.get("extract_json", False)

        system_prompt = _substitute_vars(cfg.get("system_prompt", ""), execution.context)
        prompt = _substitute_vars(prompt_template, execution.context)
        model = cfg.get("model")
        temperature = float(cfg.get("temperature", 0.7))
        max_tokens = int(cfg.get("max_tokens", 1000))

        if self._llm_client is None:
            raise RuntimeError("LLM client not injected into WorkflowEngine")

        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await self._llm_client.complete(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                session_id=execution.session_id,
            )
            # LLMResponse has a .content attribute (or .text); fall back gracefully
            raw = getattr(response, "content", None) or getattr(response, "text", str(response))
            output_value = raw
            if extract_json:
                import json
                try:
                    output_value = json.loads(raw)
                except Exception:
                    output_value = raw
        except Exception as exc:
            raise RuntimeError(f"LLM call failed: {exc}") from exc

        return NodeResult(
            output={output_variable: output_value},
            next_node_id=self._resolve_next(edge_map, node.id, "default"),
        )

    # -- ACTION ---------------------------------------------------------------

    async def _exec_action(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        edge_map: dict,
        user_input: Optional[str],
    ) -> NodeResult:
        cfg = node.config
        url = _substitute_vars(cfg.get("url", ""), execution.context)
        method = cfg.get("method", "POST").upper()
        headers = _resolve_template_dict(cfg.get("headers", {}), execution.context)
        body = _resolve_template_dict(cfg.get("body", {}), execution.context)
        output_variable = cfg.get("output_variable", "action_result")
        timeout = float(cfg.get("timeout_seconds", 10))

        from app.utils.security import is_safe_url
        if not is_safe_url(url):
            raise RuntimeError(f"ACTION node blocked: unsafe or non-HTTPS URL '{url}'")

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, url, headers=headers, json=body)
            resp.raise_for_status()
            try:
                result = resp.json()
            except Exception:
                result = resp.text

        return NodeResult(
            output={output_variable: result},
            next_node_id=self._resolve_next(edge_map, node.id, "default"),
        )

    # -- SEND_SMS -------------------------------------------------------------

    async def _exec_send_sms(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        edge_map: dict,
        user_input: Optional[str],
    ) -> NodeResult:
        cfg = node.config
        to_phone = _substitute_vars(cfg.get("to", ""), execution.context)
        message = _substitute_vars(cfg.get("message", ""), execution.context)
        await_reply = cfg.get("await_reply", False)
        reply_ttl_seconds = int(cfg.get("reply_ttl_seconds", 900))

        # Send SMS via mcp_client (routes to Twilio tool in mcp-server).
        # Fire-and-forget — failures are warned but do not abort the workflow.
        try:
            if self.mcp_client is not None:
                await self.mcp_client.call_tool("send_sms", {"to": to_phone, "message": message})
            else:
                logger.warning("workflow_sms_no_client", node_id=node.id, to=to_phone)
        except Exception as exc:
            logger.warning("workflow_sms_failed", node_id=node.id, error=str(exc))
            if cfg.get("on_error") == "fail":
                raise RuntimeError(f"SEND_SMS failed: {exc}")

        await self._record_event(
            execution=execution,
            event_type="SMS_SENT",
            payload={"to": to_phone, "message_len": len(message)},
        )

        if await_reply:
            # Store phone → execution mapping so the SMS reply handler can resume
            if self._redis is not None and to_phone:
                from app.workers.workflow_trigger_worker import store_phone_execution
                await store_phone_execution(
                    self._redis,
                    to_phone,
                    str(execution.id),
                    ttl_seconds=reply_ttl_seconds,
                )
            return NodeResult(
                awaiting_event=True,
                event_ttl_seconds=reply_ttl_seconds,
                next_node_id=self._resolve_next(edge_map, node.id, "default"),
            )

        return NodeResult(
            next_node_id=self._resolve_next(edge_map, node.id, "default"),
        )

    # -- DELAY ----------------------------------------------------------------

    async def _exec_delay(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        edge_map: dict,
        user_input: Optional[str],
    ) -> NodeResult:
        cfg = node.config
        delay_seconds = int(cfg.get("seconds", 60))
        return NodeResult(
            awaiting_event=True,
            event_ttl_seconds=delay_seconds,
            next_node_id=self._resolve_next(edge_map, node.id, "default"),
        )

    # -- HUMAN_HANDOFF --------------------------------------------------------

    async def _exec_human_handoff(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        edge_map: dict,
        user_input: Optional[str],
    ) -> NodeResult:
        cfg = node.config
        message = _substitute_vars(
            cfg.get("message", "Transferring you to a human agent. Please hold."),
            execution.context,
        )
        # Escalation is recorded; the execution completes so the session can proceed
        await self._record_event(
            execution=execution,
            event_type="HUMAN_HANDOFF_REQUESTED",
            payload={"message": message},
        )
        # Return None next_node_id — engine will call _complete()
        return NodeResult(message=message, next_node_id=None)

    # -- END ------------------------------------------------------------------

    async def _exec_end(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        edge_map: dict,
        user_input: Optional[str],
    ) -> NodeResult:
        cfg = node.config
        final_message = _substitute_vars(
            cfg.get("final_message", ""), execution.context
        )
        return NodeResult(message=final_message, next_node_id=None)

    # ==========================================================================
    # ORCHESTRATOR NODES
    # ==========================================================================

    # -- CALL_WORKFLOW ---------------------------------------------------------

    async def _exec_call_workflow(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        edge_map: dict,
        user_input: Optional[str],
    ) -> NodeResult:
        """Run another workflow as a sub-flow and block until it reaches a terminal
        state or requires user input (which is then bubbled to the parent).

        Config
        ------
        workflow_id        : UUID of the workflow to call (required)
        input_mapping      : {target_context_key: "{{source_var}}"} — maps parent
                             context vars into the child's initial context
        output_mapping     : {parent_context_key: child_context_key} — merges
                             child outputs back into the parent context
        output_variable    : single key to store the child's full context dict
        inherit_context    : bool (default False) — if True, copy entire parent
                             context into child as the initial context

        Recursion safety
        ----------------
        The call depth is tracked via execution.context["_call_depth"] (int).
        If depth ≮ _MAX_CALL_DEPTH the node raises to avoid infinite loops.
        """
        # -------------------------------------------------------------
        # Re-entry check: are we resuming from an asynchronous pause?
        # -------------------------------------------------------------
        child_ref_key = f"_child_{node.id}"
        existing_child_id_str = execution.context.get(child_ref_key)
        
        if existing_child_id_str:
            child_exec = await self.db.scalar(
                select(WorkflowExecution).where(WorkflowExecution.id == uuid.UUID(existing_child_id_str))
            )
            if not child_exec:
                raise RuntimeError(f"CALL_WORKFLOW resumed but child {existing_child_id_str} not found")
                
            # If child is still waiting, the parent must go back to sleep.
            # (Usually this re-entry means the child woke us up because it completed,
            # but we must verify strictly for correctness).
            if child_exec.status not in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.EXPIRED):
                return NodeResult(
                    awaiting_event=child_exec.status == ExecutionStatus.AWAITING_EVENT,
                    awaiting_input=child_exec.status == ExecutionStatus.AWAITING_INPUT,
                    next_node_id=node.id,  # stay on this node
                    output={},
                )
            
            # The child has finished. Evaluate its current terminal state to get the final context.
            child_result = await self.advance(execution_id=child_exec.id)
            
        else:
            # ---------------------------------------------------------
            # First invocation: create and launch child workflow
            # ---------------------------------------------------------
            current_depth = int(execution.context.get("_call_depth", 0))
            if current_depth >= _MAX_CALL_DEPTH:
                raise RuntimeError(f"CALL_WORKFLOW recursion limit reached ({_MAX_CALL_DEPTH}).")

            cfg = node.config
            raw_wf_id = cfg.get("workflow_id", "")
            if not raw_wf_id:
                raise ValueError("CALL_WORKFLOW node requires 'workflow_id' in config")
    
            try:
                child_wf_id = uuid.UUID(raw_wf_id)
            except ValueError:
                raise ValueError(f"CALL_WORKFLOW: invalid workflow_id UUID '{raw_wf_id}'")
    
            # Build child initial context from input_mapping
            input_mapping: dict = cfg.get("input_mapping", {})
            child_initial: dict = {}
            if cfg.get("inherit_context", False):
                child_initial = {k: v for k, v in execution.context.items() if not k.startswith("_")}
            for child_key, template in input_mapping.items():
                child_initial[child_key] = _substitute_vars(str(template), execution.context)
    
            # Pass recursion depth into child
            child_initial["_call_depth"] = current_depth + 1
    
            # Create child execution
            child_exec = await self.create_execution(
                workflow_id=child_wf_id,
                session_id=execution.session_id or "",
                tenant_id=execution.tenant_id,
                initial_context=child_initial,
                customer_phone=execution.customer_phone,
            )
            
            # Critical link for asynchronous wakeup:
            child_exec.parent_execution_id = execution.id
            child_exec.trigger_source = "sub_workflow"
            await self.db.flush()
    
            await self._record_event(
                execution=execution,
                event_type="CALL_WORKFLOW_STARTED",
                payload={
                    "child_workflow_id": str(child_wf_id),
                    "child_execution_id": str(child_exec.id),
                },
            )
    
            # Advance child. If it needs input or an event, it will return early.
            child_result = await self.advance(
                execution_id=child_exec.id,
                user_input=user_input,
            )

        # -------------------------------------------------------------
        # Evaluate child_result (used by both init and re-entry paths)
        # -------------------------------------------------------------
        if not child_result.completed:
            return NodeResult(
                message=child_result.message,
                awaiting_input=child_result.awaiting_input,
                awaiting_event=child_result.status == ExecutionStatus.AWAITING_EVENT,
                next_node_id=node.id,  # Stay on this node, we are now paused
                output={child_ref_key: str(child_exec.id)},
            )

        # Child completed — merge outputs back into parent context
        output_mapping: dict = cfg.get("output_mapping", {})
        output_variable: str = cfg.get("output_variable", "")
        
        # Clear the internal tracking key since we're advancing
        merged: dict = {child_ref_key: None} 

        child_ctx = child_result.context or {}
        public_child = {k: v for k, v in child_ctx.items() if not k.startswith("_")}

        if output_variable:
            merged[output_variable] = public_child
        for parent_key, child_key in output_mapping.items():
            if child_key in child_ctx:
                merged[parent_key] = child_ctx[child_key]

        await self._record_event(
            execution=execution,
            event_type="CALL_WORKFLOW_COMPLETED",
            payload={
                "child_execution_id": str(child_exec.id),
                "child_status": child_result.status.value,
                "output_keys": list([k for k in merged.keys() if k != child_ref_key]),
            },
        )

        return NodeResult(
            output=merged,
            message=child_result.message,
            next_node_id=self._resolve_next(edge_map, node.id, "default"),
        )

    # -- PARALLEL -------------------------------------------------------------

    async def _exec_parallel(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        edge_map: dict,
        user_input: Optional[str],
    ) -> NodeResult:
        """Fan-out: create N isolated sub-executions concurrently, then join.

        Config
        ------
        branches           : list of {workflow_id, input_mapping, output_variable}
                             Each branch is a separate workflow invocation.
        join_output_key    : context key where the list of all branch results
                             is stored (default: "parallel_results")
        fail_fast          : bool (default True) — if any branch fails, mark
                             the whole PARALLEL node as failed

        Design
        ------
        All branches are launched concurrently via asyncio.gather. Each branch
        uses CALL_WORKFLOW semantics internally (child executions, depth guard).
        User input is NOT supported inside parallel branches — only autonomous
        (non-INPUT) nodes should be used as branch workflows.
        """
        cfg = node.config
        branches: list[dict] = cfg.get("branches", [])
        join_key: str = cfg.get("join_output_key", "parallel_results")
        fail_fast: bool = cfg.get("fail_fast", True)

        if not branches:
            return NodeResult(
                output={join_key: []},
                next_node_id=self._resolve_next(edge_map, node.id, "default"),
            )

        parallel_ref_key = f"_parallel_{node.id}"
        existing_branch_ids = execution.context.get(parallel_ref_key)

        from app.core.database import AsyncSessionLocal

        if existing_branch_ids is not None:
            # -------------------------------------------------------------
            # JOIN PHASE (Re-entry after waking up from branch completion)
            # -------------------------------------------------------------
            branch_execs = await self.db.scalars(
                select(WorkflowExecution).where(
                    WorkflowExecution.id.in_([uuid.UUID(uid) for uid in existing_branch_ids])
                )
            )
            branch_map = {str(b.id): b for b in branch_execs}
            
            # Check if any branch is still running or waiting
            still_pending = any(
                b.status not in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.EXPIRED)
                for b in branch_map.values()
            )
            
            if still_pending:
                # Branches are still evaluating, stay asleep
                return NodeResult(
                    awaiting_event=True,
                    next_node_id=node.id,
                    output={},
                 )
                 
            # All branches have officially completed! Maintain original order.
            results_list = []
            for branch_cfg, uid in zip(branches, existing_branch_ids):
                b_exec = branch_map[uid]
                out_var = branch_cfg.get("output_variable", "branch_result")
                public_ctx = {k: v for k, v in (b_exec.context or {}).items() if not k.startswith("_")}
                results_list.append({
                    "workflow_id": branch_cfg.get("workflow_id", ""),
                    "execution_id": uid,
                    "status": b_exec.status.value,
                    "error": b_exec.error_message,
                    out_var: public_ctx
                })

            if fail_fast and any(r.get("status") == "failed" for r in results_list):
                 failed = [r for r in results_list if r.get("status") == "failed"]
                 raise RuntimeError(f"PARALLEL: {len(failed)} branch(es) failed: {[f.get('error') for f in failed]}")

            await self._record_event(
                execution=execution,
                event_type="PARALLEL_COMPLETED",
                payload={"branch_count": len(branches), "results": results_list},
            )
            
            return NodeResult(
                output={join_key: results_list, parallel_ref_key: None},
                next_node_id=self._resolve_next(edge_map, node.id, "default"),
            )

        else:
            # -------------------------------------------------------------
            # FORK PHASE (Initial Invocation)
            # -------------------------------------------------------------
            current_depth = int(execution.context.get("_call_depth", 0))
            if current_depth >= _MAX_CALL_DEPTH:
                raise RuntimeError(f"PARALLEL recursion limit reached ({_MAX_CALL_DEPTH}).")
    
            # Bounding semaphore: strictly limit concurrent DB connections to avoid pool exhaustion
            sem = asyncio.Semaphore(5)
    
            async def _run_branch(branch_cfg: dict) -> str:
                async with sem:
                    raw_id = branch_cfg.get("workflow_id", "")
                    try:
                        branch_wf_id = uuid.UUID(raw_id)
                    except ValueError:
                        return None
        
                    input_mapping = branch_cfg.get("input_mapping", {})
                    child_initial: dict = {"_call_depth": current_depth + 1}
                    for child_key, tpl in input_mapping.items():
                        child_initial[child_key] = _substitute_vars(str(tpl), execution.context)
        
                    # Each branch evaluates in a completely isolated database transaction session
                    async with AsyncSessionLocal() as branch_db:
                        try:
                            branch_engine = WorkflowEngine(
                                db=branch_db,
                                mcp_client=self.mcp_client,
                                llm_client=self._llm_client,
                                redis=self._redis,
                            )
                            child_exec = await branch_engine.create_execution(
                                workflow_id=branch_wf_id,
                                session_id=execution.session_id or "",
                                tenant_id=execution.tenant_id,
                                initial_context=child_initial,
                            )
                            child_exec.parent_execution_id = execution.id
                            child_exec.trigger_source = "sub_workflow"
                            await branch_db.flush()
                            child_id = str(child_exec.id)
            
                            # Advance the branch dynamically. Wait for it to hit AWAITING_EVENT or terminal.
                            await branch_engine.advance(execution_id=child_exec.id)
                            await branch_db.commit()
                            return child_id
                        except Exception as exc:
                            await branch_db.rollback()
                            logger.error("parallel_branch_start_error", error=str(exc))
                            return None
    
            tasks = [_run_branch(b) for b in branches]
            results: list[str] = await asyncio.gather(*tasks, return_exceptions=False)
            
            # Immediately enter AWAITING_EVENT, pausing the parent flow and saving the spawned IDs in context.
            # As each child natively completes, its detached `_wake_parent` loop will wake this system up
            # safely without deadlock.
            valid_ids = [rid for rid in results if rid is not None]
            
            await self._record_event(
                execution=execution,
                event_type="PARALLEL_STARTED",
                payload={"launched_branches": len(valid_ids)},
            )
            
            return NodeResult(
                awaiting_event=True, 
                next_node_id=node.id, 
                output={parallel_ref_key: valid_ids}
            )

    # -- WAIT_FOR_SIGNAL -------------------------------------------------------

    async def _exec_wait_for_signal(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        edge_map: dict,
        user_input: Optional[str],
    ) -> NodeResult:
        """Pause the workflow until an external HTTP signal arrives.

        Config
        ------
        signal_name        : str (required) — logical name, e.g. "payment_confirmed"
        correlation_id_key : str (default "session_id") — context key whose value
                             uniquely identifies this execution to the signal sender
        ttl_seconds        : int (default 3600) — max wait time
        output_variable    : str — where to store the signal payload

        Resume flow
        -----------
        The signal API endpoint (POST /internal/workflows/signal/{signal_name})
        looks up the execution_id in Redis by signal_name + correlation_id,
        merges the signal payload into event_payload, then calls advance().

        Redis key: wf:signal:{signal_name}:{correlation_value} → execution_id
        """
        cfg = node.config
        signal_name: str = cfg.get("signal_name", "")
        if not signal_name:
            raise ValueError("WAIT_FOR_SIGNAL requires 'signal_name' in config")

        ttl_seconds: int = int(cfg.get("ttl_seconds", 3600))
        correlation_key: str = cfg.get("correlation_id_key", "session_id")
        correlation_value: str = str(execution.context.get(correlation_key, execution.session_id or ""))
        output_variable: str = cfg.get("output_variable", "signal_payload")

        # If event_payload is present this is the RESUME call (signal already delivered)
        # The output_variable will have been set via event_payload before advance()
        if output_variable in execution.context:
            return NodeResult(
                output={},  # already in context from event_payload merge
                next_node_id=self._resolve_next(edge_map, node.id, "default"),
            )

        # First visit: register in Redis and pause
        redis_key = f"{_SIGNAL_KEY_PREFIX}{signal_name}:{correlation_value}"
        if self._redis is not None:
            await self._redis.set(
                redis_key,
                str(execution.id),
                ex=ttl_seconds,
            )

        # Store signal_name on the execution row so the API can query it
        execution.signal_name = signal_name

        await self._record_event(
            execution=execution,
            event_type="AWAITING_SIGNAL",
            payload={
                "signal_name": signal_name,
                "correlation_key": correlation_key,
                "correlation_value": correlation_value,
                "redis_key": redis_key,
            },
        )

        return NodeResult(
            awaiting_event=True,
            event_ttl_seconds=ttl_seconds,
            next_node_id=node.id,  # stay on this node until signal arrives
        )

    # -- CODE_EXEC ------------------------------------------------------------

    async def _exec_code_exec(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        edge_map: dict,
        user_input: Optional[str],
    ) -> NodeResult:
        cfg = node.config
        expression = cfg.get("expression", "False")
        output_variable = cfg.get("output_variable", "code_result")
        on_error = cfg.get("on_error", "fail")

        try:
            from simpleeval import EvalWithCompoundTypes
            import json as _json

            safe_names = {
                **execution.context,
                "True": True, "False": False, "None": None,
                "json": _json,
            }
            safe_functions = {
                "int": int, "float": float, "str": str, "bool": bool,
                "len": len, "abs": abs, "min": min, "max": max,
                "round": round, "sorted": sorted, "list": list,
                "dict": dict, "sum": sum, "any": any, "all": all,
            }
            evaluator = EvalWithCompoundTypes(
                names=safe_names,
                functions=safe_functions,
            )
            result = evaluator.eval(expression)
            return NodeResult(
                output={output_variable: result},
                next_node_id=self._resolve_next(edge_map, node.id, "default"),
            )
        except Exception as exc:
            logger.warning(
                "workflow_code_exec_error",
                node_id=node.id,
                expr=expression[:200],
                error=str(exc),
            )
            if on_error == "skip":
                return NodeResult(
                    output={output_variable: None},
                    next_node_id=self._resolve_next(edge_map, node.id, "default"),
                )
            raise RuntimeError(f"CODE_EXEC failed: {exc}") from exc


    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_next(
        self,
        edge_map: dict[str, list[WorkflowEdge]],
        node_id: str,
        handle: str = "default",
    ) -> Optional[str]:
        """Return the target node ID for the given source node and handle."""
        edges = edge_map.get(node_id, [])
        # Prefer exact handle match; fall back to "default"
        for edge in edges:
            if edge.source_handle == handle:
                return edge.target
        for edge in edges:
            if edge.source_handle == "default":
                return edge.target
        # No outgoing edge — end of flow
        return None

    async def _complete(self, execution: WorkflowExecution) -> None:
        execution.status = ExecutionStatus.COMPLETED
        execution.completed_at = _utcnow()
        await self._record_event(
            execution=execution,
            event_type="EXECUTION_COMPLETED",
            payload={},
        )
        await self._checkpoint(execution)

    async def _scrub_pii_recursive(self, data: Any, secret_keys: set[str]) -> Any:
        """Recursively redact values for keys identified as secrets or matching PII patterns."""
        if isinstance(data, dict):
            scrubbed = {}
            for k, v in data.items():
                if k.lower() in secret_keys or any(word in k.lower() for word in ["password", "secret", "token", "cvv", "ssn"]):
                    scrubbed[k] = "[REDACTED]"
                else:
                    scrubbed[k] = await self._scrub_pii_recursive(v, secret_keys)
            return scrubbed
        elif isinstance(data, list):
            return [await self._scrub_pii_recursive(x, secret_keys) for x in data]
        elif isinstance(data, str):
            import shared.pii as pii_service
            return pii_service.redact(data)
        return data

    async def _get_secret_keys(self, execution: WorkflowExecution) -> set[str]:
        """Fetch names of all variables marked as 'is_secret' for this agent."""
        from app.models.variable import AgentVariable
        from sqlalchemy import select
        stmt = select(AgentVariable.name).where(
            AgentVariable.agent_id == execution.workflow.agent_id,
            AgentVariable.is_secret == True
        )
        result = await self.db.execute(stmt)
        return {r[0].lower() for r in result.all()}

    async def _checkpoint(self, execution: WorkflowExecution) -> None:
        """Flush execution state to the DB."""
        execution.updated_at = _utcnow()
        await self.db.flush()

    async def _persist_step(
        self,
        execution: WorkflowExecution,
        node: WorkflowNode,
        status: StepStatus,
        input_snapshot: dict,
        output_snapshot: dict,
        duration_ms: int,
        idem_key: str,
    ) -> None:
        secret_keys = await self._get_secret_keys(execution)
        safe_input = await self._scrub_pii_recursive(input_snapshot, secret_keys)
        safe_output = await self._scrub_pii_recursive(output_snapshot, secret_keys)

        stmt = pg_insert(WorkflowStepExecution).values(
            id=uuid.uuid4(),
            execution_id=execution.id,
            node_id=node.id,
            node_type=node.type.value,
            status=status,
            input_snapshot=safe_input,
            output_snapshot=safe_output,
            duration_ms=duration_ms,
            idempotency_key=idem_key,
            started_at=_utcnow(),
            completed_at=_utcnow(),
        ).on_conflict_do_nothing(index_elements=["idempotency_key"])
        await self.db.execute(stmt)

    async def _record_event(
        self,
        execution: WorkflowExecution,
        event_type: str,
        payload: dict,
        actor: str = "system",
        idempotency_key: Optional[str] = None,
    ) -> None:
        secret_keys = await self._get_secret_keys(execution)
        safe_payload = await self._scrub_pii_recursive(payload, secret_keys)

        idem = idempotency_key or f"{execution.id}:{event_type}:{_utcnow().timestamp()}"
        stmt = pg_insert(WorkflowEvent).values(
            id=uuid.uuid4(),
            execution_id=execution.id,
            event_type=event_type,
            payload=safe_payload,
            actor=actor,
            idempotency_key=idem,
            created_at=_utcnow(),
        ).on_conflict_do_nothing(index_elements=["idempotency_key"])
        await self.db.execute(stmt)
