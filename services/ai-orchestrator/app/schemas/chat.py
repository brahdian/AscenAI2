from pydantic import BaseModel, Field
from typing import Literal, Optional, Union
import uuid


class LLMConfig(BaseModel):
    model_config = {"extra": "forbid"}
    model: Optional[str] = Field(None, max_length=100)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1, le=32768)
    provider: Optional[Literal["openai", "gemini", "anthropic"]] = None


class VoiceConfig(BaseModel):
    model_config = {"extra": "forbid"}
    provider: Optional[Literal["openai", "elevenlabs", "google"]] = None
    speaking_rate: Optional[float] = Field(None, ge=0.25, le=4.0)


class EscalationConfig(BaseModel):
    model_config = {"extra": "allow"}
    connector_type: Optional[str] = Field(None, max_length=50)


class ChatMessage(BaseModel):
    role: str = Field(..., description="Message role: user, assistant, or tool")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    session_id: Optional[str] = Field(
        None, description="Existing session ID; if None a new session is created"
    )
    agent_id: str = Field(..., description="UUID of the agent to use")
    message: str = Field(..., max_length=10_000, description="The user message")
    channel: str = Field("text", description="Channel: text, voice, or web")
    customer_identifier: Optional[str] = Field(
        None, description="Phone, email, or anonymous identifier"
    )
    metadata: dict = Field(default_factory=dict, description="Optional extra metadata")
    idempotency_key: Optional[str] = Field(
        None,
        max_length=128,
        description=(
            "Client-supplied deduplication key. If a response was already returned "
            "for this key within 5 minutes the same response is returned without "
            "re-processing. Use a UUID per user send action."
        ),
    )


class SourceCitation(BaseModel):
    """A single RAG source returned alongside the assistant reply."""
    type: str = Field(..., description="Context type: knowledge | history | customer | product")
    title: Optional[str] = None
    source_url: Optional[str] = None
    excerpt: str = Field(..., description="First 150 chars of the context content")
    score: float = Field(..., description="Relevance score 0-1")
    document_id: Optional[str] = None
    chunk_id: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    message: str
    tool_calls_made: list[dict] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    escalate_to_human: bool = False
    # Escalation routing hint for the client:
    #   "phone_transfer"         – voice call: client should initiate transfer to escalation_number
    #   "offer_chat_switch"      – voice call: no phone configured, offer chat instead
    #   "chat_handoff"           – text/web: route to live-chat agent queue
    #   "collect_info"           – text/web: asking user for name + phone
    #   "confirm_info"           – text/web: confirming collected details before scheduling
    #   "phone_callback_scheduled" – callback request registered
    escalation_action: Optional[str] = None
    latency_ms: int
    tokens_used: int
    # RAG breadcrumbs — which knowledge/history items informed this response
    sources: list[SourceCitation] = Field(default_factory=list)
    # Guardrail breadcrumbs
    guardrail_triggered: Optional[str] = Field(
        None, description="Reason the input was blocked (e.g. 'blocked_keyword:xyz', 'profanity')"
    )
    guardrail_actions: list[str] = Field(
        default_factory=list,
        description="Output guardrails applied (e.g. 'pii_redaction', 'length_cap', 'disclaimer_appended')",
    )
    # Session status
    session_status: Optional[str] = Field(
        None, description="Current session status: active, closed, ended, escalated"
    )
    minutes_until_expiry: Optional[float] = Field(
        None, description="Minutes remaining before session auto-closes due to inactivity"
    )
    expiry_warning: bool = Field(
        False, description="True if session is within the warning threshold before expiry"
    )


