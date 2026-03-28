"""
Evaluation framework ORM models.

Tables:
  eval_cases    — golden dataset entries (input + expected output)
  eval_runs     — a batch execution of cases against a prompt/agent version
  eval_scores   — per-case scoring results from the LLM-as-judge
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EvalCase(Base):
    """A single golden dataset entry used to evaluate agent behaviour."""

    __tablename__ = "eval_cases"
    __table_args__ = (
        Index("ix_eval_cases_agent_id", "agent_id"),
        Index("ix_eval_cases_tenant_id", "tenant_id"),
        Index("ix_eval_cases_tags", "tags", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )

    # The user input to send to the agent
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional conversation history leading up to this turn
    conversation_history: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Expected outputs (used by LLM-as-judge)
    expected_intent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    expected_tools: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    expected_response_contains: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rubric: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # freeform scoring rubric

    # Metadata
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "agent_id": str(self.agent_id),
            "input_text": self.input_text,
            "conversation_history": self.conversation_history or [],
            "expected_intent": self.expected_intent,
            "expected_tools": self.expected_tools or [],
            "expected_response_contains": self.expected_response_contains,
            "rubric": self.rubric,
            "tags": self.tags or [],
            "description": self.description,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class EvalRun(Base):
    """
    A batch evaluation run — executes a set of EvalCases against an agent
    and computes aggregate metrics.
    """

    __tablename__ = "eval_runs"
    __table_args__ = (
        Index("ix_eval_runs_agent_id", "agent_id"),
        Index("ix_eval_runs_tenant_status", "tenant_id", "status"),
        Index("ix_eval_runs_prompt_version", "prompt_version_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    # Which prompt version was tested (null = agent's current active prompt)
    prompt_version_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Trigger: "manual" | "prompt_activation" | "deploy" | "scheduled"
    trigger: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")

    # Status: pending | running | completed | failed
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")

    # Aggregate results
    total_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pass_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Dimension averages (0.0–1.0)
    avg_relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_accuracy_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_tone_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_rubric_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_composite_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "agent_id": str(self.agent_id),
            "prompt_version_id": self.prompt_version_id,
            "trigger": self.trigger,
            "status": self.status,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "pass_rate": round(self.pass_rate, 4),
            "avg_relevance_score": round(self.avg_relevance_score, 4),
            "avg_accuracy_score": round(self.avg_accuracy_score, 4),
            "avg_tone_score": round(self.avg_tone_score, 4),
            "avg_rubric_score": round(self.avg_rubric_score, 4),
            "avg_composite_score": round(self.avg_composite_score, 4),
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @property
    def gate_pass(self) -> bool:
        """True if this run meets the CI/CD pass threshold (>= 0.8)."""
        return self.pass_rate >= 0.8


class EvalScore(Base):
    """
    Per-case LLM-as-judge scoring result within an EvalRun.
    """

    __tablename__ = "eval_scores"
    __table_args__ = (
        Index("ix_eval_scores_run_id", "run_id"),
        Index("ix_eval_scores_case_id", "case_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_cases.id", ondelete="CASCADE"), nullable=False
    )

    # The actual agent response that was judged
    actual_response: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actual_tools_called: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    actual_intent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Dimension scores (0.0–1.0)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    accuracy_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tone_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rubric_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Weighted composite: 0.1*intent + 0.3*tools + 0.3*content + 0.3*rubric
    composite_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Judge reasoning
    judge_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "case_id": str(self.case_id),
            "actual_response": self.actual_response,
            "actual_tools_called": self.actual_tools_called or [],
            "actual_intent": self.actual_intent,
            "relevance_score": round(self.relevance_score, 4),
            "accuracy_score": round(self.accuracy_score, 4),
            "tone_score": round(self.tone_score, 4),
            "rubric_score": round(self.rubric_score, 4),
            "composite_score": round(self.composite_score, 4),
            "passed": self.passed,
            "judge_reasoning": self.judge_reasoning,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
