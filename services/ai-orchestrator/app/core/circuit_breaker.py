"""
Circuit Breaker — Redis-backed, shared across all worker processes.
====================================================================
Implements the classic three-state automaton:
  CLOSED  → normal operation (all calls pass through)
  OPEN    → fast-fail (calls immediately raise CircuitOpenError)
  HALF_OPEN → probe phase (one trial call allowed)

State is persisted in Redis so ALL uvicorn workers share a single view of
circuit state — essential for multi-process deployments.

Usage:
    from app.core.circuit_breaker import CircuitBreaker, CircuitOpenError

    cb = CircuitBreaker(
        name="llm_gemini",
        redis=redis_client,
        failure_threshold=5,      # trip after 5 failures in window
        recovery_timeout=30,      # try again after 30 s
        half_open_max_calls=1,    # allow 1 probe in HALF_OPEN
    )

    try:
        response = await cb.call(my_async_fn, *args, **kwargs)
    except CircuitOpenError:
        return _fallback_response()
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Coroutine, Optional

import structlog

logger = structlog.get_logger(__name__)


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit is OPEN."""

    def __init__(self, name: str):
        super().__init__(f"Circuit breaker '{name}' is OPEN — call rejected.")
        self.name = name


_STATE_CLOSED = "CLOSED"
_STATE_OPEN = "OPEN"
_STATE_HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """
    Redis-backed circuit breaker.

    Parameters
    ----------
    name:
        Unique identifier (used as Redis key prefix).
    redis:
        Async Redis client.  If None, the breaker degrades to a no-op
        (all calls pass through) — safe for local dev without Redis.
    failure_threshold:
        Number of failures in *window_seconds* before tripping OPEN.
    recovery_timeout:
        Seconds to remain OPEN before moving to HALF_OPEN.
    half_open_max_calls:
        Maximum concurrent probe calls allowed in HALF_OPEN state.
    window_seconds:
        Sliding window for counting failures (default: 60 s).
    """

    def __init__(
        self,
        name: str,
        redis=None,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        half_open_max_calls: int = 1,
        window_seconds: int = 60,
    ):
        self.name = name
        self.redis = redis
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.window_seconds = window_seconds

        # Redis key prefixes
        self._state_key = f"cb:{name}:state"
        self._fail_count_key = f"cb:{name}:failures"
        self._open_at_key = f"cb:{name}:open_at"
        self._half_open_calls_key = f"cb:{name}:half_open_calls"

        # In-process fallback state — used when Redis is unavailable.
        # Provides single-process protection during Redis outages so the
        # circuit still trips instead of letting every LLM call time out.
        self._local_lock: asyncio.Lock = asyncio.Lock()
        self._local_failures: int = 0
        self._local_open_until: float = 0.0  # epoch; 0 means CLOSED
        self._local_window_start: float = time.time()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def call(
        self,
        fn: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute *fn* guarded by the circuit breaker.

        Raises
        ------
        CircuitOpenError
            When the circuit is OPEN (or HALF_OPEN and probe slots exhausted).
        """
        state = await self._get_state()

        if state == _STATE_OPEN:
            # Check if recovery timeout has elapsed → HALF_OPEN
            if await self._should_try_recovery():
                await self._set_state(_STATE_HALF_OPEN)
                state = _STATE_HALF_OPEN
            else:
                from app.core.metrics import LLM_CIRCUIT_OPENS
                try:
                    LLM_CIRCUIT_OPENS.labels(provider=self.name).inc()
                except Exception:
                    pass
                raise CircuitOpenError(self.name)

        if state == _STATE_HALF_OPEN:
            probe_allowed = await self._claim_half_open_slot()
            if not probe_allowed:
                raise CircuitOpenError(self.name)

        try:
            result = await fn(*args, **kwargs)
            await self._on_success()
            return result
        except asyncio.TimeoutError:
            await self._on_failure("timeout")
            raise
        except CircuitOpenError:
            raise
        except Exception as exc:
            await self._on_failure(type(exc).__name__)
            raise

    async def get_state(self) -> str:
        """Return the current circuit state string (CLOSED/OPEN/HALF_OPEN)."""
        return await self._get_state()

    async def reset(self) -> None:
        """Force-close the circuit — for use in tests / admin endpoints."""
        await self._set_state(_STATE_CLOSED)
        if self.redis:
            try:
                await self.redis.delete(
                    self._fail_count_key,
                    self._open_at_key,
                    self._half_open_calls_key,
                )
            except Exception:
                pass
        logger.info("circuit_breaker_forced_reset", name=self.name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_state(self) -> str:
        if self.redis is None:
            return await self._local_get_state()
        try:
            raw = await self.redis.get(self._state_key)
            return (raw or _STATE_CLOSED)
        except Exception:
            # Redis is down — fall back to in-process state so the breaker
            # can still trip if the LLM is also degraded (cascade prevention).
            return await self._local_get_state()

    async def _local_get_state(self) -> str:
        """Return circuit state from in-process counters (Redis-unavailable path)."""
        async with self._local_lock:
            if self._local_open_until > time.time():
                return _STATE_OPEN
            if self._local_open_until > 0:
                # Recovery timeout elapsed → probe
                self._local_open_until = 0.0
                return _STATE_HALF_OPEN
            return _STATE_CLOSED

    async def _set_state(self, state: str) -> None:
        if self.redis is None:
            return
        try:
            ttl = self.recovery_timeout * 4  # Auto-expire stale state
            await self.redis.setex(self._state_key, ttl, state)
            logger.info("circuit_breaker_state_change", name=self.name, new_state=state)
        except Exception as exc:
            logger.warning("circuit_breaker_state_write_failed", name=self.name, error=str(exc))

    async def _on_success(self) -> None:
        if self.redis is None:
            await self._local_reset()
            return

        state = await self._get_state()
        if state == _STATE_HALF_OPEN:
            # Probe succeeded → close circuit
            await self._set_state(_STATE_CLOSED)
            try:
                await self.redis.delete(
                    self._fail_count_key,
                    self._open_at_key,
                    self._half_open_calls_key,
                )
            except Exception:
                pass
        elif state == _STATE_CLOSED:
            # Success in CLOSED: reset failure counter incrementally
            try:
                await self.redis.delete(self._fail_count_key)
            except Exception:
                await self._local_reset()

    async def _on_failure(self, error_type: str) -> None:
        logger.warning(
            "circuit_breaker_failure_recorded",
            name=self.name,
            error_type=error_type,
        )

        if self.redis is None:
            await self._local_record_failure()
            return

        state = await self._get_state()
        if state == _STATE_HALF_OPEN:
            # Probe failed → back to OPEN
            await self._set_state(_STATE_OPEN)
            try:
                await self.redis.setex(self._open_at_key, self.recovery_timeout * 4, str(time.time()))
            except Exception:
                pass
            return

        try:
            failure_count = await self.redis.incr(self._fail_count_key)
            await self.redis.expire(self._fail_count_key, self.window_seconds)

            if failure_count >= self.failure_threshold:
                await self._set_state(_STATE_OPEN)
                await self.redis.setex(
                    self._open_at_key,
                    self.recovery_timeout * 4,
                    str(time.time()),
                )
                logger.error(
                    "circuit_breaker_tripped_open",
                    name=self.name,
                    failure_count=failure_count,
                    threshold=self.failure_threshold,
                )
        except Exception as exc:
            logger.warning("circuit_breaker_failure_count_error", name=self.name, error=str(exc))
            # Redis write failed — maintain local fallback counter
            await self._local_record_failure()

    async def _local_record_failure(self) -> None:
        """Increment the in-process failure counter and trip if threshold reached."""
        async with self._local_lock:
            now = time.time()
            # Reset window if expired
            if now - self._local_window_start >= self.window_seconds:
                self._local_failures = 0
                self._local_window_start = now
            self._local_failures += 1
            if self._local_failures >= self.failure_threshold:
                self._local_open_until = now + self.recovery_timeout
                self._local_failures = 0
                logger.error(
                    "circuit_breaker_tripped_open_local",
                    name=self.name,
                    detail="Redis unavailable — in-process fallback tripped",
                )

    async def _local_reset(self) -> None:
        """Reset in-process state on success (called when Redis is unavailable)."""
        async with self._local_lock:
            self._local_failures = 0
            self._local_open_until = 0.0
            self._local_window_start = time.time()

    async def _should_try_recovery(self) -> bool:
        if self.redis is None:
            return True
        try:
            open_at_raw = await self.redis.get(self._open_at_key)
            if open_at_raw is None:
                return True
            open_at = float(open_at_raw)
            return (time.time() - open_at) >= self.recovery_timeout
        except Exception:
            return True

    async def _claim_half_open_slot(self) -> bool:
        """Atomically claim one HALF_OPEN probe slot. Returns True if granted."""
        if self.redis is None:
            return True
        try:
            count = await self.redis.incr(self._half_open_calls_key)
            await self.redis.expire(self._half_open_calls_key, self.recovery_timeout * 2)
            return count <= self.half_open_max_calls
        except Exception:
            return True  # Fail-open
