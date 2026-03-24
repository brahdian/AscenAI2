from pydantic import BaseModel, Field
from typing import Optional, Union
import uuid


class ChatMessage(BaseModel):
    role: str = Field(..., description="Message role: user, assistant, or tool")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    session_id: Optional[str] = Field(
        None, description="Existing session ID; if None a new session is created"
    )
    agent_id: str = Field(..., description="UUID of the agent to use")
    message: str = Field(..., description="The user message")
    channel: str = Field("text", description="Channel: text, voice, or web")
    customer_identifier: Optional[str] = Field(
        None, description="Phone, email, or anonymous identifier"
    )
    metadata: dict = Field(default_factory=dict, description="Optional extra metadata")


class ChatResponse(BaseModel):
    session_id: str
    message: str
    tool_calls_made: list[dict] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    escalate_to_human: bool = False
    latency_ms: int
    tokens_used: int


class StreamChatEvent(BaseModel):
    type: str = Field(
        ...,
        description="Event type: text_delta, tool_call, tool_result, done, error",
    )
    data: Union[str, dict]
    session_id: str


class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    business_type: str = Field("generic", description="pizza_shop, clinic, salon, generic")
    personality: Optional[str] = None
    system_prompt: Optional[str] = None
    voice_enabled: bool = True
    voice_id: Optional[str] = None
    language: str = "en"
    tools: list[str] = Field(default_factory=list)
    knowledge_base_ids: list[str] = Field(default_factory=list)
    llm_config: dict = Field(default_factory=dict)
    escalation_config: dict = Field(default_factory=dict)


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    business_type: Optional[str] = None
    personality: Optional[str] = None
    system_prompt: Optional[str] = None
    voice_enabled: Optional[bool] = None
    voice_id: Optional[str] = None
    language: Optional[str] = None
    tools: Optional[list[str]] = None
    knowledge_base_ids: Optional[list[str]] = None
    llm_config: Optional[dict] = None
    escalation_config: Optional[dict] = None
    is_active: Optional[bool] = None


class AgentResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: Optional[str]
    business_type: str
    personality: Optional[str]
    system_prompt: Optional[str]
    voice_enabled: bool
    voice_id: Optional[str]
    language: str
    tools: list
    knowledge_base_ids: list
    llm_config: dict
    escalation_config: dict
    is_active: bool
    created_at: Optional[str]
    updated_at: Optional[str]


class SessionResponse(BaseModel):
    id: str
    tenant_id: str
    agent_id: str
    customer_identifier: Optional[str]
    channel: str
    status: str
    metadata: dict
    started_at: Optional[str]
    ended_at: Optional[str]
    updated_at: Optional[str]
    messages: Optional[list[dict]] = None


class SessionAnalyticsResponse(BaseModel):
    session_id: str
    total_messages: int
    user_messages: int
    assistant_messages: int
    total_tokens: int
    total_latency_ms: int
    avg_latency_ms: float
    tool_calls_made: int
    duration_seconds: Optional[float]
    status: str


class AgentTestRequest(BaseModel):
    message: str = Field(..., description="Test message to send to the agent")
    customer_identifier: Optional[str] = "test-user"