class StreamChatEvent(BaseModel):
    type: str = Field(
        ...,
        description="Event type: text_delta, tool_call, tool_result, sources, session, done, error",
    )
    data: Union[str, dict, list]
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
    auto_detect_language: bool = False
    supported_languages: list[str] = Field(default_factory=list)
    greeting_message: Optional[str] = Field(None, max_length=1000)
    voice_greeting_url: Optional[str] = None
    voice_system_prompt: Optional[str] = None
    tools: list[str] = Field(default_factory=list)
    knowledge_base_ids: list[str] = Field(default_factory=list)
    llm_config: Optional[LLMConfig] = None
    escalation_config: Optional[EscalationConfig] = None
    # is_active intentionally omitted from AgentCreate — agents start active by default.
    # Use DELETE /agents/{id} to deactivate or POST /agents/{id}/restore to reactivate.


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    business_type: Optional[str] = None
    personality: Optional[str] = None
    system_prompt: Optional[str] = None
    voice_enabled: Optional[bool] = None
    voice_id: Optional[str] = None
    language: Optional[str] = None
    auto_detect_language: Optional[bool] = None
    supported_languages: Optional[list[str]] = None
    greeting_message: Optional[str] = Field(None, max_length=1000)
    voice_greeting_url: Optional[str] = None
    voice_system_prompt: Optional[str] = None
    tools: Optional[list[str]] = None
    knowledge_base_ids: Optional[list[str]] = None
    llm_config: Optional[LLMConfig] = None
    escalation_config: Optional[EscalationConfig] = None
    # is_active intentionally omitted — use DELETE /agents/{id} and POST /agents/{id}/restore
    # to control activation state through the lifecycle state machine.


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
    auto_detect_language: bool
    supported_languages: list
    greeting_message: Optional[str] = None
    voice_greeting_url: Optional[str] = None
    voice_system_prompt: Optional[str] = None
    computed_greeting: Optional[str] = None  # Dynamically generated based on supported_languages
    computed_protocol: Optional[str] = None  # Dynamically generated protocol instructions
    computed_fallback: Optional[str] = None  # Dynamically generated "I didn't catch that" prompt
    tools: list
    knowledge_base_ids: list
    llm_config: dict
    escalation_config: dict
    is_active: bool
    stripe_subscription_id: Optional[str] = None
    deleted_at: Optional[str] = None
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
    last_activity_at: Optional[str] = None
    updated_at: Optional[str]
    messages: Optional[list[dict]] = None
    minutes_until_expiry: Optional[float] = None


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


class ConnectorTestResult(BaseModel):
    success: bool
    connector_type: str
    message: str
    latency_ms: int


# ---------------------------------------------------------------------------
# Feedback / Training Labels
# ---------------------------------------------------------------------------

POSITIVE_LABELS = ["helpful", "accurate", "fast", "clear", "complete"]
NEGATIVE_LABELS = ["wrong", "off-topic", "inappropriate", "slow", "incomplete", "confusing"]


class ToolCorrectionItem(BaseModel):
    """Per-tool assessment inside a feedback submission."""
    tool_name: str = Field(..., description="Name of the tool that was called")
    was_correct: bool = Field(..., description="Was this tool call appropriate?")
    correct_tool: Optional[str] = Field(None, description="What tool should have been called instead (if any)")
    reason: Optional[str] = Field(None, max_length=500, description="Why this tool call was wrong")


class FeedbackCreate(BaseModel):
    message_id: str = Field(..., description="UUID of the assistant message being rated")
    session_id: str = Field(..., description="Session the message belongs to")
    agent_id: str = Field(..., description="Agent UUID")
    rating: Optional[str] = Field(None, description="positive or negative")
    labels: list[str] = Field(default_factory=list, description="Descriptive labels")
    comment: Optional[str] = Field(None, max_length=2000, description="Optional free-text comment")
    ideal_response: Optional[str] = Field(None, max_length=5000, description="What the response should have been")
    correction_reason: Optional[str] = Field(None, max_length=2000, description="Why the original response was wrong")
    feedback_source: str = Field(default="user", description="user or operator")
    # Playbook correction: {"correct_playbook_id": str, "correct_playbook_name": str}
    playbook_correction: Optional[dict] = Field(None, description="Which playbook should have been triggered")
    # Per-tool judgements
    tool_corrections: list[ToolCorrectionItem] = Field(default_factory=list, description="Per-tool assessments")


class FeedbackResponse(BaseModel):
    id: str
    message_id: str
    session_id: str
    tenant_id: str
    agent_id: str
    rating: Optional[str]
    labels: list[str]
    comment: Optional[str]
    ideal_response: Optional[str]
    correction_reason: Optional[str]
    playbook_correction: Optional[dict]
    tool_corrections: list[dict]
    feedback_source: str
    created_at: str
    agent_response: Optional[str] = None
    user_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Playbook
# ---------------------------------------------------------------------------

class ScenarioItem(BaseModel):
    trigger: str = Field(..., description="Trigger phrase or question")
    response: str = Field(..., description="Canned response to use")


class PlaybookUpsert(BaseModel):
    name: str = Field(default="Default", max_length=255)
    description: Optional[str] = None
    intent_triggers: list[str] = Field(default_factory=list)
    is_default: bool = False
    greeting_message: Optional[str] = Field(None, max_length=2000)
    instructions: Optional[str] = Field(None, max_length=10000)
    tone: str = Field(default="professional", description="professional | friendly | casual | empathetic")
    dos: list[str] = Field(default_factory=list)
    donts: list[str] = Field(default_factory=list)
    scenarios: list[ScenarioItem] = Field(default_factory=list)
    out_of_scope_response: Optional[str] = Field(None, max_length=2000)
    fallback_response: Optional[str] = Field(None, max_length=2000)
    custom_escalation_message: Optional[str] = Field(None, max_length=2000)
    is_active: bool = True


