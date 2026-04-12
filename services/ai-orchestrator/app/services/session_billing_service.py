import uuid
import time
import structlog
from datetime import datetime, date, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, text

from app.models.agent import Agent, Session as AgentSession, Message, AgentAnalytics, AgentPlaybook
from app.schemas.chat import ChatResponse
from app.core.config import settings

logger = structlog.get_logger(__name__)

class SessionBillingService:
    _DAILY_TOKEN_LIMIT = 2_000_000

    def __init__(self, db: AsyncSession, memory_manager, redis_client=None):
        self.db = db
        self.redis = redis_client
        self.memory = memory_manager
        self.session_expiry_minutes = getattr(settings, "SESSION_EXPIRY_MINUTES", 30)
        self.session_expiry_warning_minutes = getattr(settings, "SESSION_EXPIRY_WARNING_MINUTES", 5)

    def check_session_expiry(self, session: AgentSession) -> Optional[ChatResponse]:
        if session.is_expired(self.session_expiry_minutes):
            session.close()
            logger.info("session_auto_closed", session_id=session.id, reason="inactivity_timeout")
            return ChatResponse(
                session_id=session.id,
                message="Your session has expired due to inactivity. Please start a new session to continue.",
                tool_calls_made=[],
                suggested_actions=["Start new session"],
                escalate_to_human=False,
                latency_ms=0,
                tokens_used=0,
                session_status="closed",
            )
        session.touch()
        return None

    def get_session_status_info(self, session: AgentSession) -> dict:
        minutes_left = session.minutes_until_expiry(self.session_expiry_minutes)
        is_warning = minutes_left <= self.session_expiry_warning_minutes and minutes_left > 0
        return {
            "session_status": session.status,
            "minutes_until_expiry": round(minutes_left, 1),
            "expiry_warning": is_warning,
            "turn_count": session.turn_count,
        }

    async def maybe_send_greeting(self, agent: Agent, session: AgentSession, playbook: Optional[AgentPlaybook]) -> Optional[str]:
        count_result = await self.db.execute(
            select(func.count()).select_from(Message).where(
                Message.session_id == session.id
            )
        )
        msg_count = count_result.scalar() or 0
        if msg_count > 0:
            return None

        agent_cfg = agent.agent_config or {}
        is_voice = (
            agent.voice_enabled
            or getattr(agent, "channel", None) == "voice"
            or agent_cfg.get("channel") == "voice"
        )

        if is_voice:
            # For voice agents:
            # 1. Prefer a pre-generated audio URL (voice_greeting_url) — the client
            #    plays the file directly without any new TTS call.
            # 2. Fall back to the cached text greeting (computed from supported_languages).
            #    The client TTS engine speaks it verbatim.
            # 3. If neither is set, fall back to a generic default greeting.
            voice_greeting_url = agent_cfg.get("voice_greeting_url")
            if voice_greeting_url:
                # Use the greeting_message text as the conversation record, but tag
                # it with the pre-generated audio URL so the client can play the file.
                greeting_text = agent_cfg.get("greeting_message") or ""
                # Store the audio URL in session metadata so the voice client knows
                # to play the pre-generated file instead of running live TTS.
                new_meta = dict(session.metadata_ or {})
                new_meta["_voice_greeting_url"] = voice_greeting_url
                if agent_cfg.get("ivr_language_url"):
                    new_meta["_ivr_language_url"] = agent_cfg["ivr_language_url"]
                session.metadata_ = new_meta

                if not greeting_text:
                    # No text for context — derive a generic placeholder
                    greeting_text = f"[Pre-generated greeting audio: {voice_greeting_url}]"
                greeting = greeting_text
            else:
                # No pre-generated file — use cached text computed from supported_languages.
                from app.guardrails.voice_agent_guardrails import get_or_compute_voice_strings
                greeting, _, _ = await get_or_compute_voice_strings(self.db, agent)

            # Ensure voice agents always have a greeting (platform requirement).
            if not greeting:
                greeting = f"Thank you for calling. How can I assist you today?"
                logger.warning(
                    "voice_agent_missing_greeting_fallback",
                    agent_id=str(agent.id),
                )
        else:
            greeting = agent_cfg.get("greeting_message") or getattr(agent, "greeting_message", None)

        if not greeting:
            return None

        self.db.add(Message(
            session_id=session.id,
            tenant_id=session.tenant_id,
            role="assistant",
            content=greeting,
            tokens_used=0,
            latency_ms=0,
        ))
        await self.memory.add_to_short_term_memory(
            session.id, {"role": "assistant", "content": greeting}
        )

        # Mark session as greeting-only until the first real user message arrives.
        # If the caller disconnects before sending a message, turn_count stays 0
        # and update_analytics is never called — so no billing occurs.
        # This flag is read by the orchestrator to gate the is_new_session flag.
        new_meta = dict(session.metadata_ or {})
        new_meta["_greeting_only"] = True
        session.metadata_ = new_meta

        return greeting

    async def update_analytics(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        tokens: int,
        latency_ms: int,
        tool_count: int = 0,
        escalated: bool = False,
        completed: bool = False,
        voice_minutes: float = 0.0,
        is_new_session: bool = False,
        chat_units: int = 0,
    ) -> None:
        try:
            today = date.today()
            result = await self.db.execute(
                select(AgentAnalytics).where(
                    and_(
                        AgentAnalytics.tenant_id == tenant_id,
                        AgentAnalytics.agent_id == agent_id,
                        AgentAnalytics.date == today,
                    )
                )
            )
            analytics = result.scalar_one_or_none()

            if analytics is None:
                analytics = AgentAnalytics(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    date=today,
                    total_sessions=1 if is_new_session else 0,
                    total_messages=1,
                    avg_response_latency_ms=float(latency_ms),
                    total_tokens_used=tokens,
                    estimated_cost_usd=self.estimate_cost(tokens),
                    tool_executions=tool_count,
                    escalations=1 if escalated else 0,
                    successful_completions=1 if completed else 0,
                    total_chat_units=chat_units,
                    total_voice_minutes=voice_minutes,
                )
                self.db.add(analytics)
            else:
                analytics.total_messages += 1
                analytics.total_tokens_used += tokens
                analytics.estimated_cost_usd += self.estimate_cost(tokens)
                analytics.tool_executions += tool_count
                analytics.total_chat_units += chat_units
                analytics.total_voice_minutes += voice_minutes
                if is_new_session:
                   analytics.total_sessions += 1
                if escalated:
                    analytics.escalations += 1
                if completed:
                    analytics.successful_completions += 1
                n = analytics.total_messages
                analytics.avg_response_latency_ms = (
                    (analytics.avg_response_latency_ms * (n - 1) + latency_ms) / n
                )

            # --- Sync with TenantUsage (Tenant level aggregated counters) ---
            # This ensures the Billing page shows the correct total and overage
            usage_query = text("""
                UPDATE tenant_usage 
                SET current_month_messages = current_month_messages + 1,
                    current_month_sessions = current_month_sessions + :session_increment,
                    current_month_tokens = current_month_tokens + :tokens,
                    current_month_voice_minutes = current_month_voice_minutes + :voice_minutes,
                    current_month_chat_units = current_month_chat_units + :chat_units,
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS UUID)
            """)
            await self.db.execute(usage_query, {
                "tokens": tokens,
                "voice_minutes": voice_minutes,
                "chat_units": chat_units,
                "tenant_id": str(tenant_id),
                "session_increment": 1 if is_new_session else 0
            })
            
            # The calling orchestrator handles db.commit() to ensure atomicity.
        except Exception as exc:
            logger.error("analytics_update_error", error=str(exc))

    @staticmethod
    def estimate_cost(tokens: int) -> float:
        return (tokens / 1000) * 0.0001

    async def check_token_budget(self, tenant_id: str) -> bool:
        if self.redis is None:
            return True
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"tenant:{tenant_id}:token_budget:{today}"
        try:
            used = await self.redis.get(key)
            return int(used or 0) < self._DAILY_TOKEN_LIMIT
        except Exception:
            return True

    async def record_token_usage(self, tenant_id: str, tokens: int) -> None:
        if self.redis is None or tokens <= 0:
            return
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"tenant:{tenant_id}:token_budget:{today}"
        try:
            pipe = self.redis.pipeline()
            pipe.incrby(key, tokens)
            pipe.expire(key, 86400 * 2)
            await pipe.execute()
        except Exception:
            pass

    @staticmethod
    def extract_suggested_actions(response: str, intent: str) -> list[str]:
        # Minimal stub based on old Orchestrator parsing
        return []
