"""Pydantic schemas for the general-purpose workflow engine.

Used for:
- Validating workflow definitions stored in JSONB
- API request/response serialization (workflows.py)
- WorkflowEngine internal contracts
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Node types
# ---------------------------------------------------------------------------

class NodeType(str, enum.Enum):
    INPUT          = "INPUT"           # Prompt user, collect variable
    SET_VARIABLE   = "SET_VARIABLE"    # Assign/transform a variable
    VALIDATION     = "VALIDATION"      # Validate var against rule; branch pass/fail
    CONDITION      = "CONDITION"       # Boolean if/else branch
    SWITCH         = "SWITCH"          # N-way branch on variable value (like match/case)
    FOR_EACH       = "FOR_EACH"        # Iterate over a list; run body nodes per item
    TOOL_CALL      = "TOOL_CALL"       # Execute any registered MCP tool
    LLM_CALL       = "LLM_CALL"        # Call LLM with prompt template
    ACTION         = "ACTION"          # HTTP API call to external endpoint
    SEND_SMS       = "SEND_SMS"        # Fire SMS (optionally await reply)
    DELAY          = "DELAY"           # Wait N seconds before next node
    HUMAN_HANDOFF  = "HUMAN_HANDOFF"   # Escalate session to human agent
    END            = "END"             # Terminal — emit final message
    # ── Orchestrator nodes ────────────────────────────────────────────
    CALL_WORKFLOW   = "CALL_WORKFLOW"  # Run another workflow as a sub-flow and await its result
    PARALLEL        = "PARALLEL"       # Fan-out: run multiple node chains concurrently, then join
    WAIT_FOR_SIGNAL = "WAIT_FOR_SIGNAL" # Pause until an external webhook/event delivers a named signal
    CODE_EXEC       = "CODE_EXEC"      # Safe Python expression evaluation for data transformation


# ---------------------------------------------------------------------------
# Node / Edge definitions (the "program" stored in Workflow.definition)
# ---------------------------------------------------------------------------

class WorkflowNode(BaseModel):
    id: str = Field(..., description="Unique node identifier within this workflow")
    type: NodeType
    label: str = ""
    # {x, y} position for drag-and-drop UI — ignored by the engine
    position: dict = Field(default_factory=dict)
    # Node-type-specific configuration (prompts, tool names, expressions, etc.)
    config: dict = Field(default_factory=dict)
    # JSON Schema fragments (informational; engine uses config directly)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)


class WorkflowEdge(BaseModel):
    id: str
    source: str = Field(..., description="Source node id")
    target: str = Field(..., description="Target node id")
    # "default" for normal flow; "yes"/"no" for CONDITION/VALIDATION nodes
    source_handle: str = "default"
    label: str = ""


class WorkflowDefinition(BaseModel):
    """The full DAG stored in Workflow.definition JSONB."""
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    entry_node_id: str
    # Initial context variables seeded before execution starts
    variables: dict = Field(default_factory=dict)

    @field_validator("nodes")
    @classmethod
    def nodes_not_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("Workflow must have at least one node")
        return v

    @field_validator("entry_node_id")
    @classmethod
    def entry_node_exists(cls, v: str, info) -> str:
        nodes = info.data.get("nodes", [])
        node_ids = {n.id for n in nodes}
        if nodes and v not in node_ids:
            raise ValueError(f"entry_node_id '{v}' not found in nodes")
        return v

    @field_validator("definition")
    @classmethod
    def validate_no_cycles(cls, v: WorkflowDefinition) -> WorkflowDefinition:
        """Validate workflow graph contains no cycles"""
        node_ids = {n.id for n in v.nodes}
        edge_map: dict[str, list[str]] = {}
        
        for edge in v.edges:
            if edge.source not in node_ids:
                raise ValueError(f"Edge source '{edge.source}' not found in nodes")
            if edge.target not in node_ids:
                raise ValueError(f"Edge target '{edge.target}' not found in nodes")
            edge_map.setdefault(edge.source, []).append(edge.target)
        
        visited = set()
        recursion_stack = set()
        
        def has_cycle(node_id: str) -> bool:
            visited.add(node_id)
            recursion_stack.add(node_id)
            
            for neighbor in edge_map.get(node_id, []):
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in recursion_stack:
                    return True
            
            recursion_stack.remove(node_id)
            return False
        
        if has_cycle(v.entry_node_id):
            raise ValueError("Workflow graph contains a cycle which would cause infinite execution")
        
        return v


# ---------------------------------------------------------------------------
# Execution status
# ---------------------------------------------------------------------------

class ExecutionStatusEnum(str, enum.Enum):
    RUNNING          = "RUNNING"
    AWAITING_INPUT   = "AWAITING_INPUT"
    AWAITING_EVENT   = "AWAITING_EVENT"
    COMPLETED        = "COMPLETED"
    FAILED           = "FAILED"
    EXPIRED          = "EXPIRED"


# ---------------------------------------------------------------------------
# API request / response schemas
# ---------------------------------------------------------------------------

class WorkflowCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: str = ""
    definition: WorkflowDefinition
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    trigger_type: str = Field(
        default="none",
        description="none | cron | webhook | event",
    )
    trigger_config: dict = Field(default_factory=dict)


class WorkflowUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    definition: Optional[WorkflowDefinition] = None
    input_schema: Optional[dict] = None
    output_schema: Optional[dict] = None
    tags: Optional[list[str]] = None
    trigger_type: Optional[str] = None
    trigger_config: Optional[dict] = None


class WorkflowResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str
    trigger_type: str
    trigger_config: dict
    is_active: bool
    version: int
    definition: dict
    input_schema: dict
    output_schema: dict
    tags: list
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowAdvanceRequest(BaseModel):
    """Body for POST /workflows/{flow_id}/advance — resume a paused execution."""
    session_id: str
    user_input: Optional[str] = None
    event_payload: Optional[dict] = None


class WorkflowAdvanceResult(BaseModel):
    """Returned by WorkflowEngine.advance() and the advance API endpoint."""
    execution_id: uuid.UUID
    status: ExecutionStatusEnum
    # Message to show the user (from INPUT/END node prompts)
    message: Optional[str] = None
    awaiting_input: bool = False
    completed: bool = False
    context: dict = Field(default_factory=dict)
    current_node_id: Optional[str] = None
    error: Optional[str] = None


class WorkflowExecutionResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    session_id: Optional[str]
    status: str
    current_node_id: Optional[str]
    context: dict
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Internal engine contracts
# ---------------------------------------------------------------------------

class NodeResult(BaseModel):
    """What each node executor returns to the engine."""
    # Output variables to merge into execution.context
    output: dict = Field(default_factory=dict)
    # ID of the next node to execute; None = end of flow
    next_node_id: Optional[str] = None
    # Message to surface to the user (INPUT / END nodes)
    message: Optional[str] = None
    # If True the engine pauses and waits for user_input on the next advance()
    awaiting_input: bool = False
    # If True the engine pauses and waits for an external event (webhook, delay, signal)
    awaiting_event: bool = False
    # TTL for AWAITING_EVENT (seconds from now); used by DELAY and SEND_SMS nodes
    event_ttl_seconds: Optional[int] = None
    # PARALLEL: list of branch entry node IDs to execute concurrently
    parallel_branches: list[str] = Field(default_factory=list)
    # WAIT_FOR_SIGNAL: correlation key stored so the signal endpoint can resume this execution
    signal_correlation_id: Optional[str] = None