class PlaybookResponse(BaseModel):
    id: str
    agent_id: str
    tenant_id: str
    name: str
    description: Optional[str]
    intent_triggers: list[str]
    is_default: bool
    greeting_message: Optional[str] = None
    instructions: Optional[str]
    tone: str
    dos: list[str]
    donts: list[str]
    scenarios: list[dict]
    out_of_scope_response: Optional[str]
    fallback_response: Optional[str]
    custom_escalation_message: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str


class FeedbackSummary(BaseModel):
    total: int
    positive: int
    negative: int
    positive_pct: float
    top_positive_labels: list[dict]
    top_negative_labels: list[dict]
    by_agent: list[dict]


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

class DailyAnalytics(BaseModel):
    date: str
    total_sessions: int
    total_messages: int
    total_chats: int  # This will now contain the pre-calculated total_chat_units
    total_tokens: int
    estimated_cost_usd: float
    avg_latency_ms: float
    tool_executions: int
    escalations: int
    successful_completions: int
    total_voice_minutes: float = 0.0


class AgentAnalyticsSummary(BaseModel):
    agent_id: str
    agent_name: str
    total_sessions: int
    total_messages: int
    total_chats: int
    total_tokens: int
    estimated_cost_usd: float
    avg_latency_ms: float
    total_voice_minutes: float = 0.0
    positive_feedback_pct: Optional[float]


class AnalyticsOverview(BaseModel):
    period_days: int
    total_sessions: int
    total_messages: int
    total_chats: int
    total_tokens: int
    total_cost_usd: float
    avg_latency_ms: float
    total_tool_executions: int
    total_escalations: int
    feedback_positive_pct: Optional[float]
    daily: list[DailyAnalytics]
    by_agent: list[AgentAnalyticsSummary]


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

class GuardrailsUpsert(BaseModel):
    blocked_keywords: list[str] = Field(default_factory=list)
    blocked_topics: list[str] = Field(default_factory=list)
    allowed_topics: list[str] = Field(default_factory=list)
    profanity_filter: bool = True
    pii_redaction: bool = False
    pii_pseudonymization: bool = Field(
        default=False,
        description=(
            "When enabled, PII in user messages is replaced with reversible tokens "
            "before being sent to the LLM. The response tokens are replaced back with "
            "original values before delivery. Recommended for healthcare/financial agents."
        ),
    )
    max_response_length: int = Field(default=0, ge=0)
    require_disclaimer: Optional[str] = Field(None, max_length=1000)
    blocked_message: str = Field(default="I'm sorry, I can't help with that.", max_length=500)
    off_topic_message: str = Field(default="I'm only able to help with topics related to our service.", max_length=500)
    content_filter_level: str = Field(default="medium", description="none|low|medium|strict")
    is_active: bool = True


class GuardrailsResponse(BaseModel):
    id: str
    agent_id: str
    tenant_id: str
    blocked_keywords: list[str]
    blocked_topics: list[str]
    allowed_topics: list[str]
    profanity_filter: bool
    pii_redaction: bool
    pii_pseudonymization: bool = False
    max_response_length: int
    require_disclaimer: Optional[str]
    blocked_message: str
    off_topic_message: str
    content_filter_level: str
    is_active: bool
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Learning Insights
# ---------------------------------------------------------------------------

class LearningGap(BaseModel):
    message_id: str
    session_id: str
    agent_id: str
    user_message: str
    agent_response: str
    created_at: str


class UnreviewedNegative(BaseModel):
    feedback_id: str
    message_id: str
    session_id: str
    agent_id: str
    agent_response: str
    labels: list[str]
    comment: Optional[str]
    created_at: str


class GuardrailTrigger(BaseModel):
    message_id: str
    session_id: str
    agent_id: str
    user_message: str
    trigger_reason: str
    created_at: str


class SuggestedTrainingPair(BaseModel):
    feedback_id: str
    message_id: str
    session_id: str
    agent_id: str
    user_message: str
    agent_response: str
    labels: list[str]
    created_at: str


class LearningInsights(BaseModel):
    agent_id: str
    knowledge_gaps: list[LearningGap]
    unreviewed_negatives: list[UnreviewedNegative]
    guardrail_triggers: list[GuardrailTrigger]
    suggested_training_pairs: list[SuggestedTrainingPair]
    total_gaps: int
    total_unreviewed: int
    total_triggers: int
