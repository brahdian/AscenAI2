from pydantic import BaseModel, Field, field_validator, ValidationError, ConfigDict
from typing import Optional, Union, Any, Literal
import uuid

VALID_TONES = {"professional", "friendly", "casual", "formal", "warm", "direct", "empathetic"}
MAX_CONFIG_DEPTH = 5
MAX_STRING_LENGTH = 50_000
MAX_LIST_ITEMS = 500

class StrictAgentConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tone: Optional[str] = None
    instructions: Optional[str] = None
    greeting_message: Optional[str] = None
    # IVR language-selection prompt: text shown in the UI and used to generate
    # the ivr_language_url audio file.  E.g. "For English press 1, pour le
    # français appuyez sur 2."
    ivr_language_prompt: Optional[str] = Field(
        default=None,
        description="Text for the IVR language-selection prompt. Auto-generates ivr_language_url on save.",
    )
    # CDN URL for the pre-generated IVR language-selection audio file.
    ivr_language_url: Optional[str] = Field(
        default=None,
        description="CDN URL for the TTS-generated IVR language prompt audio.",
    )
    supported_languages: Optional[list[str]] = Field(default_factory=list)
    auto_detect_language: Optional[bool] = False
    voice_greeting_url: Optional[str] = None
    opening_audio_url: Optional[str] = Field(
        default=None,
        description="CDN URL for the pre-rendered mandatory opening audio (Greeting + Language Assistance)."
    )
    voice_system_prompt: Optional[str] = None
    tools: Optional[list[Any]] = Field(default_factory=list)
    knowledge_base_ids: Optional[list[str]] = Field(default_factory=list)
    llm_config: Optional[dict[str, Any]] = Field(default_factory=dict)
    escalation_config: Optional[dict[str, Any]] = Field(default_factory=dict)
    escalation_extensions: Optional[dict[str, str]] = Field(default_factory=dict)

    # Internal persistence for pending agent purchases from templates
    template_context: Optional[dict[str, Any]] = Field(
        default=None, 
        description="Persistent store for template ID and variables during payment redirects."
    )



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
    model_config = ConfigDict(extra="ignore")
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
    test_mode: bool = Field(False, description="If True, bypasses log redaction for quality review")
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
    # Phase 6: Grounding Verification
    is_grounded: Optional[bool] = Field(
        None, description="Whether the response was mathematically verified against the source citations using NLI."
    )
    grounding_explanation: Optional[str] = Field(
        None, description="NLI explanation for why the response was or was not grounded."
    )


class StreamChatEvent(BaseModel):
    type: str = Field(
        ...,
        description="Event type: text_delta, tool_call, tool_result, sources, session, done, error",
    )
    data: Union[str, dict, list]
    session_id: str


class SessionInitRequest(BaseModel):
    """Request body for POST /chat/init — creates a session and returns greetings."""
    agent_id: str = Field(..., description="UUID of the agent to initialise a session for")
    channel: str = Field("chat", description="Channel: chat or voice")
    customer_identifier: Optional[str] = Field(
        None, description="Phone, email, or anonymous identifier for the caller"
    )
    test_mode: bool = Field(False, description="If True, marks session as a test run")


class SessionInitResponse(BaseModel):
    """Response from POST /chat/init."""
    session_id: str = Field(..., description="Newly created (or resumed) session ID")
    # Greeting texts — display only the one matching the active channel
    chat_greeting: str = Field(..., description="Greeting message to display in chat mode")
    voice_greeting: str = Field(..., description="Greeting/IVR prompt to read in voice mode")
    # Language configuration
    language: str = Field("en", description="Primary agent language code")
    supported_languages: list[str] = Field(
        default_factory=list,
        description="Additional language codes the agent can handle",
    )
    auto_detect_language: bool = Field(
        False, description="Whether the agent auto-detects the caller's language"
    )


