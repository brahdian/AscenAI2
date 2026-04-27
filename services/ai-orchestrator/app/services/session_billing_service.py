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
from app.utils.expansion import resolve_agent_variables
from app.models.variable import AgentVariable
from shared.pii import redact_pii, PIIContext

logger = structlog.get_logger(__name__)

class SessionBillingService:
    _DAILY_TOKEN_LIMIT = 2_000_000

    def __init__(self, db: AsyncSession, memory_manager, redis_client=None):
        self.db = db
        self.redis = redis_client
        self.memory = memory_manager
        self.session_expiry_minutes = getattr(settings, "SESSION_EXPIRY_MINUTES", 30)
        self.session_expiry_warning_minutes = getattr(settings, "SESSION_EXPIRY_WARNING_MINUTES", 5)
        self._pii_ctx = PIIContext() # Reusable ephemeral context for metadata scrubbing

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
        # If the session was initialized via the /init endpoint, the greeting was already
        # surfaced to the client directly. Skip re-emitting it into the DB/memory,
        # which would cause the LLM to regurgitate it at the start of its first response.
        _raw_meta_check = getattr(session, "metadata_", None)
        _meta_check = dict(_raw_meta_check) if isinstance(_raw_meta_check, dict) else {}
        if _meta_check.get("_greeting_sent"):
            return None

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
            # V01: Voice agents prioritize the explicit IVR prompt (Greeting + Menu) if configured.
            ivr_prompt_raw = agent_cfg.get("ivr_language_prompt")
            custom_greeting_raw = agent_cfg.get("greeting_message")
            voice_greeting_url = agent_cfg.get("voice_greeting_url")

            # Fetch variables once (used by all branches below)
            result_vars = await self.db.execute(
                select(AgentVariable).where(AgentVariable.agent_id == agent.id)
            )
            variables = result_vars.scalars().all()

            if ivr_prompt_raw:
                # 1. Custom IVR prompt (contains both greeting and menu)
                greeting = resolve_agent_variables(ivr_prompt_raw, agent, variables, clean=True)
                _raw_meta = getattr(session, "metadata_", None)
                new_meta = dict(_raw_meta) if isinstance(_raw_meta, dict) else {}
                new_meta["_greeting_mode"] = "custom_ivr"
                session.metadata_ = new_meta
                logger.info("voice_greeting_custom_ivr", agent_id=str(agent.id))
            elif voice_greeting_url:
                # 2. Pre-generated audio URL
                greeting_text = custom_greeting_raw or ""
                _raw_meta = getattr(session, "metadata_", None)
                new_meta = dict(_raw_meta) if isinstance(_raw_meta, dict) else {}
                new_meta["_voice_greeting_url"] = voice_greeting_url
                new_meta["_greeting_mode"] = "pre_generated"
                if agent_cfg.get("ivr_language_url"):
                    new_meta["_ivr_language_url"] = agent_cfg["ivr_language_url"]
                session.metadata_ = new_meta

                if not greeting_text:
                    greeting_text = f"[Pre-generated greeting audio: {voice_greeting_url}]"
                greeting = resolve_agent_variables(greeting_text, agent, variables, clean=True)
                logger.info("voice_greeting_pre_generated", agent_id=str(agent.id), url=voice_greeting_url)
            elif custom_greeting_raw:
                # 3. Custom chat greeting + Generated IVR options
                from app.guardrails.voice_agent_guardrails import generate_ivr_language_prompt
                greeting_prefix = resolve_agent_variables(custom_greeting_raw, agent, variables, clean=True)
                ivr_generated = await generate_ivr_language_prompt(self.db, agent_cfg.get("supported_languages"))
                greeting = f"{greeting_prefix} {ivr_generated}".strip()
                
                _raw_meta = getattr(session, "metadata_", None)
                new_meta = dict(_raw_meta) if isinstance(_raw_meta, dict) else {}
                new_meta["_greeting_mode"] = "jit_tts_combined"
                session.metadata_ = new_meta
                logger.info("voice_greeting_jit_combined", agent_id=str(agent.id))
            else:
                # 4. Fallback to full platform-computed multilingual opening
                from app.guardrails.voice_agent_guardrails import get_or_compute_voice_strings
                greeting, _, _ = await get_or_compute_voice_strings(self.db, agent)
                _raw_meta = getattr(session, "metadata_", None)
                new_meta = dict(_raw_meta) if isinstance(_raw_meta, dict) else {}
                new_meta["_greeting_mode"] = "computed"
                session.metadata_ = new_meta
                logger.info("voice_greeting_computed", agent_id=str(agent.id))

            # Ensure voice agents always have a greeting (platform requirement).
            if not greeting:
                greeting = "Thank you for calling. How can I assist you today?"
                logger.warning(
                    "voice_agent_missing_greeting_fallback",
                    agent_id=str(agent.id),
                )
        else:
            greeting_raw = agent_cfg.get("greeting_message") or getattr(agent, "greeting_message", None)
            if greeting_raw:
                # FIX-08: Fetch variables once (text agents had same N+1 pattern)
                result_vars = await self.db.execute(
                    select(AgentVariable).where(AgentVariable.agent_id == agent.id)
                )
                variables = result_vars.scalars().all()
                greeting = resolve_agent_variables(greeting_raw, agent, variables, clean=True)
            else:
                greeting = None

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
        _raw_meta = getattr(session, "metadata_", None)
        new_meta = dict(_raw_meta) if isinstance(_raw_meta, dict) else {}
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
        turn_id: Optional[str] = None,
    ) -> None:
        """
        Atomically upsert one message's contribution into the AgentAnalytics
        daily rollup row using INSERT … ON CONFLICT DO UPDATE.

        Deduplication:
        If a turn_id is provided and currentlyexists in Redis, the increment is skipped
        to prevent double-billing on client retries or orchestrator failures.
        """
        if turn_id and self.redis:
            billing_key = f"billing:processed_turn:{turn_id}"
            already_billed = await self.redis.get(billing_key)
            if already_billed:
                logger.info("billing_skipped_already_processed", turn_id=turn_id)
                return
            # Set with a 24-hour TTL to handle retries within a reasonable window
            await self.redis.setex(billing_key, 86400, "billed")
        try:
            today = date.today()
            estimated_cost = self.estimate_cost(tokens)

            # B21 FIX: Use a single atomic CTE to update both agent_analytics AND tenant_usage.
            # This prevents any possibility of drift between per-agent and per-tenant counters.
            combined_sql = text("""
                WITH upsert_aa AS (
                    INSERT INTO agent_analytics (
                        id, tenant_id, agent_id, date,
                        total_sessions, total_messages,
                        avg_response_latency_ms, total_tokens_used,
                        estimated_cost_usd, tool_executions,
                        escalations, successful_completions,
                        total_chat_units, total_voice_minutes
                    ) VALUES (
                        gen_random_uuid(),
                        CAST(:tenant_id AS UUID),
                        CAST(:agent_id  AS UUID),
                        :today,
                        :session_inc, 1,
                        :latency_ms, :tokens,
                        :cost, :tool_count,
                        :escalation_inc, :completion_inc,
                        :chat_units, :voice_minutes
                    )
                    ON CONFLICT (tenant_id, agent_id, date) DO UPDATE SET
                        total_sessions          = agent_analytics.total_sessions + EXCLUDED.total_sessions,
                        total_messages          = agent_analytics.total_messages + 1,
                        avg_response_latency_ms = (
                            agent_analytics.avg_response_latency_ms * agent_analytics.total_messages + :latency_ms
                        ) / (agent_analytics.total_messages + 1),
                        total_tokens_used       = agent_analytics.total_tokens_used + EXCLUDED.total_tokens_used,
                        estimated_cost_usd      = agent_analytics.estimated_cost_usd + EXCLUDED.estimated_cost_usd,
                        tool_executions         = agent_analytics.tool_executions + EXCLUDED.tool_executions,
                        escalations             = agent_analytics.escalations + EXCLUDED.escalations,
                        successful_completions  = agent_analytics.successful_completions + EXCLUDED.successful_completions,
                        total_chat_units        = agent_analytics.total_chat_units + EXCLUDED.total_chat_units,
                        total_voice_minutes     = agent_analytics.total_voice_minutes + EXCLUDED.total_voice_minutes
                    RETURNING tenant_id
                )
                UPDATE tenant_usage
                SET current_month_messages      = current_month_messages + 1,
                    current_month_sessions      = current_month_sessions + :session_inc,
                    current_month_tokens        = current_month_tokens + :tokens,
                    current_month_voice_minutes = current_month_voice_minutes + :voice_minutes,
                    current_month_chat_units    = current_month_chat_units + :chat_units,
                    updated_at                  = NOW()
                WHERE tenant_id = (SELECT tenant_id FROM upsert_aa LIMIT 1)
            """)
            await self.db.execute(combined_sql, {
                "tenant_id":      str(tenant_id),
                "agent_id":       str(agent_id),
                "today":          today,
                "session_inc":    1 if is_new_session else 0,
                "latency_ms":     float(latency_ms),
                "tokens":         tokens,
                "cost":           estimated_cost,
                "tool_count":     tool_count,
                "escalation_inc": 1 if escalated else 0,
                "completion_inc": 1 if completed else 0,
                "chat_units":     chat_units,
                "voice_minutes":  voice_minutes,
            })

            logger.debug(
                "analytics_upserted",
                tenant_id=str(tenant_id),
                agent_id=str(agent_id),
                date=str(today),
                tokens=tokens,
                latency_ms=latency_ms,
                chat_units=chat_units,
                voice_minutes=voice_minutes,
                is_new_session=is_new_session,
            )
            
            # --- Automated Stripe Revenue Recovery ---
            # Periodically notify the Gateway to check/report overages to Stripe. 
            # We trigger this every time a session hits a 100-unit milestone (approx $1-10 revenue).
            if (chat_units % 100) < chat_units or is_new_session:
                # We use an internal task or fire-and-forget to avoid blocking the turn
                import asyncio
                asyncio.create_task(self._report_overage_to_gateway(tenant_id))
            
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

    async def _report_overage_to_gateway(self, tenant_id: uuid.UUID) -> None:
        """Helper to notify the API Gateway that a tenant's usage has reached a billing milestone."""
        import httpx
        try:
            # api-gateway:8000 is the internal service name in docker-compose
            url = f"http://api-gateway:8000/api/v1/billing/internal/report-overage"
            headers = {
                "X-Internal-Key": getattr(settings, "INTERNAL_API_KEY", ""),
                "X-Tenant-ID": str(tenant_id),
            }
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(url, headers=headers)
        except Exception as e:
            logger.warning("gateway_overage_notification_failed", error=str(e), tenant_id=str(tenant_id))

    @staticmethod
    def extract_suggested_actions(response: str, intent: str) -> list[str]:
        # Minimal stub based on old Orchestrator parsing
        return []
