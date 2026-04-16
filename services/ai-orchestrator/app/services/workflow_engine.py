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
from app.schemas.workflow import (
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

    return re.sub(r"\{\{([^}]+)\}\}", _replace, str(template))


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
            NodeType.INPUT:         self._exec_input,
            NodeType.SET_VARIABLE:  self._exec_set_variable,
            NodeType.VALIDATION:    self._exec_validation,
            NodeType.CONDITION:     self._exec_condition,
            NodeType.SWITCH:        self._exec_switch,
            NodeType.FOR_EACH:      self._exec_for_each,
            NodeType.TOOL_CALL:     self._exec_tool_call,
            NodeType.LLM_CALL:      self._exec_llm_call,
            NodeType.ACTION:        self._exec_action,
            NodeType.SEND_SMS:      self._exec_send_sms,
            NodeType.DELAY:         self._exec_delay,
            NodeType.HUMAN_HANDOFF: self._exec_human_handoff,
            NodeType.END:           self._exec_end,
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
        stmt = pg_insert(WorkflowStepExecution).values(
            id=uuid.uuid4(),
            execution_id=execution.id,
            node_id=node.id,
            node_type=node.type.value,
            status=status,
            input_snapshot=input_snapshot,
            output_snapshot=output_snapshot,
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
        idem = idempotency_key or f"{execution.id}:{event_type}:{_utcnow().timestamp()}"
        stmt = pg_insert(WorkflowEvent).values(
            id=uuid.uuid4(),
            execution_id=execution.id,
            event_type=event_type,
            payload=payload,
            actor=actor,
            idempotency_key=idem,
            created_at=_utcnow(),
        ).on_conflict_do_nothing(index_elements=["idempotency_key"])
        await self.db.execute(stmt)