class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    business_type: str = Field("generic", description="pizza_shop, clinic, salon, generic")
    personality: Optional[str] = None
    system_prompt: Optional[str] = None
    agent_config: dict = Field(default_factory=dict, description="Centralized agent config (voice, tools, etc.)")
    voice_enabled: bool = True
    voice_id: Optional[str] = None
    language: str = "en"
    auto_detect_language: bool = False
    supported_languages: list[str] = Field(default_factory=list)
    greeting_message: Optional[str] = Field(None, max_length=1000)
    # IVR language-selection prompt text (auto-generates ivr_language_url on save)
    ivr_language_prompt: Optional[str] = Field(
        None,
        max_length=500,
        description="IVR language-selection prompt. TTS audio is auto-generated on create/update.",
    )
    voice_greeting_url: Optional[str] = None
    ivr_language_url: Optional[str] = None
    voice_system_prompt: Optional[str] = None
    tools: list[str] = Field(default_factory=list)
    knowledge_base_ids: list[str] = Field(default_factory=list)
    llm_config: Optional[LLMConfig] = None
    escalation_config: Optional[EscalationConfig] = None
    extension_number: Optional[str] = Field(None, max_length=20)
    is_available_as_tool: Optional[bool] = None
    is_active: Optional[bool] = None
    stripe_subscription_id: Optional[str] = None
    expires_at: Optional[str] = None
    guardrails_config: Optional[dict] = Field(None, description="Initial guardrail settings (pii, profanity, etc.)")

    @field_validator("agent_config", mode="before")
    @classmethod
    def validate_agent_config(cls, v: Any) -> dict:
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ValueError("agent_config must be a dictionary")

        # Phase 6: Strict JSONB schema validation
        try:
            validated = StrictAgentConfig(**v)
        except ValidationError as e:
            raise ValueError(f"Strict agent_config validation failed: {e}")

        return validated.model_dump(exclude_unset=True)


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    business_type: Optional[str] = None
    personality: Optional[str] = None
    system_prompt: Optional[str] = None
    agent_config: Optional[dict] = Field(
        None,
        description="Full or partial agent config dict. Keys replace/merge into existing config."
    )
    voice_enabled: Optional[bool] = None
    voice_id: Optional[str] = None
    language: Optional[str] = None
    auto_detect_language: Optional[bool] = None
    supported_languages: Optional[list[str]] = None
    greeting_message: Optional[str] = Field(None, max_length=1000)
    # IVR language-selection prompt text (auto-generates ivr_language_url on save)
    ivr_language_prompt: Optional[str] = Field(
        None,
        max_length=500,
        description="IVR language-selection prompt. TTS audio is auto-generated on create/update.",
    )
    voice_greeting_url: Optional[str] = None
    ivr_language_url: Optional[str] = None
    voice_system_prompt: Optional[str] = None
    opening_preview: Optional[str] = Field(None, description="Custom override for the pre-computed opening greeting.")
    tools: Optional[list[str]] = None
    knowledge_base_ids: Optional[list[str]] = None
    llm_config: Optional[LLMConfig] = None
    escalation_config: Optional[EscalationConfig] = None
    extension_number: Optional[str] = Field(None, max_length=20)
    is_available_as_tool: Optional[bool] = None
    is_active: Optional[bool] = None
    stripe_subscription_id: Optional[str] = None
    expires_at: Optional[str] = None
    version: Optional[int] = Field(None, description="Current version of the agent for optimistic locking")

    @field_validator("agent_config", mode="before")
    @classmethod
    def validate_agent_config(cls, v: Any) -> Optional[dict]:
        if v is None:
            return None
        if not isinstance(v, dict):
            raise ValueError("agent_config must be a dictionary")

        # Phase 6: Strict JSONB schema validation
        try:
            validated = StrictAgentConfig(**v)
        except ValidationError as e:
            raise ValueError(f"Strict agent_config validation failed: {e}")

        return validated.model_dump(exclude_unset=True)


class AgentResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: Optional[str]
    business_type: str
    personality: Optional[str]
    system_prompt: Optional[str]
    agent_config: dict = {}
    voice_enabled: bool
    voice_id: Optional[str]
    language: str
    auto_detect_language: bool = False
    supported_languages: list[str] = []
    greeting_message: Optional[str] = None
    # IVR language-selection prompt text and its pre-generated TTS audio URL
    ivr_language_prompt: Optional[str] = None
    voice_greeting_url: Optional[str] = None
    ivr_language_url: Optional[str] = None
    opening_audio_url: Optional[str] = None
    voice_system_prompt: Optional[str] = None
    computed_greeting: Optional[str] = None
    computed_protocol: Optional[str] = None
    computed_fallback: Optional[str] = None
    tools: list = []
    knowledge_base_ids: list = []
    llm_config: dict = {}
    escalation_config: dict = {}
    extension_number: Optional[str] = None
    is_available_as_tool: bool = True
    is_active: bool
    status: str
    version: int = 1
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


