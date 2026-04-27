"""
Pydantic schemas for the declarative Playbook Engine.

A playbook is a state-machine definition expressed as a DAG of typed steps.
The engine executes steps in order, persisting state between turns so the
user can drive a multi-step workflow (e.g. refund flow, booking flow) with
full durability.

Step types
----------
llm            — call the LLM with a prompt template; optionally extract JSON
deterministic  — set_variable or format_message without any LLM/tool call
tool           — execute an MCP tool with mapped arguments
condition      — branch on a Python-safe boolean expression
wait_input     — pause execution and prompt the user for input
goto           — unconditional jump to another step
end            — terminal step; emits a final message and marks the session done
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Step base
# ---------------------------------------------------------------------------

class PlaybookStep(BaseModel):
    """Common fields shared by every step type."""

    id: str = Field(..., description="Unique step identifier within the playbook")
    type: str = Field(..., description="Step type discriminator")
    description: Optional[str] = Field(None, description="Human-readable description (ignored at runtime)")
    # Most steps advance to next_step_id after completion.
    # If None the engine will look for a step ordering convention or treat as end.
    next_step_id: Optional[str] = Field(None, description="Step to advance to after this one succeeds")


# ---------------------------------------------------------------------------
# Concrete step types
# ---------------------------------------------------------------------------

class LLMStep(PlaybookStep):
    """
    Call the LLM with a rendered prompt template.

    The LLM receives ONLY the current step's context — it cannot see prior
    steps' raw prompts or skip ahead in the playbook.

    Variables from ``state.variables`` are substituted into the template
    using ``{{var_name}}`` syntax before the call is made.
    """
    type: Literal["llm"] = "llm"

    prompt_template: str = Field(
        ...,
        description=(
            "Jinja-style template with {{var_name}} placeholders. "
            "Substituted from state.variables before calling the LLM."
        ),
    )
    output_variable: str = Field(
        ...,
        description="State variable name to store the LLM text response in",
    )
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=1, le=8192)
    extract_json: bool = Field(
        default=False,
        description=(
            "If True, attempt to parse the LLM response as JSON and store "
            "the parsed dict into output_variable instead of raw text."
        ),
    )


class DeterministicStep(PlaybookStep):
    """
    Pure in-process operation — no LLM or tool call.

    Supported actions
    -----------------
    set_variable    — params: {variable: str, value: Any}
                      Sets state.variables[variable] = value.
                      Value may contain {{var}} references.
    format_message  — params: {template: str, output_variable: str}
                      Renders template with current variables and stores the
                      result in state.variables[output_variable].
    """
    type: Literal["deterministic"] = "deterministic"

    action: Literal["set_variable", "format_message"] = Field(
        ..., description="The deterministic action to execute"
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific parameters (see action docstring above)",
    )


class ToolStep(PlaybookStep):
    """
    Execute a named MCP tool.

    ``argument_mapping`` maps tool argument names to either:
    - a literal value:  ``{"amount": 100}``
    - a variable ref:   ``{"order_id": "{{order_id}}"}``

    On error the engine applies ``on_error``:
    - ``continue`` — log the error, store the error string in
                     ``output_variable`` if set, advance to next_step_id
    - ``fail``     — transition to ``end`` with status=failed
    - ``retry``    — retry up to ``retry_attempts`` times with
                     ``retry_delay_seconds`` back-off, then apply the inner
                     ``on_retry_exhausted`` policy (continue|fail)
    """
    type: Literal["tool"] = "tool"

    tool_name: str = Field(..., description="MCP tool name to invoke")
    argument_mapping: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Maps MCP tool argument names to literal values or {{var}} references. "
            "References are substituted from state.variables before the call."
        ),
    )
    output_variable: Optional[str] = Field(
        None,
        description="If set, stores the serialised tool result in this variable",
    )
    on_error: Literal["continue", "fail", "retry"] = Field(
        default="fail",
        description="What to do when the tool call fails",
    )
    retry_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Max retries when on_error=retry",
    )
    retry_delay_seconds: float = Field(
        default=1.0,
        ge=0.0,
        le=60.0,
        description="Back-off between retries (seconds)",
    )
    on_retry_exhausted: Literal["continue", "fail"] = Field(
        default="fail",
        description="Policy after all retries are spent",
    )


class ConditionStep(PlaybookStep):
    """
    Branch on a Python-safe boolean expression.

    The expression is evaluated in a sandboxed namespace that contains only
    the current ``state.variables`` dict.  No imports, no builtins beyond
    basic math / string operations are permitted.

    Example expressions
    -------------------
    ``int(order_age_days) < 30``
    ``status == 'active'``
    ``float(total) > 100.0 and currency == 'USD'``
    """
    type: Literal["condition"] = "condition"

    expression: str = Field(
        ...,
        description=(
            "Python-safe boolean expression evaluated against state.variables. "
            "Variable names are injected directly into the eval namespace."
        ),
    )
    then_step_id: str = Field(
        ..., description="Step to advance to when expression evaluates to True"
    )
    else_step_id: str = Field(
        ..., description="Step to advance to when expression evaluates to False"
    )


class WaitInputStep(PlaybookStep):
    """
    Pause the playbook and prompt the user for free-text input.

    The engine returns ``awaiting_input=True`` to the caller and halts until
    ``advance()`` is called again with the user's reply.

    ``validation_regex``, if provided, is checked against the raw input.
    If it does not match, ``error_message`` is returned and the step is
    retried (the user is re-prompted).
    """
    type: Literal["wait_input"] = "wait_input"

    prompt_to_user: str = Field(
        ...,
        description=(
            "Message shown to the user. Supports {{var}} substitution "
            "from the current state.variables."
        ),
    )
    variable_to_store: str = Field(
        ...,
        description="State variable name to write the user's reply into",
    )
    validation_regex: Optional[str] = Field(
        None,
        description=(
            "Optional Python regex pattern. If the user input does not match, "
            "the step re-prompts with error_message."
        ),
    )
    error_message: Optional[str] = Field(
        None,
        description=(
            "Shown to the user when validation_regex fails. "
            "Defaults to a generic 'invalid input' message."
        ),
    )
    timeout_seconds: Optional[int] = Field(
        None,
        description=(
            "If set, the step transitions to timeout_step_id after this many "
            "seconds of inactivity. Not enforced by the engine itself — the "
            "caller is responsible for scheduling a timeout check."
        ),
    )
    timeout_step_id: Optional[str] = Field(
        None,
        description="Step to advance to on timeout (requires timeout_seconds)",
    )

    @field_validator("validation_regex")
    @classmethod
    def _validate_regex(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                re.compile(v)
            except re.error as exc:
                raise ValueError(f"Invalid validation_regex: {exc}") from exc
        return v


class GotoStep(PlaybookStep):
    """Unconditional jump to another step (useful after branch re-convergence)."""

    type: Literal["goto"] = "goto"
    target_step_id: str = Field(..., description="The step to jump to")


class EndStep(PlaybookStep):
    """
    Terminal step.  Execution halts; the engine marks the session as done.

    ``final_message_template`` is rendered with current variables and
    returned as the last response to the user.
    """
    type: Literal["end"] = "end"

    final_message_template: str = Field(
        ...,
        description="Final message rendered with {{var}} substitution",
    )
    status: Literal["completed", "escalated", "failed"] = Field(
        default="completed",
        description="Outcome written to PlaybookExecution.status",
    )


# ---------------------------------------------------------------------------
# Discriminated union of all step types
# ---------------------------------------------------------------------------

AnyStep = Annotated[
    Union[
        LLMStep,
        DeterministicStep,
        ToolStep,
        ConditionStep,
        WaitInputStep,
        GotoStep,
        EndStep,
    ],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Top-level playbook definition
# ---------------------------------------------------------------------------

class PlaybookDefinition(BaseModel):
    """
    A complete playbook definition.

    The ``steps`` dict maps step IDs to typed step objects.  The execution
    engine starts at ``initial_step_id`` and follows ``next_step_id`` /
    branch pointers until an ``EndStep`` is reached or the max-steps guard
    fires.

    ``trigger_keywords`` are matched (case-insensitive substring) against
    incoming user messages by the orchestrator to auto-start this playbook.
    """

    id: str = Field(..., description="Globally unique playbook ID (slug-style, e.g. 'refund_v1')")
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    version: str = Field(default="1.0.0", description="Semantic version string")
    trigger_keywords: list[str] = Field(
        default_factory=list,
        description=(
            "If any of these words/phrases appears in a user message "
            "(case-insensitive), the orchestrator auto-starts this playbook."
        ),
    )
    initial_step_id: str = Field(..., description="The first step to execute")
    steps: dict[str, AnyStep] = Field(
        ...,
        description="All steps keyed by their id. The id inside the step must match the dict key.",
    )

    @model_validator(mode="after")
    def _validate_steps(self) -> "PlaybookDefinition":
        # Ensure initial_step_id exists
        if self.initial_step_id not in self.steps:
            raise ValueError(
                f"initial_step_id '{self.initial_step_id}' not found in steps"
            )
        # Ensure every step's id matches its dict key
        for key, step in self.steps.items():
            if step.id != key:
                raise ValueError(
                    f"Step dict key '{key}' does not match step.id '{step.id}'"
                )
        # Validate all step cross-references
        all_ids = set(self.steps.keys())
        for step in self.steps.values():
            refs: list[str] = []
            if hasattr(step, "next_step_id") and step.next_step_id:
                refs.append(step.next_step_id)
            if isinstance(step, ConditionStep):
                refs += [step.then_step_id, step.else_step_id]
            if isinstance(step, GotoStep):
                refs.append(step.target_step_id)
            if isinstance(step, WaitInputStep) and step.timeout_step_id:
                refs.append(step.timeout_step_id)
            for ref in refs:
                if ref not in all_ids:
                    raise ValueError(
                        f"Step '{step.id}' references unknown step_id '{ref}'"
                    )
        return self


# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------

class StepHistoryEntry(BaseModel):
    """One entry written to PlaybookState.history per executed step."""

    step_id: str
    step_type: str
    executed_at: str  # ISO-8601 timestamp
    result_summary: Optional[str] = None  # short human-readable note
    variables_snapshot: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class PlaybookState(BaseModel):
    """
    Serialisable runtime state for a single playbook session.

    Persisted in Redis under ``playbook_state:{session_id}`` (24 h TTL)
    and check-pointed to PostgreSQL ``playbook_executions`` on every
    step transition.
    """

    session_id: str
    playbook_id: str
    current_step_id: str
    variables: dict[str, Any] = Field(default_factory=dict)
    history: list[StepHistoryEntry] = Field(default_factory=list)
    # status: active | awaiting_input | completed | failed | escalated
    status: str = Field(default="active")
    awaiting_input: bool = False
    step_count: int = Field(default=0, description="Total steps executed so far")
    created_at: str  # ISO-8601
    updated_at: str  # ISO-8601
    # Populated when status transitions to a terminal state
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Example playbooks (shipped as built-in templates)
# ---------------------------------------------------------------------------

REFUND_PLAYBOOK = PlaybookDefinition(
    id="refund_v1",
    name="Refund Request Flow",
    description=(
        "Guides a customer through the refund request process: collects the "
        "order ID, verifies eligibility (< 30 days), confirms the refund, "
        "then processes it via Stripe."
    ),
    version="1.0.0",
    trigger_keywords=["refund", "return", "money back", "get my money", "charge back"],
    initial_step_id="collect_order_id",
    steps={
        # NOTE: Greeting is now handled at agent level (Agent.greeting_message
        # + Agent.voice_greeting_url), not inside playbook steps.
        "collect_order_id": WaitInputStep(
            id="collect_order_id",
            type="wait_input",
            description="Ask the customer for their order ID.",
            prompt_to_user=(
                "Hello! I can help you with a refund request. "
                "Please provide your order ID (e.g. ORD-12345):"
            ),
            variable_to_store="order_id",
            validation_regex=r"^[A-Za-z0-9\-]{3,50}$",
            error_message=(
                "That doesn't look like a valid order ID. "
                "Please enter a format like ORD-12345."
            ),
            next_step_id="lookup_order",
        ),
        "lookup_order": ToolStep(
            id="lookup_order",
            type="tool",
            description="Fetch order details from the backend.",
            tool_name="get_order_details",
            argument_mapping={"order_id": "{{order_id}}"},
            output_variable="order_details",
            on_error="fail",
            next_step_id="check_eligibility",
        ),
        "check_eligibility": ConditionStep(
            id="check_eligibility",
            type="condition",
            description="Check if the order is within the 30-day refund window.",
            expression="int(order_details.get('age_days', 999)) < 30",
            then_step_id="confirm_refund",
            else_step_id="ineligible_end",
        ),
        "confirm_refund": WaitInputStep(
            id="confirm_refund",
            type="wait_input",
            description="Ask the customer to confirm before processing.",
            prompt_to_user=(
                "Your order {{order_id}} is eligible for a refund. "
                "Would you like to proceed? (yes / no)"
            ),
            variable_to_store="user_confirmation",
            validation_regex=r"^(yes|no|y|n)$",
            error_message="Please reply with 'yes' or 'no'.",
            next_step_id="route_confirmation",
        ),
        "route_confirmation": ConditionStep(
            id="route_confirmation",
            type="condition",
            description="Route based on the user's yes/no answer.",
            expression="user_confirmation.lower() in ('yes', 'y')",
            then_step_id="process_refund",
            else_step_id="cancelled_end",
        ),
        "process_refund": ToolStep(
            id="process_refund",
            type="tool",
            description="Issue the refund via Stripe.",
            tool_name="stripe_create_refund",
            argument_mapping={
                "order_id": "{{order_id}}",
                "amount": "{{order_details.amount}}",
                "currency": "{{order_details.currency}}",
            },
            output_variable="refund_result",
            on_error="retry",
            retry_attempts=3,
            retry_delay_seconds=2.0,
            on_retry_exhausted="fail",
            next_step_id="refund_success_end",
        ),
        "refund_success_end": EndStep(
            id="refund_success_end",
            type="end",
            description="Inform the customer the refund was processed.",
            final_message_template=(
                "Your refund for order {{order_id}} has been processed successfully. "
                "You should see the funds returned within 3-5 business days. "
                "Is there anything else I can help you with?"
            ),
            status="completed",
        ),
        "ineligible_end": EndStep(
            id="ineligible_end",
            type="end",
            description="Inform the customer the order is outside the refund window.",
            final_message_template=(
                "I'm sorry, but order {{order_id}} is outside our 30-day refund window "
                "and is not eligible for a refund. "
                "If you believe this is an error, please contact our support team."
            ),
            status="completed",
        ),
        "cancelled_end": EndStep(
            id="cancelled_end",
            type="end",
            description="The customer chose not to proceed.",
            final_message_template=(
                "No problem! Your refund request has been cancelled. "
                "Let me know if there's anything else I can help with."
            ),
            status="completed",
        ),
    },
)


BOOKING_PLAYBOOK = PlaybookDefinition(
    id="booking_v1",
    name="Appointment Booking Flow",
    description=(
        "Guides a customer through scheduling an appointment: collects their "
        "name and preferred date, checks availability, generates a confirmation "
        "message via LLM, creates the booking, and sends a confirmation email."
    ),
    version="1.0.0",
    trigger_keywords=["book", "appointment", "schedule", "reserve", "booking"],
    initial_step_id="collect_name",
    steps={
        # NOTE: Greeting is now handled at agent level.
        "collect_name": WaitInputStep(
            id="collect_name",
            type="wait_input",
            description="Welcome and ask for the customer's name.",
            prompt_to_user=(
                "Welcome! I'd be happy to help you schedule an appointment. "
                "May I have your full name, please?"
            ),
            variable_to_store="customer_name",
            validation_regex=r"^[A-Za-z\s'\-]{2,100}$",
            error_message=(
                "Please enter your full name (letters, spaces, hyphens only)."
            ),
            next_step_id="collect_date",
        ),
        "collect_date": WaitInputStep(
            id="collect_date",
            type="wait_input",
            description="Ask the customer for their preferred appointment date.",
            prompt_to_user=(
                "Thank you, {{customer_name}}! "
                "What date would you prefer for your appointment? "
                "Please use the format YYYY-MM-DD (e.g. 2026-04-15)."
            ),
            variable_to_store="preferred_date",
            validation_regex=r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$",
            error_message=(
                "Please enter the date in YYYY-MM-DD format, e.g. 2026-04-15."
            ),
            next_step_id="check_availability",
        ),
        "check_availability": ToolStep(
            id="check_availability",
            type="tool",
            description="Check if the requested date has open slots.",
            tool_name="check_appointment_availability",
            argument_mapping={"date": "{{preferred_date}}"},
            output_variable="availability",
            on_error="fail",
            next_step_id="availability_branch",
        ),
        "availability_branch": ConditionStep(
            id="availability_branch",
            type="condition",
            description="Branch on whether slots are available.",
            expression="availability.get('slots_available', 0) > 0",
            then_step_id="confirm_booking",
            else_step_id="no_availability_end",
        ),
        "confirm_booking": LLMStep(
            id="confirm_booking",
            type="llm",
            description="Generate a warm confirmation message using the LLM.",
            prompt_template=(
                "You are a friendly appointment scheduler assistant. "
                "A customer named {{customer_name}} has requested an appointment "
                "on {{preferred_date}}. There are {{availability.slots_available}} "
                "slots available. "
                "Write a brief, friendly confirmation message (2-3 sentences) "
                "that confirms we will book the appointment and asks them to "
                "confirm by replying 'confirm'."
            ),
            output_variable="confirmation_message",
            temperature=0.5,
            max_tokens=200,
            extract_json=False,
            next_step_id="wait_booking_confirm",
        ),
        "wait_booking_confirm": WaitInputStep(
            id="wait_booking_confirm",
            type="wait_input",
            description="Show the LLM-generated message and wait for customer confirmation.",
            prompt_to_user="{{confirmation_message}}",
            variable_to_store="booking_confirmed",
            validation_regex=r"^(confirm|yes|no|cancel)$",
            error_message="Please reply with 'confirm' to proceed or 'no' to cancel.",
            next_step_id="booking_confirm_branch",
        ),
        "booking_confirm_branch": ConditionStep(
            id="booking_confirm_branch",
            type="condition",
            description="Check if the customer confirmed the booking.",
            expression="booking_confirmed.lower() in ('confirm', 'yes')",
            then_step_id="create_booking",
            else_step_id="booking_cancelled_end",
        ),
        "create_booking": ToolStep(
            id="create_booking",
            type="tool",
            description="Create the appointment record in the backend.",
            tool_name="create_appointment",
            argument_mapping={
                "customer_name": "{{customer_name}}",
                "date": "{{preferred_date}}",
            },
            output_variable="booking_result",
            on_error="retry",
            retry_attempts=2,
            retry_delay_seconds=1.0,
            on_retry_exhausted="fail",
            next_step_id="send_confirmation",
        ),
        "send_confirmation": ToolStep(
            id="send_confirmation",
            type="tool",
            description="Send a confirmation email to the customer.",
            tool_name="send_email",
            argument_mapping={
                "recipient_name": "{{customer_name}}",
                "subject": "Appointment Confirmation — {{preferred_date}}",
                "booking_id": "{{booking_result.booking_id}}",
                "date": "{{preferred_date}}",
            },
            output_variable="email_result",
            on_error="continue",  # Non-fatal — booking already created
            next_step_id="booking_success_end",
        ),
        "booking_success_end": EndStep(
            id="booking_success_end",
            type="end",
            description="Confirm the booking to the customer.",
            final_message_template=(
                "Your appointment has been booked for {{preferred_date}}, "
                "{{customer_name}}! A confirmation email has been sent to you. "
                "Your booking reference is {{booking_result.booking_id}}. "
                "See you then!"
            ),
            status="completed",
        ),
        "no_availability_end": EndStep(
            id="no_availability_end",
            type="end",
            description="Inform the customer no slots are available.",
            final_message_template=(
                "I'm sorry, {{customer_name}}, but there are no available slots "
                "on {{preferred_date}}. Please try a different date or contact "
                "us directly for assistance."
            ),
            status="completed",
        ),
        "booking_cancelled_end": EndStep(
            id="booking_cancelled_end",
            type="end",
            description="The customer cancelled the booking.",
            final_message_template=(
                "No problem, {{customer_name}}! Your booking request has been "
                "cancelled. Feel free to reach out whenever you'd like to "
                "schedule an appointment."
            ),
            status="completed",
        ),
    },
)


# ---------------------------------------------------------------------------
# Engine result types
# ---------------------------------------------------------------------------

class StepResult:
    """
    Internal return value from a single step executor.

    Not a Pydantic model — kept as a plain dataclass for speed.
    """
    __slots__ = (
        "message", "next_step_id", "awaiting_input",
        "terminal", "terminal_status", "error", "continue_on_error",
    )

    def __init__(
        self,
        message: Optional[str] = None,
        next_step_id: Optional[str] = None,
        awaiting_input: bool = False,
        terminal: bool = False,
        terminal_status: Optional[str] = None,
        error: Optional[str] = None,
        continue_on_error: bool = False,
    ) -> None:
        self.message = message
        self.next_step_id = next_step_id
        self.awaiting_input = awaiting_input
        self.terminal = terminal
        self.terminal_status = terminal_status
        self.error = error
        self.continue_on_error = continue_on_error


class PlaybookAdvanceResult(BaseModel):
    """Returned by PlaybookEngine.advance() to the orchestrator."""

    session_id: str
    status: str  # active | awaiting_input | completed | failed | escalated
    message: Optional[str] = None
    awaiting_input: bool = False
    completed: bool = False
    variables: dict[str, Any] = Field(default_factory=dict)
    step_count: int = 0
    current_step_id: Optional[str] = None


LEAD_QUALIFICATION_PLAYBOOK = PlaybookDefinition(
    id="lead_qualification_v1",
    name="Lead Qualification",
    description=(
        "Qualifies an inbound lead by collecting their name, contact, and interest, "
        "then routes them to the right next step (demo, callback, or self-serve)."
    ),
    version="1.0.0",
    trigger_keywords=["book a demo", "pricing", "interested", "learn more", "how does it work", "tell me more"],
    initial_step_id="collect_name",
    steps={
        "collect_name": WaitInputStep(
            id="collect_name",
            type="wait_input",
            description="Ask for the lead's full name.",
            prompt_to_user="Hi! I'd love to learn more about what you're looking for. May I have your full name?",
            variable_to_store="lead_name",
            validation_regex=r"^[A-Za-z\s'\-]{2,100}$",
            error_message="Please enter your full name (letters only).",
            next_step_id="collect_email",
        ),
        "collect_email": WaitInputStep(
            id="collect_email",
            type="wait_input",
            description="Collect the lead's email address.",
            prompt_to_user="Thanks, {{lead_name}}! What's the best email address to reach you?",
            variable_to_store="lead_email",
            validation_regex=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
            error_message="Please enter a valid email address (e.g. name@company.com).",
            next_step_id="collect_interest",
        ),
        "collect_interest": WaitInputStep(
            id="collect_interest",
            type="wait_input",
            description="Ask what they are primarily interested in.",
            prompt_to_user=(
                "Perfect! What are you most interested in — a live demo, a pricing quote, "
                "or general information? Just reply with 'demo', 'pricing', or 'info'."
            ),
            variable_to_store="lead_interest",
            validation_regex=r"^(demo|pricing|info)$",
            error_message="Please reply with 'demo', 'pricing', or 'info'.",
            next_step_id="route_interest",
        ),
        "route_interest": ConditionStep(
            id="route_interest",
            type="condition",
            description="Route to the appropriate next step based on interest.",
            expression="lead_interest.lower() == 'demo'",
            then_step_id="book_demo",
            else_step_id="capture_lead_end",
        ),
        "book_demo": ToolStep(
            id="book_demo",
            type="tool",
            description="Create a demo booking for the lead.",
            tool_name="create_demo_booking",
            argument_mapping={"name": "{{lead_name}}", "email": "{{lead_email}}"},
            output_variable="demo_result",
            on_error="continue",
            next_step_id="demo_booked_end",
        ),
        "demo_booked_end": EndStep(
            id="demo_booked_end",
            type="end",
            description="Confirm the demo booking.",
            final_message_template=(
                "Great news, {{lead_name}}! A demo has been scheduled and a confirmation "
                "will be sent to {{lead_email}}. Our team looks forward to speaking with you!"
            ),
            status="completed",
        ),
        "capture_lead_end": EndStep(
            id="capture_lead_end",
            type="end",
            description="Capture lead and close with a follow-up promise.",
            final_message_template=(
                "Thanks, {{lead_name}}! We've saved your details and someone from our team "
                "will follow up at {{lead_email}} with {{lead_interest}} information shortly. "
                "Is there anything else I can help you with today?"
            ),
            status="completed",
        ),
    },
)


ORDER_HANDLING_PLAYBOOK = PlaybookDefinition(
    id="order_handling_v1",
    name="Order Handling",
    description=(
        "Guides a customer through placing an order: collects item and quantity, "
        "confirms details, processes the order, and provides a reference number."
    ),
    version="1.0.0",
    trigger_keywords=["order", "buy", "purchase", "add to cart", "i want", "i'd like to get"],
    initial_step_id="collect_item",
    steps={
        "collect_item": WaitInputStep(
            id="collect_item",
            type="wait_input",
            description="Ask the customer what they would like to order.",
            prompt_to_user="I'd be happy to help you place an order! What would you like to order today?",
            variable_to_store="order_item",
            validation_regex=r"^.{2,200}$",
            error_message="Please tell me what you'd like to order.",
            next_step_id="collect_quantity",
        ),
        "collect_quantity": WaitInputStep(
            id="collect_quantity",
            type="wait_input",
            description="Ask for the quantity.",
            prompt_to_user="How many would you like? (Enter a number, e.g. 2)",
            variable_to_store="order_quantity",
            validation_regex=r"^[1-9][0-9]?$",
            error_message="Please enter a valid quantity between 1 and 99.",
            next_step_id="confirm_order",
        ),
        "confirm_order": WaitInputStep(
            id="confirm_order",
            type="wait_input",
            description="Confirm the order details with the customer.",
            prompt_to_user=(
                "To confirm: {{order_quantity}} x {{order_item}}. "
                "Shall I place this order? (yes / no)"
            ),
            variable_to_store="order_confirmed",
            validation_regex=r"^(yes|no|y|n)$",
            error_message="Please reply with 'yes' or 'no'.",
            next_step_id="route_order_confirm",
        ),
        "route_order_confirm": ConditionStep(
            id="route_order_confirm",
            type="condition",
            description="Branch on confirmation.",
            expression="order_confirmed.lower() in ('yes', 'y')",
            then_step_id="place_order",
            else_step_id="order_cancelled_end",
        ),
        "place_order": ToolStep(
            id="place_order",
            type="tool",
            description="Submit the order to the backend.",
            tool_name="create_order",
            argument_mapping={
                "item": "{{order_item}}",
                "quantity": "{{order_quantity}}",
            },
            output_variable="order_result",
            on_error="retry",
            retry_attempts=2,
            retry_delay_seconds=1.0,
            on_retry_exhausted="fail",
            next_step_id="order_success_end",
        ),
        "order_success_end": EndStep(
            id="order_success_end",
            type="end",
            description="Confirm the order was placed.",
            final_message_template=(
                "Your order for {{order_quantity}} x {{order_item}} has been placed! "
                "Your order reference is {{order_result.order_id}}. "
                "Is there anything else I can help you with?"
            ),
            status="completed",
        ),
        "order_cancelled_end": EndStep(
            id="order_cancelled_end",
            type="end",
            description="Order cancelled by customer.",
            final_message_template=(
                "No problem — your order has been cancelled. "
                "Let me know if you'd like to order something else!"
            ),
            status="completed",
        ),
    },
)


CUSTOMER_SUPPORT_PLAYBOOK = PlaybookDefinition(
    id="customer_support_v1",
    name="Customer Support",
    description=(
        "Handles general customer support inquiries: collects the issue, "
        "searches the knowledge base, and escalates to a human if unresolved."
    ),
    version="1.0.0",
    trigger_keywords=["help", "issue", "problem", "complaint", "question", "not working", "broken", "wrong"],
    initial_step_id="collect_issue",
    steps={
        "collect_issue": WaitInputStep(
            id="collect_issue",
            type="wait_input",
            description="Ask the customer to describe their issue.",
            prompt_to_user=(
                "I'm here to help! Could you briefly describe what's going on "
                "so I can find the best solution for you?"
            ),
            variable_to_store="customer_issue",
            validation_regex=r"^.{5,1000}$",
            error_message="Please describe your issue in a few words.",
            next_step_id="search_knowledge",
        ),
        "search_knowledge": ToolStep(
            id="search_knowledge",
            type="tool",
            description="Search the knowledge base for relevant answers.",
            tool_name="search_knowledge_base",
            argument_mapping={"query": "{{customer_issue}}"},
            output_variable="kb_result",
            on_error="continue",
            next_step_id="route_kb_result",
        ),
        "route_kb_result": ConditionStep(
            id="route_kb_result",
            type="condition",
            description="Check if the knowledge base returned a useful answer.",
            expression="bool(kb_result.get('answer'))",
            then_step_id="present_answer",
            else_step_id="escalate_to_human",
        ),
        "present_answer": LLMStep(
            id="present_answer",
            type="llm",
            description="Present the knowledge base answer in a friendly way.",
            prompt_template=(
                "A customer asked: {{customer_issue}}\n"
                "The knowledge base returned: {{kb_result.answer}}\n"
                "Write a concise, friendly response (2-4 sentences) that addresses their issue directly. "
                "End by asking if this resolved their problem."
            ),
            output_variable="support_response",
            temperature=0.4,
            max_tokens=300,
            extract_json=False,
            next_step_id="check_resolved",
        ),
        "check_resolved": WaitInputStep(
            id="check_resolved",
            type="wait_input",
            description="Check if the answer resolved the customer's issue.",
            prompt_to_user="{{support_response}}",
            variable_to_store="issue_resolved",
            validation_regex=r"^(yes|no|y|n)$",
            error_message="Please reply with 'yes' if resolved or 'no' if you need more help.",
            next_step_id="route_resolved",
        ),
        "route_resolved": ConditionStep(
            id="route_resolved",
            type="condition",
            description="Escalate if not resolved.",
            expression="issue_resolved.lower() in ('yes', 'y')",
            then_step_id="support_resolved_end",
            else_step_id="escalate_to_human",
        ),
        "escalate_to_human": ToolStep(
            id="escalate_to_human",
            type="tool",
            description="Escalate to a human support agent.",
            tool_name="escalate_to_human",
            argument_mapping={"issue_summary": "{{customer_issue}}"},
            output_variable="escalation_result",
            on_error="continue",
            next_step_id="escalation_end",
        ),
        "support_resolved_end": EndStep(
            id="support_resolved_end",
            type="end",
            description="Issue resolved successfully.",
            final_message_template=(
                "I'm glad that helped! Is there anything else I can assist you with today?"
            ),
            status="completed",
        ),
        "escalation_end": EndStep(
            id="escalation_end",
            type="end",
            description="Inform customer of escalation.",
            final_message_template=(
                "I've connected you with our support team who will follow up shortly. "
                "Your reference number is {{escalation_result.ticket_id}}. "
                "Thank you for your patience!"
            ),
            status="escalated",
        ),
    },
)


PAYMENT_CHECKOUT_PLAYBOOK = PlaybookDefinition(
    id="payment_checkout_v1",
    name="Payment & Checkout",
    description=(
        "Handles payment and checkout: confirms the amount, collects explicit "
        "user authorization, processes payment via Stripe, and provides a receipt."
    ),
    version="1.0.0",
    trigger_keywords=["pay", "checkout", "card", "billing", "payment", "charge", "invoice"],
    initial_step_id="confirm_amount",
    steps={
        "confirm_amount": WaitInputStep(
            id="confirm_amount",
            type="wait_input",
            description="Confirm the payment amount with the customer.",
            prompt_to_user=(
                "I can help you complete your payment. "
                "The amount due is {{payment_amount}} {{payment_currency}}. "
                "Would you like to proceed? (yes / no)"
            ),
            variable_to_store="payment_confirmed",
            validation_regex=r"^(yes|no|y|n)$",
            error_message="Please reply with 'yes' to proceed or 'no' to cancel.",
            next_step_id="route_payment_confirm",
        ),
        "route_payment_confirm": ConditionStep(
            id="route_payment_confirm",
            type="condition",
            description="Branch on payment confirmation.",
            expression="payment_confirmed.lower() in ('yes', 'y')",
            then_step_id="process_payment",
            else_step_id="payment_cancelled_end",
        ),
        "process_payment": ToolStep(
            id="process_payment",
            type="tool",
            description="Process payment via Stripe.",
            tool_name="stripe_create_payment",
            argument_mapping={
                "amount": "{{payment_amount}}",
                "currency": "{{payment_currency}}",
                "customer_id": "{{customer_id}}",
            },
            output_variable="payment_result",
            on_error="fail",
            next_step_id="route_payment_result",
        ),
        "route_payment_result": ConditionStep(
            id="route_payment_result",
            type="condition",
            description="Branch on payment success or failure.",
            expression="payment_result.get('status') == 'succeeded'",
            then_step_id="payment_success_end",
            else_step_id="payment_failed_end",
        ),
        "payment_success_end": EndStep(
            id="payment_success_end",
            type="end",
            description="Payment successful.",
            final_message_template=(
                "Payment of {{payment_amount}} {{payment_currency}} was successful! "
                "Your confirmation code is {{payment_result.confirmation_code}}. "
                "A receipt has been sent to your email. Is there anything else I can help with?"
            ),
            status="completed",
        ),
        "payment_cancelled_end": EndStep(
            id="payment_cancelled_end",
            type="end",
            description="Payment cancelled by customer.",
            final_message_template=(
                "No problem — your payment has been cancelled. "
                "Let me know if you'd like to try again or need any help."
            ),
            status="completed",
        ),
        "payment_failed_end": EndStep(
            id="payment_failed_end",
            type="end",
            description="Payment failed.",
            final_message_template=(
                "I'm sorry, the payment could not be processed. "
                "Please try a different card or contact your bank. "
                "Would you like to try again or speak with a support agent?"
            ),
            status="failed",
        ),
    },
)


ESCALATION_HANDOFF_PLAYBOOK = PlaybookDefinition(
    id="escalation_handoff_v1",
    name="Escalation to Human",
    description=(
        "Handles explicit customer requests to speak with a human agent: "
        "collects a brief reason, initiates the handoff, and provides a ticket reference."
    ),
    version="1.0.0",
    trigger_keywords=["speak to agent", "talk to human", "real person", "manager", "escalate", "human", "representative"],
    initial_step_id="acknowledge_request",
    steps={
        "acknowledge_request": WaitInputStep(
            id="acknowledge_request",
            type="wait_input",
            description="Acknowledge the request and collect a brief reason.",
            prompt_to_user=(
                "Of course! I'll connect you with a member of our team right away. "
                "Could you briefly tell me what this is about so they're prepared to help you?"
            ),
            variable_to_store="escalation_reason",
            validation_regex=r"^.{2,500}$",
            error_message="Please provide a brief description (at least 2 characters).",
            next_step_id="initiate_escalation",
        ),
        "initiate_escalation": ToolStep(
            id="initiate_escalation",
            type="tool",
            description="Create a support ticket and notify a human agent.",
            tool_name="escalate_to_human",
            argument_mapping={"issue_summary": "{{escalation_reason}}"},
            output_variable="escalation_result",
            on_error="continue",
            next_step_id="escalation_confirmed_end",
        ),
        "escalation_confirmed_end": EndStep(
            id="escalation_confirmed_end",
            type="end",
            description="Confirm the handoff to the customer.",
            final_message_template=(
                "You've been connected to our support team. "
                "Your reference number is {{escalation_result.ticket_id}}. "
                "An agent will be with you shortly. Thank you for your patience!"
            ),
            status="escalated",
        ),
    },
)


# ---------------------------------------------------------------------------
# Registry of built-in playbooks (used by the engine for quick lookup)
# ---------------------------------------------------------------------------

BUILTIN_PLAYBOOKS: dict[str, PlaybookDefinition] = {
    REFUND_PLAYBOOK.id: REFUND_PLAYBOOK,
    BOOKING_PLAYBOOK.id: BOOKING_PLAYBOOK,
    LEAD_QUALIFICATION_PLAYBOOK.id: LEAD_QUALIFICATION_PLAYBOOK,
    ORDER_HANDLING_PLAYBOOK.id: ORDER_HANDLING_PLAYBOOK,
    CUSTOMER_SUPPORT_PLAYBOOK.id: CUSTOMER_SUPPORT_PLAYBOOK,
    PAYMENT_CHECKOUT_PLAYBOOK.id: PAYMENT_CHECKOUT_PLAYBOOK,
    ESCALATION_HANDOFF_PLAYBOOK.id: ESCALATION_HANDOFF_PLAYBOOK,
}
