"""Booking workflow models — appointment slot reservation with payment state machine.

Tables
------
booking_workflows  — one row per booking attempt; owns the state machine
booking_events     — append-only audit log; every transition is an event

Design principles
-----------------
* AscenAI owns the state machine; external CRMs (Calendly, Square, GCal) are
  called at the right state transitions.
* `state_version` provides optimistic locking: SELECT FOR UPDATE prevents
  concurrent transitions on the same workflow.
* `payment_intent_id` has a unique constraint — prevents double-confirm from
  duplicate webhooks.
* `booking_events.idempotency_key` unique constraint makes every event write
  idempotent (INSERT … ON CONFLICT DO NOTHING pattern).
"""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, time, timezone
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------

class BookingState(str, enum.Enum):
    INITIATED         = "INITIATED"
    SLOT_HELD         = "SLOT_HELD"
    PAYMENT_PENDING   = "PAYMENT_PENDING"
    PAYMENT_COMPLETED = "PAYMENT_COMPLETED"
    CONFIRMED         = "CONFIRMED"
    EXPIRED           = "EXPIRED"
    FAILED            = "FAILED"
    NEEDS_REBOOK      = "NEEDS_REBOOK"


TERMINAL_STATES = {
    BookingState.CONFIRMED,
    BookingState.EXPIRED,
    BookingState.FAILED,
}

# States that should no longer hold a CRM slot
RELEASED_STATES = {
    BookingState.CONFIRMED,
    BookingState.EXPIRED,
    BookingState.FAILED,
    BookingState.NEEDS_REBOOK,
}


# ---------------------------------------------------------------------------
# BookingWorkflow
# ---------------------------------------------------------------------------

class BookingWorkflow(Base):
    """One row per booking attempt.

    Lifecycle
    ---------
    INITIATED → SLOT_HELD → PAYMENT_PENDING → PAYMENT_COMPLETED → CONFIRMED
                    │              │
                    └──► EXPIRED   └──► EXPIRED | FAILED
                                   └──► NEEDS_REBOOK (slot lost at confirm time)
    """
    __tablename__ = "booking_workflows"
    __table_args__ = (
        UniqueConstraint("payment_intent_id", name="uq_bw_payment_intent_id"),
        Index("ix_bw_tenant_state", "tenant_id", "state"),
        # Partial index: only active workflows need fast expiry queries
        Index(
            "ix_bw_expiry_active",
            "expiry_time",
            postgresql_where=(
                "state NOT IN ('CONFIRMED','EXPIRED','FAILED','NEEDS_REBOOK')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    # Original session that started this flow — may be closed after disconnect
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # Customer contact — must be persisted for post-disconnect SMS
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    customer_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")

    # Which external provider handles the actual booking
    # "calendly" | "square" | "google_calendar" | "custom" | "builtin"
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="builtin")

    # External CRM reservation identifiers (set after hold_slot call)
    external_reservation_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_reservation_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Slot details — stored here so we can recover after a CRM error
    slot_service: Mapped[str] = mapped_column(String(255), nullable=False)
    slot_date: Mapped[date] = mapped_column(Date, nullable=False)
    slot_time: Mapped[str] = mapped_column(String(10), nullable=False)  # "HH:MM"
    slot_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)

    # State machine
    state: Mapped[BookingState] = mapped_column(
        SAEnum(BookingState, name="booking_state", create_type=True),
        nullable=False,
        default=BookingState.INITIATED,
    )
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Payment
    # Unique key passed to Stripe at link creation — ensures idempotent link creation
    payment_idempotency_key: Mapped[str] = mapped_column(
        String(128), nullable=False, default=lambda: str(uuid.uuid4())
    )
    payment_link_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Stripe PaymentIntent ID — set after link creation; unique across all workflows
    payment_intent_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Slot hold expiry — configurable via tenant_config["slot_hold_ttl_minutes"]
    expiry_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Tracks whether a reminder SMS has been sent (to avoid double-sending)
    sms_reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Provider-specific extras (e.g., Calendly event_type_uuid, Square location_id)
    extra_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    # Relationship
    events: Mapped[list[BookingEvent]] = relationship(
        "BookingEvent", back_populates="workflow", order_by="BookingEvent.created_at"
    )

    def __repr__(self) -> str:
        return (
            f"<BookingWorkflow id={self.id!s:.8} state={self.state.value} "
            f"tenant={self.tenant_id!s:.8} slot={self.slot_date} {self.slot_time}>"
        )


# ---------------------------------------------------------------------------
# BookingEvent — append-only audit log
# ---------------------------------------------------------------------------

class BookingEvent(Base):
    """Immutable audit record for every state transition and significant action.

    The `idempotency_key` unique constraint means any event can be written
    safely with an INSERT … ON CONFLICT DO NOTHING — no duplicate processing.
    """
    __tablename__ = "booking_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_be_idempotency_key"),
        Index("ix_be_workflow_id", "workflow_id"),
        Index("ix_be_event_type", "event_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("booking_workflows.id", ondelete="CASCADE"),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    from_state: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    to_state: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # "user" | "system" | "stripe_webhook" | "expiry_worker" | "appointment_tool"
    actor: Mapped[str] = mapped_column(String(64), nullable=False, default="system")

    # Unique key prevents duplicate event inserts (idempotent writes)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # Relationship
    workflow: Mapped[BookingWorkflow] = relationship(
        "BookingWorkflow", back_populates="events"
    )

    def __repr__(self) -> str:
        return (
            f"<BookingEvent type={self.event_type} "
            f"workflow={self.workflow_id!s:.8} actor={self.actor}>"
        )
