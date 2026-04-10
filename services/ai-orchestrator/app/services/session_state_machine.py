"""
SessionStateMachine
===================
Single authoritative handler for all Session.status lifecycle transitions.

Legal state graph:
  active --> escalated
  active --> closed
  active --> ended
  escalated --> closed
  escalated --> ended
  closed --> (terminal — no further transitions)
  ended  --> (terminal — no further transitions)

Usage:
    from app.services.session_state_machine import SessionStateMachine

    SessionStateMachine.transition(session, "escalated", reason="frustration_threshold")
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import structlog

logger = structlog.get_logger(__name__)

# Adjacency map of legal next states
_TRANSITIONS: dict[str, frozenset[str]] = {
    "active":    frozenset({"escalated", "closed", "ended"}),
    "escalated": frozenset({"closed", "ended"}),
    "closed":    frozenset(),  # terminal
    "ended":     frozenset(),  # terminal
}


class InvalidSessionTransition(ValueError):
    """Raised when an illegal state transition is attempted."""


class SessionStateMachine:
    """
    Centralised guard for Session.status mutations.

    Never mutates status directly — always goes through `transition()` so
    that:
      * Only legal transitions are executed.
      * Every change is logged at the structured-log level.
      * `ended_at` is automatically set when transitioning to a terminal state.
    """

    @staticmethod
    def transition(
        session,
        target: str,
        *,
        reason: Optional[str] = None,
        raise_on_invalid: bool = False,
    ) -> bool:
        """
        Attempt to move *session* to *target* state.

        Parameters
        ----------
        session:
            An ``AgentSession`` ORM instance.
        target:
            Desired next state (``"active"``, ``"escalated"``, ``"closed"``, ``"ended"``).
        reason:
            Optional human-readable reason string, written to the structured log.
        raise_on_invalid:
            If ``True``, raises ``InvalidSessionTransition`` on illegal transitions
            instead of silently skipping.  Default is ``False`` for safety —
            callers should not crash on guard failures.

        Returns
        -------
        bool
            ``True`` if the transition was applied, ``False`` if skipped.
        """
        current: str = getattr(session, "status", "active") or "active"

        if current == target:
            # Already in desired state — idempotent, not an error.
            return True

        allowed = _TRANSITIONS.get(current, frozenset())

        if target not in allowed:
            msg = (
                f"Invalid session transition: {current!r} → {target!r} "
                f"(session_id={getattr(session, 'id', '?')})"
            )
            logger.warning(
                "session_state_machine_invalid_transition",
                session_id=getattr(session, "id", None),
                current_status=current,
                target_status=target,
                reason=reason,
            )
            if raise_on_invalid:
                raise InvalidSessionTransition(msg)
            return False

        # Apply the transition
        session.status = target

        if target in ("closed", "ended") and not getattr(session, "ended_at", None):
            session.ended_at = datetime.now(timezone.utc)

        logger.info(
            "session_state_machine_transition",
            session_id=getattr(session, "id", None),
            from_status=current,
            to_status=target,
            reason=reason,
        )
        return True

    @staticmethod
    def close(session, *, reason: Optional[str] = "inactivity") -> bool:
        """Convenience wrapper to close a session."""
        return SessionStateMachine.transition(session, "closed", reason=reason)

    @staticmethod
    def escalate(session, *, reason: Optional[str] = None) -> bool:
        """Convenience wrapper to escalate a session to a human agent."""
        return SessionStateMachine.transition(session, "escalated", reason=reason)
