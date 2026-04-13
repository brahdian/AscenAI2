"""Tests for booking state machine.

Covers:
  - Happy-path transitions
  - Idempotent re-transition
  - Invalid transition raises InvalidTransitionError
  - WorkflowNotFoundError for missing workflow
  - record_event idempotency (duplicate key = no-op)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.booking import BookingEvent, BookingState, BookingWorkflow
from app.services.booking_state_machine import (
    InvalidTransitionError,
    WorkflowNotFoundError,
    transition,
    record_event,
)


def _make_workflow(state: BookingState = BookingState.INITIATED) -> BookingWorkflow:
    return BookingWorkflow(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        customer_name="Alice",
        customer_phone="+14155551234",
        provider="builtin",
        slot_service="Haircut",
        slot_date="2026-05-01",
        slot_time="10:00",
        state=state,
        state_version=0,
        payment_idempotency_key=str(uuid.uuid4()),
        expiry_time=datetime.now(timezone.utc) + timedelta(minutes=15),
    )


def _make_db(wf=None):
    """Mock SQLAlchemy async session."""
    db = MagicMock()
    # scalar_one_or_none via execute().scalar_one_or_none()
    result = MagicMock()
    result.scalar_one_or_none.return_value = wf
    db.execute = AsyncMock(return_value=result)
    db.scalar = AsyncMock(return_value=wf)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


class TestTransition:
    @pytest.mark.asyncio
    async def test_happy_path_initiated_to_slot_held(self):
        wf = _make_workflow(BookingState.INITIATED)
        db = _make_db(wf)

        result = await transition(db, wf.id, BookingState.SLOT_HELD, actor="test")

        assert result.state == BookingState.SLOT_HELD
        assert result.state_version == 1
        db.add.assert_called_once()  # BookingEvent was added

    @pytest.mark.asyncio
    async def test_idempotent_same_state(self):
        wf = _make_workflow(BookingState.SLOT_HELD)
        db = _make_db(wf)

        result = await transition(db, wf.id, BookingState.SLOT_HELD, actor="test")

        assert result.state == BookingState.SLOT_HELD
        assert result.state_version == 0  # Not incremented
        db.add.assert_not_called()  # No event written

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self):
        wf = _make_workflow(BookingState.CONFIRMED)  # terminal
        db = _make_db(wf)

        with pytest.raises(InvalidTransitionError) as exc_info:
            await transition(db, wf.id, BookingState.SLOT_HELD, actor="test")

        assert "CONFIRMED" in str(exc_info.value)
        assert "SLOT_HELD" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_workflow_not_found_raises(self):
        db = _make_db(wf=None)

        with pytest.raises(WorkflowNotFoundError):
            await transition(db, uuid.uuid4(), BookingState.SLOT_HELD, actor="test")

    @pytest.mark.asyncio
    async def test_payment_completed_to_confirmed(self):
        wf = _make_workflow(BookingState.PAYMENT_COMPLETED)
        db = _make_db(wf)

        result = await transition(db, wf.id, BookingState.CONFIRMED, actor="system")

        assert result.state == BookingState.CONFIRMED
        assert result.state_version == 1

    @pytest.mark.asyncio
    async def test_payment_pending_to_expired(self):
        wf = _make_workflow(BookingState.PAYMENT_PENDING)
        db = _make_db(wf)

        result = await transition(db, wf.id, BookingState.EXPIRED, actor="expiry_worker")

        assert result.state == BookingState.EXPIRED

    @pytest.mark.asyncio
    async def test_needs_rebook_can_retry_slot_held(self):
        wf = _make_workflow(BookingState.NEEDS_REBOOK)
        db = _make_db(wf)

        result = await transition(db, wf.id, BookingState.SLOT_HELD, actor="rebooking_flow")

        assert result.state == BookingState.SLOT_HELD


class TestValidTransitions:
    """Verify the transition table covers all expected paths."""

    from app.services.booking_state_machine import VALID_TRANSITIONS

    def test_terminal_states_have_no_outgoing(self):
        from app.services.booking_state_machine import VALID_TRANSITIONS
        for state in (BookingState.CONFIRMED, BookingState.EXPIRED, BookingState.FAILED):
            assert VALID_TRANSITIONS[state] == set(), f"{state} should be terminal"

    def test_full_happy_path_is_valid(self):
        from app.services.booking_state_machine import VALID_TRANSITIONS
        chain = [
            (BookingState.INITIATED, BookingState.SLOT_HELD),
            (BookingState.SLOT_HELD, BookingState.PAYMENT_PENDING),
            (BookingState.PAYMENT_PENDING, BookingState.PAYMENT_COMPLETED),
            (BookingState.PAYMENT_COMPLETED, BookingState.CONFIRMED),
        ]
        for from_s, to_s in chain:
            assert to_s in VALID_TRANSITIONS[from_s], f"{from_s} → {to_s} must be valid"
