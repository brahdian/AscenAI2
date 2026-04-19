"""
AgentStateMachine
=================
Single authoritative handler for all Agent.status lifecycle transitions.

Legal state graph:
  DRAFT            → PENDING_PAYMENT, ACTIVE, ARCHIVED
  PENDING_PAYMENT  → ACTIVE, ARCHIVED, DRAFT
  ACTIVE           → GRACE, EXPIRED, ARCHIVED
  GRACE            → ACTIVE, EXPIRED, ARCHIVED
  EXPIRED          → GRACE, ARCHIVED, ACTIVE
  ARCHIVED         → ACTIVE, DRAFT, PENDING_PAYMENT   ← revivable for slot re-use

Every transition is persisted to `agent_state_transitions` for a full audit
trail. The DB write is a fire-and-forget `db.add()` — the caller must commit.

Usage:
    from app.services.agent_state_machine import AgentStateMachine

    ok = await AgentStateMachine.transition(
        agent, "ACTIVE", db=db,
        reason="stripe_payment_confirmed",
        actor="billing_webhook",
    )
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from app.models.agent_transitions import AgentStateTransition

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# State graph
# ---------------------------------------------------------------------------

VALID_STATES: frozenset[str] = frozenset(
    {"DRAFT", "PENDING_PAYMENT", "ACTIVE", "GRACE", "EXPIRED", "ARCHIVED"}
)

_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT":            frozenset({"PENDING_PAYMENT", "ACTIVE", "ARCHIVED"}),
    "PENDING_PAYMENT":  frozenset({"ACTIVE", "ARCHIVED", "DRAFT"}),
    "ACTIVE":           frozenset({"GRACE", "EXPIRED", "ARCHIVED"}),
    "GRACE":            frozenset({"ACTIVE", "EXPIRED", "ARCHIVED"}),
    "EXPIRED":          frozenset({"GRACE", "ARCHIVED", "ACTIVE"}),
    # ARCHIVED is now revivable — an operator can swap a slot to a different agent.
    "ARCHIVED":         frozenset({"ACTIVE", "DRAFT", "PENDING_PAYMENT"}),
}


class InvalidAgentTransition(ValueError):
    """Raised when an illegal agent state transition is attempted."""


class AgentStateMachine:
    """
    Centralised guard for Agent.status mutations with full audit trail.

    Never mutate Agent.status directly — always use this class so that:
      * Only legal transitions execute.
      * Every change is logged at structlog level.
      * Every change is persisted to agent_state_transitions.
    """

    @staticmethod
    async def transition(
        agent,
        target: str,
        *,
        db,
        reason: Optional[str] = None,
        actor: Optional[str] = "system",
        raise_on_invalid: bool = False,
    ) -> bool:
        """
        Attempt to move *agent* to *target* state.

        Parameters
        ----------
        agent:
            An ``Agent`` ORM instance.
        target:
            Desired next state (one of VALID_STATES).
        db:
            SQLAlchemy AsyncSession — used to write the transition record.
        reason:
            Optional human-readable reason string.
        actor:
            Who triggered the transition (e.g. "billing_webhook", "admin_api").
        raise_on_invalid:
            If True, raises ``InvalidAgentTransition`` on illegal transitions.

        Returns
        -------
        bool
            True if the transition was applied, False if skipped.
        """
        # Normalise to uppercase
        target = target.upper()
        current: str = (getattr(agent, "status", "DRAFT") or "DRAFT").upper()

        # Unknown target state — always reject
        if target not in VALID_STATES:
            msg = f"Unknown agent state: {target!r}"
            logger.error("agent_state_machine_unknown_target", target=target, agent_id=str(getattr(agent, "id", "?")))
            if raise_on_invalid:
                raise InvalidAgentTransition(msg)
            return False

        if current == target:
            # Already in desired state — idempotent, not an error.
            return True

        allowed = _TRANSITIONS.get(current, frozenset())

        if target not in allowed:
            msg = (
                f"Invalid agent transition: {current!r} → {target!r} "
                f"(agent_id={getattr(agent, 'id', '?')})"
            )
            logger.warning(
                "agent_state_machine_invalid_transition",
                agent_id=str(getattr(agent, "id", None)),
                tenant_id=str(getattr(agent, "tenant_id", None)),
                current_status=current,
                target_status=target,
                reason=reason,
                actor=actor,
            )
            if raise_on_invalid:
                raise InvalidAgentTransition(msg)
            return False

        # ── Apply the transition ──────────────────────────────────────────
        agent.status = target

        # Maintain is_active flag in sync with state
        if target == "ACTIVE":
            agent.is_active = True
        elif target in ("EXPIRED", "ARCHIVED", "PENDING_PAYMENT"):
            agent.is_active = False

        # Write audit record
        try:
            record = AgentStateTransition(
                id=uuid.uuid4(),
                agent_id=agent.id,
                tenant_id=agent.tenant_id,
                from_state=current,
                to_state=target,
                reason=reason or "",
                actor=actor or "system",
                transitioned_at=datetime.now(timezone.utc),
            )
            db.add(record)
        except Exception as audit_err:
            # Never block the transition because of an audit write failure.
            logger.error(
                "agent_state_transition_audit_write_failed",
                error=str(audit_err),
                agent_id=str(getattr(agent, "id", None)),
            )

        logger.info(
            "agent_state_machine_transition",
            agent_id=str(getattr(agent, "id", None)),
            tenant_id=str(getattr(agent, "tenant_id", None)),
            from_status=current,
            to_status=target,
            reason=reason,
            actor=actor,
        )
        return True

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------

    @staticmethod
    async def activate(agent, *, db, reason: Optional[str] = None, actor: str = "system") -> bool:
        """Transition agent to ACTIVE."""
        return await AgentStateMachine.transition(
            agent, "ACTIVE", db=db, reason=reason, actor=actor
        )

    @staticmethod
    async def archive(agent, *, db, reason: Optional[str] = None, actor: str = "system") -> bool:
        """Transition agent to ARCHIVED (soft-delete)."""
        return await AgentStateMachine.transition(
            agent, "ARCHIVED", db=db, reason=reason, actor=actor
        )

    @staticmethod
    async def pending_payment(agent, *, db, reason: Optional[str] = None, actor: str = "system") -> bool:
        """Transition agent to PENDING_PAYMENT (awaiting Stripe confirmation)."""
        return await AgentStateMachine.transition(
            agent, "PENDING_PAYMENT", db=db, reason=reason, actor=actor
        )

    @staticmethod
    async def enter_grace(agent, *, db, reason: Optional[str] = None, actor: str = "system") -> bool:
        """Transition agent to GRACE (subscription lapsed but within grace period)."""
        return await AgentStateMachine.transition(
            agent, "GRACE", db=db, reason=reason, actor=actor
        )

    @staticmethod
    async def expire(agent, *, db, reason: Optional[str] = None, actor: str = "system") -> bool:
        """Transition agent to EXPIRED."""
        return await AgentStateMachine.transition(
            agent, "EXPIRED", db=db, reason=reason, actor=actor
        )

    @staticmethod
    async def deactivate(
        agent,
        *,
        db,
        reason: Optional[str] = None,
        actor: str = "system",
    ) -> bool:
        """Archive an agent to free its slot (the preferred deactivation path)."""
        return await AgentStateMachine.transition(
            agent, "ARCHIVED", db=db, reason=reason, actor=actor
        )

    @staticmethod
    async def revive(
        agent,
        *,
        db,
        reason: Optional[str] = None,
        actor: str = "system",
    ) -> bool:
        """Revive an archived/expired agent when a slot is available."""
        return await AgentStateMachine.transition(
            agent, "ACTIVE", db=db, reason=reason, actor=actor
        )
