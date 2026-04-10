from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Tool Call & Result
# ---------------------------------------------------------------------------

class MCPToolCall(BaseModel):
    tool_name: str = Field(..., min_length=1, max_length=255, description="Name of the tool to invoke")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Tool input parameters")
    session_id: str = Field(..., min_length=1, max_length=255, description="Current session identifier")
    trace_id: str = Field(default="", max_length=255, description="Distributed trace identifier")
    timeout_override: Optional[int] = Field(None, ge=1, le=300, description="Override default timeout in seconds")


class MCPToolResult(BaseModel):
    tool_name: str
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    duration_ms: int = 0
    trace_id: str = ""
    execution_id: Optional[str] = None
    status: str = "completed"  # completed | failed | timeout


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

class ContextItem(BaseModel):
    type: str = Field(..., description="Item type: knowledge | history | customer | product")
    content: str = Field(..., description="The textual content")
    score: float = Field(default=1.0, ge=0.0, le=1.0, description="Relevance score 0-1")
    metadata: dict[str, Any] = Field(default_factory=dict)


class MCPContextRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="Search query")
    session_id: str = Field(..., min_length=1, max_length=255)
    context_types: list[str] = Field(
        default=["knowledge"],
        description="Types to retrieve: knowledge, history, customer",
    )
    top_k: int = Field(default=5, ge=1, le=50, description="Max results per context type")
    tenant_id: str = Field(..., description="Tenant identifier")
    customer_id: Optional[str] = Field(None, description="Customer identifier for CRM lookup")
    kb_id: Optional[str] = Field(None, description="Specific knowledge base to search")

    @field_validator("context_types")
    @classmethod
    def validate_context_types(cls, v: list[str]) -> list[str]:
        valid = {"knowledge", "history", "customer"}
        for t in v:
            if t not in valid:
                raise ValueError(f"Invalid context type '{t}'. Must be one of: {valid}")
        return v


class MCPContextResult(BaseModel):
    items: list[ContextItem] = Field(default_factory=list)
    trace_id: str = ""
    total_found: int = 0


# ---------------------------------------------------------------------------
# Tool Authentication Configuration
# ---------------------------------------------------------------------------

class ToolAuthConfig(BaseModel):
    """Structured auth config stored in AgentTool.config.auth_config (JSONB).
    Using model_config extra='forbid' ensures unknown credential fields are rejected
    at write time, preventing silent misconfigurations.
    """
    model_config = {"extra": "forbid"}

    type: Literal["none", "api_key", "bearer", "basic", "oauth2_cc"] = Field(
        default="none",
        description="Authentication method for this tool's endpoint",
    )
    # api_key / bearer
    value: Optional[str] = Field(
        None,
        max_length=4096,
        description="Credential value — API key or bearer token (stored encrypted at rest)",
    )
    header: Optional[str] = Field(
        None,
        max_length=100,
        description="Header name for api_key auth (e.g. 'X-API-Key', 'Authorization')",
    )
    # basic auth
    username: Optional[str] = Field(None, max_length=255)
    password: Optional[str] = Field(None, max_length=4096, description="Basic auth password (encrypted)")
    # oauth2_cc (client credentials)
    token_url: Optional[str] = Field(None, max_length=2048)
    client_id: Optional[str] = Field(None, max_length=512)
    client_secret: Optional[str] = Field(None, max_length=4096, description="OAuth2 client secret (encrypted)")
    scope: Optional[str] = Field(None, max_length=512)
    audience: Optional[str] = Field(None, max_length=512)


# ---------------------------------------------------------------------------
# Tool Registration
# ---------------------------------------------------------------------------

class ToolRegistration(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_\-]+$")
    description: str = Field(..., min_length=1, max_length=1000)
    category: str = Field(..., min_length=1, max_length=100)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    endpoint_url: Optional[str] = Field(None, max_length=2048)
    auth_config: Optional[ToolAuthConfig] = None
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10000)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    is_builtin: bool = False
    tool_metadata: dict[str, Any] = Field(default_factory=dict)


class ToolUpdate(BaseModel):
    description: Optional[str] = None
    category: Optional[str] = None
    input_schema: Optional[dict[str, Any]] = None
    output_schema: Optional[dict[str, Any]] = None
    endpoint_url: Optional[str] = None
    auth_config: Optional[ToolAuthConfig] = None
    rate_limit_per_minute: Optional[int] = Field(None, ge=1, le=10000)
    timeout_seconds: Optional[int] = Field(None, ge=1, le=300)
    is_active: Optional[bool] = None
    tool_metadata: Optional[dict[str, Any]] = None


class ToolResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str
    category: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    endpoint_url: Optional[str]
    rate_limit_per_minute: int
    timeout_seconds: int
    is_active: bool
    is_builtin: bool
    tool_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Knowledge / Documents
# ---------------------------------------------------------------------------

class KnowledgeDocumentCreate(BaseModel):
    kb_id: str = Field(..., description="Knowledge base UUID")
    title: str = Field(..., min_length=1, max_length=512)
    content: str = Field(..., min_length=1)
    content_type: str = Field(default="text")
    doc_metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeDocumentResponse(BaseModel):
    id: str
    kb_id: str
    tenant_id: str
    title: str
    content_type: str
    vector_id: Optional[str]
    doc_metadata: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="")
    agent_id: Optional[str] = None


class KnowledgeBaseResponse(BaseModel):
    id: str
    tenant_id: str
    agent_id: Optional[str]
    name: str
    description: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Execution History
# ---------------------------------------------------------------------------

class ExecutionResponse(BaseModel):
    id: str
    tenant_id: str
    tool_id: str
    session_id: str
    trace_id: str
    input_data: dict[str, Any]
    output_data: Optional[dict[str, Any]]
    status: str
    error_message: Optional[str]
    duration_ms: Optional[int]
    created_at: datetime
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Streaming / WebSocket Messages
# ---------------------------------------------------------------------------

class StreamMessage(BaseModel):
    type: str = Field(
        ...,
        description="Message type: tool_call | tool_result | context_request | context_result | error | ping | pong",
    )
    payload: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WebSocketMessage(BaseModel):
    """Incoming message from WebSocket client."""
    type: str  # "tool_call" | "context_request" | "ping"
    payload: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    redis: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
