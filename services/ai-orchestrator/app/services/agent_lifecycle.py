"""
Agent lifecycle state machine.

Valid states and their transitions:

    DRAFT → PENDING_PAYMENT | ACTIVE
    PENDING_PAYMENT → ACTIVE | ARCHIVED
    ACTIVE → GRACE | ARCHIVED
    GRACE → ACTIVE | EXPIRED
    EXPIRED → ACTIVE | ARCHIVED
    ARCHIVED → ACTIVE  (restore only)

Use `transition_agent()` for every state change — never mutate `agent.is_active`
or `agent.status` directly outside this module.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# State definitions
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft":           {"pending_payment", "active"},
    "pending_payment": {"active", "archived"},
    "active":          {"grace", "archived"},
    "grace":           {"active", "expired"},
    "expired":         {"active", "archived"},
    "archived":        {"active"},
}

# States that mean the agent is operationally active
_ACTIVE_STATES = frozenset({"active", "grace"})


class AgentLifecycleError(ValueError):
    """Raised when a state transition is not permitted."""


# ---------------------------------------------------------------------------
# Core transition function
# ---------------------------------------------------------------------------

async def transition_agent(
    agent,
    to_state: str,
    db: AsyncSession,
    *,
    actor_id: Optional[str] = None,
    reason: Optional[str] = None,
    request_id: Optional[str] = None,
) -> None:
    """
    Apply a lifecycle transition to *agent* and persist an audit record.

    Raises AgentLifecycleError if the transition is not allowed.
    The caller must commit the session after this function returns.
    """
    from app.models.agent import AgentLifecycleAudit

    from_state: str = getattr(agent, "status", None) or (
        "active" if agent.is_active else "archived"
    )

    allowed = VALID_TRANSITIONS.get(from_state, set())
    if to_state not in allowed:
        raise AgentLifecycleError(
            f"Cannot transition agent {agent.id} from '{from_state}' to '{to_state}'. "
            f"Allowed targets: {sorted(allowed) or 'none'}"
        )

    # Apply state
    agent.status = to_state
    agent.is_active = to_state in _ACTIVE_STATES

    if to_state == "archived":
        agent.deleted_at = datetime.now(timezone.utc)
    elif to_state == "active":
        agent.deleted_at = None

    # Emit structured log — correlate with distributed trace
    logger.info(
        "agent_lifecycle_transition",
        agent_id=str(agent.id),
        tenant_id=str(agent.tenant_id),
        from_state=from_state,
        to_state=to_state,
        actor_id=actor_id,
        reason=reason,
        request_id=request_id,
    )

    # Persist immutable audit record
    db.add(
        AgentLifecycleAudit(
            id=uuid.uuid4(),
            agent_id=agent.id,
            tenant_id=agent.tenant_id,
            from_state=from_state,
            to_state=to_state,
            actor_id=actor_id,
            reason=reason,
            request_id=request_id,
        )
    )
