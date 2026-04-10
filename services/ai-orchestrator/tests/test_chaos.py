"""
Chaos & Failure Test Suite — Phase 9 of Platform Hardening
===========================================================
Tests that the system degrades gracefully and NEVER silently corrupts data
when external dependencies (Redis, DB, LLM, Stripe) fail.

Run with:
    pytest services/ai-orchestrator/tests/test_chaos.py -v

Each test class groups failures by dependency type.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Path fix: IdempotencyService lives in api-gateway, not ai-orchestrator.
# We add the api-gateway source root to sys.path so the chaos tests can
# import it directly without cross-service dependencies at runtime.
# ---------------------------------------------------------------------------
_GW_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../../api-gateway")
)
if _GW_ROOT not in sys.path:
    sys.path.insert(0, _GW_ROOT)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def fake_agent():
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.tenant_id = uuid.uuid4()
    agent.status = "ACTIVE"
    agent.is_active = True
    agent.agent_config = {}
    agent.name = "TestBot"
    return agent


@pytest.fixture
def fake_session():
    session = MagicMock()
    session.id = str(uuid.uuid4())
    session.tenant_id = uuid.uuid4()
    session.agent_id = uuid.uuid4()
    session.status = "active"
    session.turn_count = 0
    session.metadata_ = {}
    session.customer_identifier = None
    session.channel = "text"
    session.is_expired.return_value = False
    return session


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.flush = AsyncMock()
    return db


# ===========================================================================
# Phase 5 — Circuit Breaker Tests
# ===========================================================================

class TestCircuitBreaker:
    """Verify the circuit breaker transitions state correctly under failures."""

    @pytest.mark.asyncio
    async def test_breaker_trips_open_after_threshold(self):
        from app.core.circuit_breaker import CircuitBreaker, CircuitOpenError

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # CLOSED
        mock_redis.incr = AsyncMock(side_effect=[1, 2, 3, 4, 5])
        mock_redis.expire = AsyncMock()
        mock_redis.delete = AsyncMock()
        mock_redis.setex = AsyncMock()
        mock_redis.expireat = AsyncMock()

        cb = CircuitBreaker(
            name="test_llm",
            redis=mock_redis,
            failure_threshold=3,
            recovery_timeout=5,
        )

        async def failing_fn():
            raise RuntimeError("LLM API unavailable")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(failing_fn)

        # After threshold, state should be OPEN
        mock_redis.get = AsyncMock(return_value="OPEN")
        with pytest.raises(CircuitOpenError):
            await cb.call(failing_fn)

    @pytest.mark.asyncio
    async def test_breaker_recovers_after_timeout(self):
        from app.core.circuit_breaker import CircuitBreaker

        mock_redis = AsyncMock()

        import time
        # Simulate open_at in the past (beyond recovery_timeout)
        past = str(time.time() - 100)
        call_count = 0
        state_seq = ["OPEN", "HALF_OPEN", "CLOSED"]

        async def get_side_effect(key):
            if "state" in key:
                return state_seq.pop(0) if state_seq else "CLOSED"
            if "open_at" in key:
                return past
            if "half_open_calls" in key:
                return None
            return None

        mock_redis.get = AsyncMock(side_effect=get_side_effect)
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()
        mock_redis.setex = AsyncMock()
        mock_redis.delete = AsyncMock()

        cb = CircuitBreaker(name="test_llm_recovery", redis=mock_redis, recovery_timeout=10)

        async def success_fn():
            return "ok"

        result = await cb.call(success_fn)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_breaker_fail_open_when_redis_down(self):
        """When Redis is unavailable, circuit breaker must NOT block traffic."""
        from app.core.circuit_breaker import CircuitBreaker

        # Simulate Redis being completely unavailable
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))

        cb = CircuitBreaker(name="test_failopen", redis=mock_redis)

        async def good_fn():
            return "response"

        # Must succeed even with broken Redis
        result = await cb.call(good_fn)
        assert result == "response"

    @pytest.mark.asyncio
    async def test_breaker_no_redis_passthrough(self):
        """Without Redis, breaker degrades to a no-op pass-through."""
        from app.core.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(name="noop", redis=None)

        async def fn():
            return 42

        result = await cb.call(fn)
        assert result == 42


# ===========================================================================
# Phase 5 — LLM Timeout Tests
# ===========================================================================

class TestLLMTimeout:
    """Verify that LLM timeouts produce a graceful fallback, not a 500."""

    @pytest.mark.asyncio
    async def test_llm_timeout_returns_fallback(self, fake_agent, fake_session, mock_db):
        from app.services.orchestrator import Orchestrator
        from app.schemas.chat import ChatResponse

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_mcp = AsyncMock()
        mock_mcp.retrieve_context = AsyncMock(return_value=[])
        mock_memory = AsyncMock()
        mock_memory.get_short_term_memory = AsyncMock(return_value=[])
        mock_memory.get_session_summary = AsyncMock(return_value=None)

        with patch("app.services.orchestrator.LLM_TIMEOUT_SECONDS", 0.001):
            orch = Orchestrator(
                llm_client=mock_llm,
                mcp_client=mock_mcp,
                memory_manager=mock_memory,
                db=mock_db,
                redis_client=None,
            )

            with patch.object(orch.context_builder, "load_guardrails", AsyncMock(return_value=None)), \
                 patch.object(orch.context_builder, "load_custom_guardrails", AsyncMock(return_value=None)), \
                 patch.object(orch.context_builder, "load_platform_guardrails", AsyncMock(return_value=None)), \
                 patch.object(orch.context_builder, "load_variables", AsyncMock(return_value={})), \
                 patch.object(orch.context_builder, "load_corrections", AsyncMock(return_value=[])), \
                 patch.object(orch.context_builder, "build_system_prompt", return_value="prompt"), \
                 patch.object(orch.context_builder, "get_agent_tools_schema", AsyncMock(return_value=[])), \
                 patch.object(orch.playbook_handler, "route_active_playbook", AsyncMock(return_value=None)), \
                 patch.object(orch.playbook_handler, "ensure_playbook_execution", AsyncMock(return_value=(None, {}))), \
                 patch.object(orch.billing_service, "check_session_expiry", return_value=None), \
                 patch.object(orch.billing_service, "maybe_send_greeting", AsyncMock(return_value=None)), \
                 patch.object(orch.billing_service, "check_token_budget", AsyncMock(return_value=True)), \
                 patch.object(orch.billing_service, "update_analytics", AsyncMock()), \
                 patch.object(orch.billing_service, "record_token_usage", AsyncMock()):

                # The response must be a ChatResponse with fallback text, not a 500
                response = await orch.process_message(fake_agent, fake_session, "hello")
                assert isinstance(response, ChatResponse)
                # Must contain something reassuring, not be empty
                assert len(response.message) > 0
                assert response.tokens_used == 0


# ===========================================================================
# Phase 2 — Idempotency Tests
# ===========================================================================

class TestIdempotency:
    """Verify duplicate events are correctly detected and rejected."""

    @pytest.mark.asyncio
    async def test_redis_hit_prevents_reprocessing(self, mock_db):
        from app.services.idempotency_service import IdempotencyService  # api-gateway

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="1")  # Already processed

        svc = IdempotencyService(db=mock_db, redis=mock_redis)
        already_done = await svc.is_already_processed("stripe_event", "evt_abc123")

        assert already_done is True
        # DB should NOT have been queried
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_redis_miss_fallback_to_db(self, mock_db):
        from app.services.idempotency_service import IdempotencyService  # api-gateway

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # Redis miss
        mock_redis.setex = AsyncMock()

        # DB also returns no row — fresh event
        mock_db.execute = AsyncMock(
            return_value=MagicMock(first=MagicMock(return_value=None))
        )

        svc = IdempotencyService(db=mock_db, redis=mock_redis)
        already_done = await svc.is_already_processed("stripe_event", "evt_new")

        assert already_done is False

    @pytest.mark.asyncio
    async def test_redis_down_uses_db_fallback(self, mock_db):
        from app.services.idempotency_service import IdempotencyService  # api-gateway

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))

        # DB has a record → already processed
        mock_row = MagicMock()
        mock_db.execute = AsyncMock(
            return_value=MagicMock(first=MagicMock(return_value=mock_row))
        )

        svc = IdempotencyService(db=mock_db, redis=mock_redis)
        already_done = await svc.is_already_processed("stripe_event", "evt_replay")

        assert already_done is True

    @pytest.mark.asyncio
    async def test_both_down_allows_processing(self, mock_db):
        """If BOTH Redis and DB are down, fail-open to prevent total blockage."""
        from app.services.idempotency_service import IdempotencyService  # api-gateway

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        mock_db.execute = AsyncMock(side_effect=Exception("DB timeout"))

        svc = IdempotencyService(db=mock_db, redis=mock_redis)
        already_done = await svc.is_already_processed("stripe_event", "evt_chaos")

        # Fail-open: allow processing
        assert already_done is False


# ===========================================================================
# Phase 3 — Agent State Machine Tests
# ===========================================================================

class TestAgentStateMachine:
    """Verify invalid transitions are rejected."""

    @pytest.mark.asyncio
    async def test_valid_transition_succeeds(self, fake_agent, mock_db):
        from app.services.agent_state_machine import AgentStateMachine

        fake_agent.status = "DRAFT"
        result = await AgentStateMachine.transition(
            fake_agent, "ACTIVE", db=mock_db, reason="payment_confirmed"
        )
        assert result is True
        assert fake_agent.status == "ACTIVE"
        assert fake_agent.is_active is True

    @pytest.mark.asyncio
    async def test_archived_is_terminal(self, fake_agent, mock_db):
        from app.services.agent_state_machine import AgentStateMachine, InvalidAgentTransition

        fake_agent.status = "ARCHIVED"
        result = await AgentStateMachine.transition(
            fake_agent, "ACTIVE", db=mock_db, raise_on_invalid=False
        )
        assert result is False  # Must not apply
        assert fake_agent.status == "ARCHIVED"

        with pytest.raises(InvalidAgentTransition):
            await AgentStateMachine.transition(
                fake_agent, "ACTIVE", db=mock_db, raise_on_invalid=True
            )

    @pytest.mark.asyncio
    async def test_idempotent_same_state(self, fake_agent, mock_db):
        from app.services.agent_state_machine import AgentStateMachine

        fake_agent.status = "ACTIVE"
        result = await AgentStateMachine.transition(
            fake_agent, "ACTIVE", db=mock_db
        )
        assert result is True  # Idempotent — not an error

    @pytest.mark.asyncio
    async def test_expired_cannot_become_active(self, fake_agent, mock_db):
        from app.services.agent_state_machine import AgentStateMachine

        fake_agent.status = "EXPIRED"
        result = await AgentStateMachine.transition(
            fake_agent, "ACTIVE", db=mock_db
        )
        assert result is False  # EXPIRED → ACTIVE is not allowed


# ===========================================================================
# Phase 5 — Redis Failure Graceful Degradation
# ===========================================================================

class TestRedisDegradation:
    """Verify the system operates correctly without Redis."""

    @pytest.mark.asyncio
    async def test_token_budget_allows_when_redis_down(self, mock_db):
        from app.services.session_billing_service import SessionBillingService

        mock_memory = AsyncMock()
        # Redis is None — must default to True (allow all)
        svc = SessionBillingService(db=mock_db, memory_manager=mock_memory, redis_client=None)
        result = await svc.check_token_budget("tenant-123")
        assert result is True

    @pytest.mark.asyncio
    async def test_record_token_usage_noop_without_redis(self, mock_db):
        from app.services.session_billing_service import SessionBillingService

        mock_memory = AsyncMock()
        svc = SessionBillingService(db=mock_db, memory_manager=mock_memory, redis_client=None)
        # Must not raise
        await svc.record_token_usage("tenant-123", 500)

    @pytest.mark.asyncio
    async def test_fallback_counter_returns_zero_without_redis(self, mock_db):
        from app.services.playbook_handler import PlaybookHandler

        mock_llm = AsyncMock()
        handler = PlaybookHandler(db=mock_db, llm_client=mock_llm, redis_client=None)
        count = await handler.increment_fallback_counter("session-123")
        assert count == 0
