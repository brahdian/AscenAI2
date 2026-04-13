"""Booking workflow state machine.

Design
------
* Every transition acquires a row-level lock (SELECT … FOR UPDATE) so concurrent
  callers serialize on the same workflow row — no lost updates.
* Transitions are idempotent: calling transition(wf, SLOT_HELD) when the
  workflow is already SLOT_HELD is a silent no-op.
* `state_version` is incremented on every real transition — callers can assert
  optimistic-lock expectations if needed.
* A BookingEvent record is written inside the same transaction as the state
  change — the audit trail is always consistent with the state.
* The idempotency_key on BookingEvent is "{workflow_id}:{from_state}:{to_state}",
  so even if two processes race to the same transition, only one event row lands.
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import BookingEvent, BookingState, BookingWorkflow

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Legal transition table
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[BookingState, set[BookingState]] = {
    BookingState.INITIATED: {
        BookingState.SLOT_HELD,
        BookingState.FAILED,
    },
    BookingState.SLOT_HELD: {
        BookingState.PAYMENT_PENDING,
        BookingState.EXPIRED,
        BookingState.FAILED,
    },
    BookingState.PAYMENT_PENDING: {
        BookingState.PAYMENT_COMPLETED,
        BookingState.EXPIRED,
        BookingState.FAILED,
    },
    BookingState.PAYMENT_COMPLETED: {
        BookingState.CONFIRMED,
        BookingState.NEEDS_REBOOK,
    },
    # Terminal states — no outgoing transitions
    BookingState.CONFIRMED:     set(),
    BookingState.EXPIRED:       set(),
    BookingState.FAILED:        set(),
    # NEEDS_REBOOK allows re-entering the flow with a new slot
    BookingState.NEEDS_REBOOK:  {BookingState.SLOT_HELD, BookingState.FAILED},
}


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class WorkflowNotFoundError(Exception):
    def __init__(self, workflow_id: uuid.UUID) -> None:
        super().__init__(f"BookingWorkflow {workflow_id} not found")
        self.workflow_id = workflow_id


class InvalidTransitionError(Exception):
    def __init__(self, from_state: BookingState, to_state: BookingState) -> None:
        super().__init__(
            f"Invalid booking state transition: {from_state.value} → {to_state.value}"
        )
        self.from_state = from_state
        self.to_state = to_state


# ---------------------------------------------------------------------------
# Core transition function
# ---------------------------------------------------------------------------

async def transition(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    to_state: BookingState,
    actor: str,
    payload: Optional[dict] = None,
) -> BookingWorkflow:
    """Atomically transition a BookingWorkflow to a new state.

    Parameters
    ----------
    db          : Active async SQLAlchemy session (caller manages commit).
    workflow_id : UUID of the workflow to transition.
    to_state    : Target state.
    actor       : Who triggered this transition ("stripe_webhook", "expiry_worker", etc.)
    payload     : Optional dict stored on the BookingEvent for debugging.

    Returns
    -------
    The updated BookingWorkflow ORM instance.

    Raises
    ------
    WorkflowNotFoundError  — workflow_id does not exist.
    InvalidTransitionError — the transition is not in VALID_TRANSITIONS.

    Notes
    -----
    * Uses SELECT … FOR UPDATE to serialize concurrent access.
    * Already-at-target-state is idempotent (returns without writing).
    * The BookingEvent is written in the same transaction as the state update.
    """
    # SELECT … FOR UPDATE — serializes concurrent transition attempts
    result = await db.execute(
        select(BookingWorkflow)
        .where(BookingWorkflow.id == workflow_id)
        .with_for_update()
    )
    wf: Optional[BookingWorkflow] = result.scalar_one_or_none()

    if wf is None:
        raise WorkflowNotFoundError(workflow_id)

    # Idempotent: already at target state — no-op
    if wf.state == to_state:
        logger.debug(
            "booking_transition_idempotent",
            workflow_id=str(workflow_id),
            state=to_state.value,
        )
        return wf

    # Guard: validate the transition is allowed
    allowed = VALID_TRANSITIONS.get(wf.state, set())
    if to_state not in allowed:
        raise InvalidTransitionError(wf.state, to_state)

    from_state = wf.state

    # Apply state change and bump version (optimistic lock signal)
    wf.state = to_state
    wf.state_version += 1

    # Write immutable audit event (idempotent via unique key)
    event = BookingEvent(
        workflow_id=workflow_id,
        event_type=f"STATE_{from_state.value}_TO_{to_state.value}",
        from_state=from_state.value,
        to_state=to_state.value,
        actor=actor,
        idempotency_key=f"{workflow_id}:{from_state.value}:{to_state.value}",
        payload=payload or {},
    )
    db.add(event)

    logger.info(
        "booking_state_transitioned",
        workflow_id=str(workflow_id),
        from_state=from_state.value,
        to_state=to_state.value,
        actor=actor,
        state_version=wf.state_version,
    )

    return wf


async def record_event(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    event_type: str,
    actor: str,
    idempotency_key: Optional[str] = None,
    payload: Optional[dict] = None,
) -> None:
    """Write a non-transition event to the audit log (idempotent).

    Used for events like PAYMENT_LINK_SENT, STRIPE_EVENT_SEALED, SMS_SENT, etc.
    If idempotency_key is provided and already exists, the insert is silently
    skipped via INSERT … ON CONFLICT DO NOTHING.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = pg_insert(BookingEvent).values(
        id=uuid.uuid4(),
        workflow_id=workflow_id,
        event_type=event_type,
        actor=actor,
        idempotency_key=idempotency_key,
        payload=payload or {},
    )
    if idempotency_key:
        stmt = stmt.on_conflict_do_nothing(index_elements=["idempotency_key"])
    await db.execute(stmt)
