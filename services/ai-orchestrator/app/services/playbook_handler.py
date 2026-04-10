import time
import json
import asyncio
import uuid
import structlog
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.agent import Agent, AgentPlaybook, Session as AgentSession, Message, PlaybookExecution
from app.schemas.chat import ChatResponse
from app.services.llm_client import LLMClient
from app.services.session_state_machine import SessionStateMachine

logger = structlog.get_logger(__name__)

_FALLBACK_COUNTER_PREFIX = "session:fallbacks:"
_FALLBACK_ESCALATION_THRESHOLD = 3
ESCALATION_KEYWORDS = [
    "speak to human", "talk to agent", "real person", "supervisor",
    "I can't help", "beyond my capabilities", "escalating",
]

class PlaybookHandler:
    def __init__(self, db: AsyncSession, llm_client: LLMClient, redis_client=None):
        self.db = db
        self.llm = llm_client
        self.redis = redis_client

    async def route_active_playbook(self, agent_id: str, user_message: str) -> Optional[AgentPlaybook]:
        # Implementation of Redis-backed summary caching
        cache_key = f"agent_playbook_summaries:{agent_id}"
        playbook_summaries = []
        
        if self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    playbook_summaries = json.loads(cached)
            except Exception as e:
                logger.warning("redis_playbook_summaries_load_failed", agent_id=agent_id, error=str(e))

        if not playbook_summaries:
            result = await self.db.execute(
                select(AgentPlaybook).where(
                    AgentPlaybook.agent_id == uuid.UUID(agent_id),
                    AgentPlaybook.is_active.is_(True),
                )
            )
            playbooks = list(result.scalars().all())
            if not playbooks:
                return None
            
            playbook_summaries = [
                {"id": str(p.id), "name": p.name, "description": p.description or ""}
                for p in playbooks
            ]
            
            if self.redis:
                try:
                    await self.redis.setex(cache_key, 3600, json.dumps(playbook_summaries))
                except Exception as e:
                    logger.warning("redis_playbook_summaries_cache_failed", agent_id=agent_id, error=str(e))

        if len(playbook_summaries) == 1:
            # Still load the full object for the caller
            result = await self.db.execute(select(AgentPlaybook).where(AgentPlaybook.id == uuid.UUID(playbook_summaries[0]["id"])))
            return result.scalar_one_or_none()

        system_prompt = (
            "You are a strict semantic intent router. Analyze the user's message and select the single best playbook ID to handle it. "
            "Respond ONLY with the exact UUID of the winning playbook. If no playbook is a good match, respond ONLY with the word 'none'.\n\n"
            "AVAILABLE PLAYBOOKS:\n"
        )
        for p in playbook_summaries:
            system_prompt += f"ID: {p['id']}\nName: {p['name']}\nDescription: {p['description']}\n\n"
            
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        try:
            response = await self.llm.complete(messages=messages, max_tokens=50, stream=False)
            content = response.content.strip()
            
            for p in playbook_summaries:
                if p["id"] in content:
                    logger.info("intent_routed", playbook_id=p["id"], playbook_name=p["name"])
                    result = await self.db.execute(select(AgentPlaybook).where(AgentPlaybook.id == uuid.UUID(p["id"])))
                    return result.scalar_one_or_none()
                    
            logger.info("intent_routed_none", raw_selection=content)
        except Exception as e:
            logger.warning("intent_routing_failed", error=str(e))
            
        return await self.get_default_playbook(agent_id)

    async def get_default_playbook(self, agent_id: str) -> Optional[AgentPlaybook]:
        # Check cache/DB for "General Chat" or default flag
        result = await self.db.execute(
            select(AgentPlaybook).where(
                AgentPlaybook.agent_id == uuid.UUID(agent_id),
                AgentPlaybook.name == "General Chat",
                AgentPlaybook.is_active.is_(True),
            )
        )
        playbook = result.scalar_one_or_none()
        
        if playbook:
            return playbook
            
        result = await self.db.execute(
            select(AgentPlaybook).where(
                AgentPlaybook.agent_id == uuid.UUID(agent_id),
                AgentPlaybook.is_default.is_(True),
                AgentPlaybook.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def ensure_playbook_execution(self, agent_id: str, session_id: str, playbook: Optional[AgentPlaybook]) -> Tuple[Optional[PlaybookExecution], dict]:
        if not playbook:
            return None, {}
        
        pb_exec_res = await self.db.execute(
            select(PlaybookExecution).where(
                PlaybookExecution.session_id == session_id,
                PlaybookExecution.playbook_id == str(playbook.id),
                PlaybookExecution.status == "active"
            )
        )
        playbook_exec = pb_exec_res.scalar_one_or_none()
        if not playbook_exec:
            res = await self.db.execute(select(AgentSession.tenant_id).where(AgentSession.id == session_id))
            tenant_id = res.scalar() or uuid.uuid4()
            
            playbook_exec = PlaybookExecution(
                session_id=session_id,
                playbook_id=str(playbook.id),
                tenant_id=tenant_id,
                # B15 FIX: PlaybookExecution.agent_id is UUID — must not pass string
                agent_id=uuid.UUID(agent_id) if isinstance(agent_id, str) else agent_id,
                status="active",
                variables={}
            )
            self.db.add(playbook_exec)
        
        return playbook_exec, playbook_exec.variables or {}

    def is_fallback_response(self, response: str, playbook: Optional[AgentPlaybook]) -> bool:
        fallback_phrases = [
            "i don't know", "i'm not sure", "i cannot help",
            "i'm unable to", "beyond my", "i don't have information",
        ]
        r = response.lower()
        if any(phrase in r for phrase in fallback_phrases):
            return True
        
        if playbook and playbook.config:
            fallback_res = playbook.config.get("fallback_response", "")
            if fallback_res and fallback_res.strip().lower() in r:
                return True
        return False

    async def increment_fallback_counter(self, session_id: str) -> int:
        if self.redis is None:
            return 0
        key = f"{_FALLBACK_COUNTER_PREFIX}{session_id}"
        try:
            count = await self.redis.incr(key)
            await self.redis.expire(key, 3600)
            return int(count)
        except Exception:
            return 0

    async def reset_fallback_counter(self, session_id: str) -> None:
        if self.redis is None:
            return
        key = f"{_FALLBACK_COUNTER_PREFIX}{session_id}"
        try:
            await self.redis.delete(key)
        except Exception:
            pass

    async def should_escalate(self, agent: Agent, response: str, messages: list) -> bool:
        escalation_config = (agent.agent_config or {}).get("escalation_config", {}) or {}
        if not escalation_config.get("escalate_to_human", False):
            return False

        response_lower = response.lower()
        for keyword in ESCALATION_KEYWORDS:
            if keyword.lower() in response_lower:
                return True

        user_messages = [
            m["content"] for m in messages
            if m.get("role") == "user"
        ][-3:]

        frustration_count = 0
        frustration_signals = ["again", "still", "not working", "doesn't help", "useless", "terrible"]
        for msg in user_messages:
            for signal in frustration_signals:
                if signal in msg.lower():
                    frustration_count += 1

        return frustration_count >= 2

    async def build_escalation_response(
        self,
        agent: Agent,
        session: AgentSession,
        user_message: str,
        start_time: float,
    ) -> ChatResponse:
        escalation_config = (agent.agent_config or {}).get("escalation_config", {}) or {}
        escalation_number = escalation_config.get("escalation_number", "")
        chat_enabled = bool(escalation_config.get("chat_enabled", False))
        chat_agent_name = escalation_config.get("chat_agent_name", "our support team")
        channel = (session.channel or "text").lower()

        if channel == "voice":
            if escalation_number:
                message = "Transferring you to a human agent now — please hold."
                action = "phone_transfer"
                SessionStateMachine.escalate(session, reason="voice_escalation_number")
            elif chat_enabled:
                message = (
                    "I don't have a direct phone transfer set up, but I can switch you "
                    "to our live chat support. Would you like me to do that?"
                )
                action = "offer_chat_switch"
            else:
                message = "Connecting you with a human agent now — please hold."
                action = "phone_transfer"
                SessionStateMachine.escalate(session, reason="voice_escalation_no_number")
        elif chat_enabled:
            message = (
                f"I'm transferring you to {chat_agent_name} right now. "
                f"One of our agents will be with you shortly."
            )
            action = "chat_handoff"
            SessionStateMachine.escalate(session, reason="chat_handoff")
            await self.fire_connector(
                escalation_config=escalation_config,
                agent=agent,
                session=session,
                trigger_message=user_message,
            )
        else:
            # B2 FIX: Build a fresh dict so MutableDict tracker sees the change
            metadata = dict(session.metadata_ or {})
            metadata["_escalation_state"] = "collecting_info"
            session.metadata_ = metadata
            message = (
                "I'd be happy to connect you with a human agent. "
                "To arrange a callback, could you share your name and phone number?"
            )
            action = "collect_info"

        latency_ms = int((time.monotonic() - start_time) * 1000)

        self.db.add(Message(
            session_id=session.id, tenant_id=session.tenant_id,
            role="user", content=user_message, tokens_used=0, latency_ms=0,
        ))
        self.db.add(Message(
            session_id=session.id, tenant_id=session.tenant_id,
            role="assistant", content=message,
            tokens_used=0, latency_ms=latency_ms,
        ))

        return ChatResponse(
            session_id=session.id,
            message=message,
            tool_calls_made=[],
            suggested_actions=[],
            escalate_to_human=action not in ("collect_info", "offer_chat_switch"),
            escalation_action=action,
            latency_ms=latency_ms,
            tokens_used=0,
        )

    async def handle_escalation_info_collection(
        self,
        agent: Agent,
        session: AgentSession,
        user_message: str,
        start_time: float,
        state: str,
        metadata: dict,
    ) -> ChatResponse:
        import re

        latency_ms = int((time.monotonic() - start_time) * 1000)
        action: Optional[str] = None
        message: str = ""
        confirmed: bool = False

        if state == "collecting_info":
            phone_match = re.search(r'(\+?[\d][\d\s\-\(\)\.]{5,}\d)', user_message)
            phone = phone_match.group(1).strip() if phone_match else None

            raw_name = user_message[:phone_match.start()].strip().rstrip(',') if phone_match else user_message.strip()
            name = raw_name if raw_name and 2 <= len(raw_name) <= 60 and not re.fullmatch(r'[\d\s\-\(\)\+]+', raw_name) else None

            if name and phone:
                # B2 FIX: Always assign a fresh dict so MutableDict registers the change
                session.metadata_ = {**metadata, "_escalation_state": "confirming_info",
                            "_escalation_name": name, "_escalation_phone": phone}
                message = (
                    f"Got it! Just to confirm I have the right details:\n"
                    f"• Name: {name}\n"
                    f"• Phone: {phone}\n\n"
                    f"Shall I go ahead and arrange the callback? (Yes / No)"
                )
                action = "confirm_info"
            elif phone and not name:
                session.metadata_ = {**metadata, "_escalation_phone": phone}
                message = "Thanks! And could I get your name so the agent knows who they're calling?"
                action = "collect_info"
            elif name and not phone:
                session.metadata_ = {**metadata, "_escalation_name": name}
                message = f"Thanks, {name}! And what's the best phone number to reach you?"
                action = "collect_info"
            else:
                message = (
                    "I just need your name and phone number to arrange a callback. "
                    "For example: 'Alex Johnson, +1 555-123-4567'"
                )
                action = "collect_info"

        elif state == "confirming_info":
            name = metadata.get("_escalation_name", "")
            phone = metadata.get("_escalation_phone", "")
            confirmed = any(
                w in user_message.lower()
                for w in ("yes", "yeah", "yep", "yup", "correct", "sure", "ok", "okay", "proceed", "confirm", "please")
            )

            if confirmed:
                # B2 FIX: fresh dict assignment for MutableDict tracking
                session.metadata_ = {k: v for k, v in metadata.items() if not k.startswith("_escalation_")}
                SessionStateMachine.escalate(session, reason="callback_confirmed")

                escalation_config_ref = (agent.agent_config or {}).get("escalation_config", {}) or {}
                escalation_number = escalation_config_ref.get("escalation_number", "")
                
                message = (
                    f"Perfect — I've notified our team. An agent will call you "
                    f"at {phone} shortly, {name}."
                )
                if escalation_number:
                    message += f"\n\nYou can also reach us directly at {escalation_number}."
                action = "phone_callback_scheduled"

                await self.fire_connector(
                    escalation_config=escalation_config_ref,
                    agent=agent,
                    session=session,
                    trigger_message=user_message,
                    contact_name=name,
                    contact_phone=phone,
                )
            else:
                session.metadata_ = {k: v for k, v in metadata.items() if not k.startswith("_escalation_")}
                message = "No problem — I've cancelled that. Is there anything else I can help you with?"
                action = None

        if not message:
            # Fallback if somehow state is invalid or loop closed
            session.metadata_ = {k: v for k, v in metadata.items() if not k.startswith("_escalation_")}
            SessionStateMachine.escalate(session, reason="escalation_info_collection_fallback")
            message = "I'll connect you with a human agent right away. Please hold."
            action = "phone_transfer"

        self.db.add(Message(
            session_id=session.id, tenant_id=session.tenant_id,
            role="user", content=user_message, tokens_used=0, latency_ms=0,
        ))
        self.db.add(Message(
            session_id=session.id, tenant_id=session.tenant_id,
            role="assistant", content=message, tokens_used=0, latency_ms=latency_ms,
        ))

        return ChatResponse(
            session_id=session.id,
            message=message,
            tool_calls_made=[],
            suggested_actions=[],
            escalate_to_human=action in ("phone_callback_scheduled", "phone_transfer", "chat_handoff"),
            escalation_action=action,
            latency_ms=latency_ms,
            tokens_used=0,
        )

    async def fire_connector(
        self,
        escalation_config: dict,
        agent: Agent,
        session: AgentSession,
        trigger_message: str,
        contact_name: str = "",
        contact_phone: str = "",
        contact_email: str = "",
    ) -> None:
        from app.models.agent import EscalationAttempt
        from app.connectors.factory import trigger_connector_with_idempotency, EscalationPayload

        connector_type = (escalation_config.get("connector_type") or "").lower().strip()

        try:
            result = await self.db.execute(
                select(Message)
                .where(Message.session_id == session.id)
                .order_by(Message.created_at.asc())
            )
            msgs = result.scalars().all()
            history = [{"role": m.role, "content": m.content} for m in msgs]
        except Exception:
            history = []

        payload = EscalationPayload(
            tenant_id=str(session.tenant_id),
            session_id=str(session.id),
            agent_name=agent.name or "AscenAI Bot",
            contact_name=contact_name,
            contact_phone=contact_phone,
            contact_email=contact_email,
            history=history,
            trigger_message=trigger_message,
            channel=session.channel or "web",
        )

        attempt = EscalationAttempt(
            tenant_id=session.tenant_id,
            session_id=str(session.id),
            agent_name=agent.name or "AscenAI Bot",
            connector_type=connector_type,
            channel=session.channel or "web",
            contact_name=contact_name or None,
            contact_phone=contact_phone or None,
            contact_email=contact_email or None,
            trigger_message=trigger_message[:1000] if trigger_message else None,
            status="pending",
            payload_snapshot={
                "history_len": len(history),
                "trigger": trigger_message[:200] if trigger_message else "",
            },
        )
        try:
            self.db.add(attempt)
            await self.db.flush()
            attempt_id = str(attempt.id)
        except Exception as exc:
            logger.warning("escalation_attempt_persist_failed", error=str(exc))
            attempt_id = None

        async def _run_and_update():
            try:
                from app.core.database import AsyncSessionLocal
                result = await trigger_connector_with_idempotency(
                    escalation_config, payload, redis=self.redis
                )
                if attempt_id:
                    async with AsyncSessionLocal() as db2:
                        row = await db2.get(EscalationAttempt, attempt_id)
                        if row:
                            if result is None:
                                row.status = "skipped"
                            elif result.ticket_id == "deduplicated":
                                row.status = "deduplicated"
                            elif result.success:
                                row.status = "success"
                                row.ticket_id = result.ticket_id or None
                                row.conversation_url = result.conversation_url or None
                            else:
                                row.status = "failed"
                                row.error_message = result.error[:1000] if result.error else None
                            await db2.commit()
            except Exception as exc:
                logger.error("escalation_background_task_failed", attempt_id=attempt_id, error=str(exc))

        asyncio.create_task(_run_and_update())