class PlaybookConfig(BaseModel):
    instructions: Optional[str] = Field(None, max_length=MAX_STRING_LENGTH)
    tone: Optional[str] = Field(None, description=f"Valid tones: {', '.join(VALID_TONES)}")
    dos: list[str] = Field(default_factory=list)
    donts: list[str] = Field(default_factory=list)
    scenarios: list[dict] = Field(default_factory=list)
    out_of_scope_response: Optional[str] = Field(None, max_length=MAX_STRING_LENGTH)
    fallback_response: Optional[str] = Field(None, max_length=MAX_STRING_LENGTH)
    custom_escalation_message: Optional[str] = Field(None, max_length=MAX_STRING_LENGTH)
    tools: list[str] = Field(default_factory=list)

    @field_validator("tone")
    @classmethod
    def validate_tone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.lower() not in VALID_TONES:
            raise ValueError(f"tone must be one of: {', '.join(sorted(VALID_TONES))}")
        return v.lower() if v else v

    @field_validator("dos", "donts")
    @classmethod
    def validate_string_list(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_LIST_ITEMS:
            raise ValueError(f"List cannot exceed {MAX_LIST_ITEMS} items")
        return v

    @field_validator("scenarios")
    @classmethod
    def validate_scenarios(cls, v: list[dict]) -> list[dict]:
        if len(v) > MAX_LIST_ITEMS:
            raise ValueError(f"scenarios cannot exceed {MAX_LIST_ITEMS} items")
        return v

    @field_validator("tools")
    @classmethod
    def validate_tools(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_LIST_ITEMS:
            raise ValueError(f"tools cannot exceed {MAX_LIST_ITEMS} items")
        return v


class PlaybookUpsert(BaseModel):
    name: str = Field(default="Default", max_length=255)
    description: Optional[str] = None
    intent_triggers: list[str] = Field(default_factory=list)
    config: dict = Field(
        default_factory=dict,
        description="Playbook configuration: instructions, tone, dos, donts, scenarios, etc."
    )
    is_active: bool = True

    @field_validator("config", mode="before")
    @classmethod
    def validate_config(cls, v: Any) -> dict:
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ValueError("config must be a dictionary")
        
        try:
            validated = PlaybookConfig(**v).model_dump(exclude_none=True)
        except ValidationError as e:
            raise ValueError(f"Invalid config: {e}")
        if len(str(validated)) > MAX_STRING_LENGTH * 2:
            raise ValueError("config content exceeds maximum size")
        return validated


class PlaybookResponse(BaseModel):
    id: str
    agent_id: str
    tenant_id: str
    name: str
    description: Optional[str]
    intent_triggers: list[str]
    instructions: Optional[str] = None
    tone: str = "professional"
    dos: list[str] = Field(default_factory=list)
    donts: list[str] = Field(default_factory=list)
    scenarios: list[dict] = Field(default_factory=list)
    out_of_scope_response: Optional[str] = None
    fallback_response: Optional[str] = None
    custom_escalation_message: Optional[str] = None
    config: dict = Field(default_factory=dict)
    is_active: bool
    created_at: str
    updated_at: str


class PlaybookHistoryResponse(BaseModel):
    id: str
    playbook_id: str
    tenant_id: str
    agent_id: str
    name: str
    description: Optional[str]
    intent_triggers: list[str]
    config: dict = Field(default_factory=dict)
    snapshot_reason: Optional[str]
    created_at: str



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
    config: dict = Field(default_factory=dict)
    is_active: bool = True


class GuardrailsResponse(BaseModel):
    id: str
    agent_id: str
    tenant_id: str
    config: dict
    is_active: bool
    created_at: str
    updated_at: str


class CustomGuardrailSchema(BaseModel):
    id: str
    agent_id: str
    tenant_id: str
    rule: str
    category: str
    is_active: bool
    created_at: str
    updated_at: str


class CustomGuardrailCreate(BaseModel):
    rule: str
    category: str = "Custom"
    is_active: bool = True


class CustomGuardrailUpdate(BaseModel):
    rule: Optional[str] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None


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
