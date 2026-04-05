import asyncio
import time
import json
import uuid
from typing import AsyncGenerator, Optional
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.config import settings
from app.models.agent import Agent, Session, Message
from app.schemas.chat import ChatResponse, SourceCitation, StreamChatEvent
from app.services import pii_service
from app.services.llm_client import LLMClient, LLMResponse
from app.services.mcp_client import MCPClient
from app.services.memory_manager import MemoryManager
from app.services.intent_detector import IntentDetector

from app.services.guardrail_service import GuardrailService
from app.services.tool_executor_service import ToolExecutionService
from app.services.context_builder_service import ContextBuilderService
from app.services.playbook_handler import PlaybookHandler
from app.services.session_billing_service import SessionBillingService
from app.services.moderation_service import ModerationService, OutputBlockedError

logger = structlog.get_logger(__name__)

MAX_TOOL_ITERATIONS = settings.MAX_TOOL_ITERATIONS
LLM_TIMEOUT_SECONDS: int = getattr(settings, "LLM_TIMEOUT_SECONDS", 30)
_FALLBACK_ESCALATION_THRESHOLD = 3


class Orchestrator:
    """
    Core orchestration engine, refactored to delegate to focused services.
    """
    def __init__(
        self,
        llm_client: LLMClient,
        mcp_client: MCPClient,
        memory_manager: MemoryManager,
        db: AsyncSession,
        redis_client=None,
        moderation_service: Optional[ModerationService] = None,
    ):
        self.llm = llm_client
        self.mcp = mcp_client
        self.memory = memory_manager
        self.db = db
        self.redis = redis_client
        self.intent_detector = IntentDetector()
        self.moderation_service = moderation_service

        # Instantiate Delegates
        self.guardrail_service = GuardrailService(redis_client=self.redis)
        self.tool_executor = ToolExecutionService(db=self.db, mcp=self.mcp, redis_client=self.redis)
        self.context_builder = ContextBuilderService(db=self.db, mcp=self.mcp, redis_client=self.redis)
        self.playbook_handler = PlaybookHandler(db=self.db, llm_client=self.llm, redis_client=self.redis)
        self.billing_service = SessionBillingService(db=self.db, memory_manager=self.memory, redis_client=self.redis)

    async def _llm_complete_with_timeout(self, **kwargs) -> LLMResponse:
        try:
            return await asyncio.wait_for(
                self.llm.complete(**kwargs),
                timeout=LLM_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error("llm_timeout", timeout_s=LLM_TIMEOUT_SECONDS, model=getattr(self.llm, "model", "unknown"))
            from app.services.llm_client import LLMResponse, TokenUsage
            return LLMResponse(
                content="I'm sorry, I'm taking longer than expected to respond. Please try again in a moment.",
                tool_calls=None,
                finish_reason="timeout",
                usage=TokenUsage(),
            )

    # ------------------------------------------------------------------
    # Non-streaming path
    # ------------------------------------------------------------------

    async def process_message(self, agent: Agent, session: Session, user_message: str, stream: bool = False) -> ChatResponse | AsyncGenerator:
        if stream:
            return self.stream_response(agent, session, user_message)

        start_time = time.monotonic()
        tenant_id = str(session.tenant_id)
        session_id = session.id

        expiry_response = self.billing_service.check_session_expiry(session)
        if expiry_response:
            return expiry_response

        user_message = self.guardrail_service.sanitize_user_message(user_message)

        session_meta = dict(session.metadata_ or {})
        escalation_state = session_meta.get("_escalation_state")
        if escalation_state:
            return await self.playbook_handler.handle_escalation_info_collection(
                agent, session, user_message, start_time, escalation_state, session_meta
            )

        emergency_response = self.guardrail_service.check_emergency(user_message, agent)
        if emergency_response:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            self.db.add(Message(session_id=session_id, tenant_id=session.tenant_id, role="user", content=user_message, tokens_used=0, latency_ms=0))
            self.db.add(Message(session_id=session_id, tenant_id=session.tenant_id, role="assistant", content=emergency_response, tokens_used=0, latency_ms=latency_ms))
            session.status = "escalated"
            return ChatResponse(session_id=session_id, message=emergency_response, tool_calls_made=[], suggested_actions=["Call 911"], escalate_to_human=True, latency_ms=latency_ms, tokens_used=0)

        jailbreak_response = self.guardrail_service.check_jailbreak(user_message, agent)
        if jailbreak_response:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            return ChatResponse(session_id=session_id, message=jailbreak_response, tool_calls_made=[], suggested_actions=[], escalate_to_human=False, latency_ms=latency_ms, tokens_used=0)

        intent = self.intent_detector.detect_intent(user_message)
        if self.intent_detector.should_escalate_immediately(user_message):
            return await self.playbook_handler.build_escalation_response(agent, session, user_message, start_time)

        playbook = await self.playbook_handler.route_active_playbook(str(agent.id), user_message)
        playbook_exec, local_vars = await self.playbook_handler.ensure_playbook_execution(str(agent.id), str(session.id), playbook)
        corrections = await self.context_builder.load_corrections(str(agent.id))
        await self.billing_service.maybe_send_greeting(agent, session, playbook)

        guardrails = await self.context_builder.load_guardrails(str(agent.id))
        variables = await self.context_builder.load_variables(str(agent.id), str(playbook.id) if playbook else None)

        block_reason = self.guardrail_service.check_input_guardrails(user_message, guardrails)
        if block_reason:
            block_msg = (guardrails.blocked_message if guardrails else "I'm sorry, I can't help with that.")
            self.db.add(Message(session_id=session_id, tenant_id=session.tenant_id, role="user", content=user_message, guardrail_triggered=block_reason, tokens_used=0, latency_ms=0))
            return ChatResponse(session_id=session_id, message=block_msg, tool_calls_made=[], suggested_actions=[], escalate_to_human=False, latency_ms=int((time.monotonic() - start_time) * 1000), tokens_used=0, guardrail_triggered=block_reason)

        history = await self.memory.get_short_term_memory(session_id)
        summary = await self.memory.get_session_summary(session_id)

        # SECURITY FIX: Always load PII context and pseudonymize if required
        pii_ctx = await self.guardrail_service.get_pii_context(session_id)
        llm_user_message = self.guardrail_service.redact_user_message(user_message, pii_ctx, session_id)

        kb_ids = agent.knowledge_base_ids or []
        context_items = await self.mcp.retrieve_context(
            tenant_id=tenant_id, query=user_message, session_id=session_id, context_types=["knowledge", "history"], knowledge_base_ids=kb_ids if kb_ids else None,
        )

        source_citations = [
            SourceCitation(
                type=item.get("type", "knowledge"), title=item.get("metadata", {}).get("title"), source_url=item.get("metadata", {}).get("source_url"),
                excerpt=(item.get("content", "") or "")[:150], score=float(item.get("score", 1.0)),
                document_id=str(item.get("metadata", {}).get("document_id")) if item.get("metadata", {}).get("document_id") else None,
                chunk_id=str(item.get("metadata", {}).get("chunk_id")) if item.get("metadata", {}).get("chunk_id") else None,
            ) for item in context_items if isinstance(item, dict)
        ]

        customer_profile = {}
        if session.customer_identifier:
            customer_profile = await self.memory.get_long_term_customer_memory(tenant_id, session.customer_identifier)

        session_language = session_meta.get("language")

        # Multilingual: Detect language if auto_detect is ON
        if getattr(agent, "auto_detect_language", False):
            detected_lang = self.intent_detector.detect_language(
                user_message, getattr(agent, "supported_languages", []) or []
            )
            if detected_lang and detected_lang != session_language:
                session_language = detected_lang
                session_meta["language"] = detected_lang
                session.metadata = dict(session_meta) # Persist it

        system_prompt = self.context_builder.build_system_prompt(
            agent=agent, context_items=context_items, customer_profile=customer_profile, intent=intent,
            session_language=session_language, playbook=playbook, corrections=corrections, guardrails=guardrails,
            variables=variables, session_meta=session_meta, local_vars=local_vars
        )

        tool_schemas = await self.context_builder.get_agent_tools_schema(agent, playbook, tenant_id)

        messages = [{"role": "system", "content": system_prompt}]
        if summary:
            messages.append({"role": "system", "content": f"[Conversation summary so far]: {summary}"})
        messages.extend(history)
        messages.append({"role": "user", "content": llm_user_message})

        if not await self.billing_service.check_token_budget(tenant_id):
            return ChatResponse(session_id=session_id, message="I'm temporarily unavailable due to high usage. Please try again later.", tool_calls_made=[], suggested_actions=[], escalate_to_human=False, latency_ms=int((time.monotonic() - start_time) * 1000), tokens_used=0)

        tool_calls_made = []
        total_tokens = 0
        llm_config = agent.llm_config or {}
        temperature = llm_config.get("temperature", 0.7)
        max_tokens = llm_config.get("max_tokens", settings.MAX_RESPONSE_TOKENS)

        final_response = None
        iterations = 0
        system_tools = agent.tools or []
        playbook_tools = playbook.tools or [] if playbook else []
        enabled_tools = list(dict.fromkeys(system_tools + playbook_tools))

        while iterations < MAX_TOOL_ITERATIONS:
            llm_response = await self._llm_complete_with_timeout(messages=messages, tools=tool_schemas if tool_schemas else None, temperature=temperature, max_tokens=max_tokens, stream=False, session_id=session_id)
            total_tokens += llm_response.usage.total_tokens

            if llm_response.finish_reason == "timeout":
                final_response = llm_response.content
                break

            if llm_response.tool_calls:
                iterations += 1
                allowed_calls = self.tool_executor.filter_unauthorized_tool_calls(llm_response.tool_calls, enabled_tools)
                if not allowed_calls:
                    final_response = llm_response.content or "I wasn't able to complete that action."
                    break

                confirmation_prompt = self.tool_executor.requires_confirmation(allowed_calls, user_message, history)
                if confirmation_prompt:
                    final_response = confirmation_prompt
                    break

                if pii_ctx is not None and pii_ctx.has_mappings():
                    for tc in allowed_calls:
                        if isinstance(tc.arguments, dict):
                            tc.arguments = pii_service.restore_dict(tc.arguments, pii_ctx, session_id)

                tool_results = await self.tool_executor.execute_tool_calls(tool_calls=allowed_calls, tenant_id=tenant_id, session_id=session_id)
                tool_results = [{k: self.guardrail_service.scrub_credentials(str(v)) if isinstance(v, str) else v for k, v in r.items()} if isinstance(r, dict) else r for r in tool_results]

                if pii_ctx is not None:
                    _re_anon = []
                    for _r in tool_results:
                        if isinstance(_r, dict):
                            _re_anon.append(pii_service.redact_dict(_r, pii_ctx, session_id))
                        else:
                            _re_anon.append(_r)
                    tool_results = _re_anon

                for tc, result in zip(allowed_calls, tool_results):
                    safe_args = tc.arguments if not pii_ctx else pii_service.redact_dict(tc.arguments, pii_ctx, session_id) if isinstance(tc.arguments, dict) else tc.arguments
                    tool_calls_made.append({"tool": tc.name, "arguments": safe_args, "result": result})

                messages.append({"role": "assistant", "content": llm_response.content or "", "tool_calls": [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in allowed_calls]})
                for tc, result in zip(allowed_calls, tool_results):
                    sanitized_result = self.guardrail_service.sanitize_tool_output(str(result))
                    messages.append({"role": "tool", "name": tc.name, "tool_call_id": tc.id, "content": sanitized_result})
                continue
            else:
                final_response = llm_response.content or ""
                break

        if final_response is None:
            logger.warning("max_tool_iterations_reached", session_id=session_id, iterations=MAX_TOOL_ITERATIONS, agent_id=str(agent.id))
            final_response = llm_response.content or "I wasn't able to fully complete your request."

        # Moderation gate: check LLM output before it reaches the user.
        if self.moderation_service and final_response:
            try:
                await self.moderation_service.check_output(final_response)
            except OutputBlockedError as _obe:
                logger.warning(
                    "llm_output_blocked",
                    session_id=session_id,
                    categories=_obe.categories,
                    reason=_obe.reason,
                )
                final_response = "I'm sorry, I'm not able to help with that."

        latency_ms = int((time.monotonic() - start_time) * 1000)
        receipt = self.tool_executor.build_receipt_summary(tool_calls_made)
        if receipt:
            final_response = final_response.rstrip() + " " + receipt

        pseudo_final_response = final_response

        final_response, guardrail_actions = self.guardrail_service.apply_output_guardrails(final_response, guardrails, pii_ctx, session_id)
        if pii_ctx is not None:
            await self.guardrail_service.save_pii_context(session_id, pii_ctx)

        final_response = self.guardrail_service.check_professional_claims(final_response)
        is_fallback = self.playbook_handler.is_fallback_response(final_response, playbook)

        if is_fallback:
            fallback_count = await self.playbook_handler.increment_fallback_counter(session_id)
            if fallback_count >= _FALLBACK_ESCALATION_THRESHOLD:
                session.status = "escalated"
                final_response = "I've been unable to help with your last few requests. Let me connect you with a human agent."
                pseudo_final_response = final_response
                await self.playbook_handler.reset_fallback_counter(session_id)
        else:
            await self.playbook_handler.reset_fallback_counter(session_id)

        await self.memory.add_to_short_term_memory(session_id, {"role": "user", "content": llm_user_message})
        await self.memory.add_to_short_term_memory(session_id, {"role": "assistant", "content": pseudo_final_response})

        try:
            await self.memory.maybe_summarize(session_id, self.llm)
            if session.customer_identifier:
                await self.memory.extract_and_store_long_term_memory(
                    tenant_id=tenant_id, customer_identifier=session.customer_identifier,
                    conversation_text=f"User: {user_message}\nAssistant: {final_response}",
                    llm_client=self.llm,
                )
        except Exception as _mem_exc:
            logger.warning("memory_post_turn_error", error=str(_mem_exc))

        user_msg = Message(
            session_id=session_id, 
            tenant_id=session.tenant_id, 
            role="user", 
            content=pii_service.redact_for_display(user_message, pii_ctx) if (pii_ctx and guardrails and guardrails.pii_redaction) else user_message, 
            tokens_used=0, 
            latency_ms=0
        )
        assistant_msg = Message(
            session_id=session_id, 
            tenant_id=session.tenant_id, 
            role="assistant", 
            content=pii_service.redact_for_display(final_response, pii_ctx) if (pii_ctx and guardrails and guardrails.pii_redaction) else final_response,
            tool_calls=tool_calls_made if tool_calls_made else None, tokens_used=total_tokens, latency_ms=latency_ms,
            is_fallback=is_fallback, playbook_name=playbook.name if playbook else None,
            sources=json.loads(json.dumps([c.model_dump() for c in source_citations])) if source_citations else [],
        )
        self.db.add(user_msg)
        self.db.add(assistant_msg)

        is_new = (session.turn_count == 0)
        
        # Calculate Chat Unit increment (TC-B01)
        # Rule: 1 Chat point per session floor, then +1 per 10 messages (turns).
        # Turn 1 (count 0->1): +1 unit
        # Turn 11 (count 10->11): +1 unit, etc.
        chat_unit_increment = 0
        if is_new:
            chat_unit_increment = 1
        elif session.turn_count > 0 and (session.turn_count + 1) % 10 == 0:
            chat_unit_increment = 1

        session.turn_count += 1
        await self.billing_service.update_analytics(
            tenant_id=session.tenant_id, 
            agent_id=session.agent_id, 
            tokens=total_tokens, 
            latency_ms=latency_ms, 
            tool_count=len(tool_calls_made),
            is_new_session=is_new,
            chat_units=chat_unit_increment
        )
        await self.billing_service.record_token_usage(tenant_id, total_tokens)

        should_escalate = await self.playbook_handler.should_escalate(agent, final_response, messages)
        if should_escalate:
            session.status = "escalated"

        return ChatResponse(
            session_id=session_id, message=final_response, tool_calls_made=tool_calls_made,
            source_citations=source_citations if source_citations else None,
            suggested_actions=self.billing_service.extract_suggested_actions(final_response, intent),
            escalate_to_human=should_escalate, latency_ms=latency_ms, tokens_used=total_tokens,
            playbook_executed=playbook.name if playbook else None,
            playbook_variables=local_vars if local_vars else None,
            turn_count=session.turn_count, session_status=session.status,
            guardrail_actions=guardrail_actions,
        )

    # ------------------------------------------------------------------
    # Streaming path
    # ------------------------------------------------------------------

    async def stream_response(self, agent: Agent, session: Session, user_message: str) -> AsyncGenerator:
        start_time = time.monotonic()
        tenant_id = str(session.tenant_id)
        session_id = session.id
        tool_calls_made: list = []
        total_tokens = 0

        yield StreamChatEvent(type="started", data={"session_id": session_id}, session_id=session_id)

        user_message = self.guardrail_service.sanitize_user_message(user_message)

        session_meta = dict(session.metadata_ or {})
        escalation_state = session_meta.get("_escalation_state")
        if escalation_state:
            info_collection_response = await self.playbook_handler.handle_escalation_info_collection(
                agent, session, user_message, start_time, escalation_state, session_meta
            )
            yield StreamChatEvent(type="text_delta", data=info_collection_response.message, session_id=session_id)
            yield StreamChatEvent(type="done", data={"session_id": session_id, "latency_ms": info_collection_response.latency_ms, "tokens_used": 0, "escalate_to_human": info_collection_response.escalate_to_human, "escalation_action": info_collection_response.escalation_action}, session_id=session_id)
            return

        emergency_response = self.guardrail_service.check_emergency(user_message, agent)
        if emergency_response:
            session.status = "escalated"
            yield StreamChatEvent(type="text_delta", data=emergency_response, session_id=session_id)
            yield StreamChatEvent(type="done", data={"session_id": session_id, "latency_ms": int((time.monotonic() - start_time) * 1000), "tokens_used": 0, "escalate_to_human": True}, session_id=session_id)
            return

        jailbreak_response = self.guardrail_service.check_jailbreak(user_message, agent)
        if jailbreak_response:
            yield StreamChatEvent(type="text_delta", data=jailbreak_response, session_id=session_id)
            yield StreamChatEvent(type="done", data={"session_id": session_id, "latency_ms": int((time.monotonic() - start_time) * 1000), "tokens_used": 0, "escalate_to_human": False}, session_id=session_id)
            return

        intent = self.intent_detector.detect_intent(user_message)
        if self.intent_detector.should_escalate_immediately(user_message):
            escalation_response = await self.playbook_handler.build_escalation_response(agent, session, user_message, start_time)
            yield StreamChatEvent(type="text_delta", data=escalation_response.message, session_id=session_id)
            yield StreamChatEvent(type="done", data={"session_id": session_id, "latency_ms": escalation_response.latency_ms, "tokens_used": 0, "escalate_to_human": True, "escalation_action": escalation_response.escalation_action}, session_id=session_id)
            return

        playbook = await self.playbook_handler.route_active_playbook(str(agent.id), user_message)
        playbook_exec, local_vars = await self.playbook_handler.ensure_playbook_execution(str(agent.id), session_id, playbook)
        corrections = await self.context_builder.load_corrections(str(agent.id))
        await self.billing_service.maybe_send_greeting(agent, session, playbook)

        guardrails = await self.context_builder.load_guardrails(str(agent.id))
        variables = await self.context_builder.load_variables(str(agent.id), str(playbook.id) if playbook else None)

        block_reason = self.guardrail_service.check_input_guardrails(user_message, guardrails)
        if block_reason:
            block_msg = (guardrails.blocked_message if guardrails else "I'm sorry, I can't help with that.")
            yield StreamChatEvent(type="text_delta", data=block_msg, session_id=session_id)
            yield StreamChatEvent(type="done", data={"session_id": session_id, "latency_ms": int((time.monotonic() - start_time) * 1000), "tokens_used": 0, "escalate_to_human": False, "guardrail_triggered": block_reason}, session_id=session_id)
            return

        history = await self.memory.get_short_term_memory(session_id)
        summary = await self.memory.get_session_summary(session_id)

        stream_pii_ctx = await self.guardrail_service.get_pii_context(session_id)
        llm_user_message = self.guardrail_service.redact_user_message(user_message, stream_pii_ctx, session_id)
        _pii_active = stream_pii_ctx is not None and stream_pii_ctx.has_mappings()

        kb_ids = agent.knowledge_base_ids or []
        context_items = await self.mcp.retrieve_context(
            tenant_id=tenant_id, query=user_message, session_id=session_id, context_types=["knowledge", "history"],
            knowledge_base_ids=kb_ids if kb_ids else None,
        )

        stream_source_citations = [
            SourceCitation(
                type=item.get("type", "knowledge"), title=item.get("metadata", {}).get("title"), source_url=item.get("metadata", {}).get("source_url"),
                excerpt=(item.get("content", "") or "")[:150], score=float(item.get("score", 1.0)),
                document_id=str(item.get("metadata", {}).get("document_id")) if item.get("metadata", {}).get("document_id") else None,
                chunk_id=str(item.get("metadata", {}).get("chunk_id")) if item.get("metadata", {}).get("chunk_id") else None,
            ) for item in context_items if isinstance(item, dict)
        ]

        customer_profile = {}
        if session.customer_identifier:
            customer_profile = await self.memory.get_long_term_customer_memory(tenant_id, session.customer_identifier)

        session_meta = dict(session.metadata_ or {}) if hasattr(session, "metadata_") else {}
        session_language = session_meta.get("language")

        system_prompt = self.context_builder.build_system_prompt(
            agent=agent, context_items=context_items, customer_profile=customer_profile, intent=intent,
            session_language=session_language, playbook=playbook, corrections=corrections, guardrails=guardrails,
            variables=variables, session_meta=session_meta, local_vars=local_vars
        )

        tool_schemas = await self.context_builder.get_agent_tools_schema(agent, playbook, tenant_id)

        latency_ms = int((time.monotonic() - start_time) * 1000)
        
        # Calculate Chat Units and New Session flags (TC-B01)
        is_new = (session.turn_count == 0)
        chat_unit_increment = 0
        if is_new:
            chat_unit_increment = 1
        elif session.turn_count > 0 and (session.turn_count + 1) % 10 == 0:
            chat_unit_increment = 1

        latency_ms = int((time.monotonic() - start_time) * 1000)
        temperature = llm_config.get("temperature", 0.7)
        max_tokens = llm_config.get("max_tokens", settings.MAX_RESPONSE_TOKENS)
        system_tools = agent.tools or []
        playbook_tools = playbook.tools or [] if playbook else []
        enabled_tools = list(dict.fromkeys(system_tools + playbook_tools))

        full_response_text = ""
        iterations = 0
        llm_response = None

        while iterations < MAX_TOOL_ITERATIONS:
            llm_response = await self._llm_complete_with_timeout(
                messages=messages, tools=tool_schemas if tool_schemas else None, temperature=temperature, max_tokens=max_tokens, stream=False, session_id=session_id
            )
            total_tokens += llm_response.usage.total_tokens

            if llm_response.finish_reason == "timeout":
                full_response_text = llm_response.content or "I'm sorry, I'm taking longer than expected."
                break

            if not llm_response.tool_calls:
                full_response_text = llm_response.content or ""
                break

            iterations += 1
            allowed_calls = self.tool_executor.filter_unauthorized_tool_calls(llm_response.tool_calls, enabled_tools)
            if not allowed_calls:
                full_response_text = llm_response.content or "I wasn't able to complete that action."
                break

            confirmation_prompt = self.tool_executor.requires_confirmation(allowed_calls, user_message, history)
            if confirmation_prompt:
                full_response_text = confirmation_prompt
                break

            yield StreamChatEvent(type="tool_call", data={"tools": [{"name": tc.name, "arguments": tc.arguments} for tc in allowed_calls]}, session_id=session_id)

            if stream_pii_ctx is not None and stream_pii_ctx.has_mappings():
                for tc in allowed_calls:
                    if isinstance(tc.arguments, dict):
                        tc.arguments = pii_service.restore_dict(tc.arguments, stream_pii_ctx, session_id)

            tool_results = await self.tool_executor.execute_tool_calls(tool_calls=allowed_calls, tenant_id=tenant_id, session_id=session_id)
            tool_results = [{k: self.guardrail_service.scrub_credentials(str(v)) if isinstance(v, str) else v for k, v in r.items()} if isinstance(r, dict) else r for r in tool_results]

            if stream_pii_ctx is not None:
                _re_anon_s = []
                for _r in tool_results:
                    if isinstance(_r, dict):
                        _re_anon_s.append(pii_service.redact_dict(_r, stream_pii_ctx, session_id))
                    else:
                        _re_anon_s.append(_r)
                tool_results = _re_anon_s

            for tc, result in zip(allowed_calls, tool_results):
                safe_args = tc.arguments if not stream_pii_ctx else pii_service.redact_dict(tc.arguments, stream_pii_ctx, session_id) if isinstance(tc.arguments, dict) else tc.arguments
                tool_calls_made.append({"tool": tc.name, "arguments": safe_args, "result": result})
                yield StreamChatEvent(type="tool_result", data={"tool": tc.name, "result": result}, session_id=session_id)

            messages.append({"role": "assistant", "content": llm_response.content or "", "tool_calls": [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in allowed_calls]})
            for tc, result in zip(allowed_calls, tool_results):
                sanitized_result = self.guardrail_service.sanitize_tool_output(str(result))
                messages.append({"role": "tool", "name": tc.name, "tool_call_id": tc.id, "content": sanitized_result})

        if not full_response_text and llm_response:
            logger.warning("stream_max_tool_iterations_reached", session_id=session_id, iterations=MAX_TOOL_ITERATIONS)
            full_response_text = llm_response.content or "I wasn't able to fully complete your request."

        receipt = self.tool_executor.build_receipt_summary(tool_calls_made)
        if receipt:
            full_response_text = full_response_text.rstrip() + " " + receipt

        pseudo_full_response = full_response_text

        if _pii_active and full_response_text:
            parser = pii_service.create_streaming_parser(stream_pii_ctx, session_id)
            full_response_text = parser.process_chunk(full_response_text) + parser.flush()

        # Apply output guardrails (including PII restoration) BEFORE streaming to client
        full_response_text, stream_guardrail_actions = self.guardrail_service.apply_output_guardrails(full_response_text, guardrails, stream_pii_ctx, session_id)

        words = full_response_text.split(" ")
        for word in words:
            yield StreamChatEvent(type="text_delta", data=word + " ", session_id=session_id)
            await asyncio.sleep(0.01)

        latency_ms = int((time.monotonic() - start_time) * 1000)
        if stream_pii_ctx is not None:
            await self.guardrail_service.save_pii_context(session_id, stream_pii_ctx)

        full_response_text = self.guardrail_service.check_professional_claims(full_response_text)
        is_fallback = self.playbook_handler.is_fallback_response(full_response_text, playbook)

        if is_fallback:
            fallback_count = await self.playbook_handler.increment_fallback_counter(session_id)
            if fallback_count >= _FALLBACK_ESCALATION_THRESHOLD:
                session.status = "escalated"
                full_response_text = "I've been unable to help with your last few requests. Let me connect you with a human agent."
                pseudo_full_response = full_response_text
                await self.playbook_handler.reset_fallback_counter(session_id)
        else:
            await self.playbook_handler.reset_fallback_counter(session_id)

        await self.memory.add_to_short_term_memory(session_id, {"role": "user", "content": llm_user_message})
        await self.memory.add_to_short_term_memory(session_id, {"role": "assistant", "content": pseudo_full_response})

        try:
            await self.memory.maybe_summarize(session_id, self.llm)
            if session.customer_identifier:
                await self.memory.extract_and_store_long_term_memory(
                    tenant_id=tenant_id, customer_identifier=session.customer_identifier,
                    conversation_text=f"User: {user_message}\nAssistant: {full_response_text}",
                    llm_client=self.llm,
                )
        except Exception as _mem_exc:
            logger.warning("stream_memory_post_turn_error", error=str(_mem_exc))

        user_msg_content = pii_service.redact_for_display(user_message, stream_pii_ctx) if stream_pii_ctx else user_message
        assistant_msg_content = pii_service.redact_for_display(full_response_text, stream_pii_ctx) if stream_pii_ctx else full_response_text

        user_msg = Message(session_id=session_id, tenant_id=session.tenant_id, role="user", content=user_msg_content, tokens_used=0, latency_ms=0)
        assistant_msg = Message(
            session_id=session_id, tenant_id=session.tenant_id, role="assistant", content=assistant_msg_content,
            tool_calls=tool_calls_made if tool_calls_made else None, tokens_used=total_tokens, latency_ms=latency_ms,
            is_fallback=is_fallback, playbook_name=playbook.name if playbook else None,
            sources=json.loads(json.dumps([c.model_dump() for c in stream_source_citations])) if stream_source_citations else [],
        )
        self.db.add(user_msg)
        self.db.add(assistant_msg)

        session.turn_count += 1
        await self.billing_service.update_analytics(
            tenant_id=session.tenant_id,
            agent_id=session.agent_id,
            tokens=total_tokens,
            latency_ms=latency_ms,
            tool_count=len(tool_calls_made),
            is_new_session=is_new,
            chat_units=chat_unit_increment
        )
        await self.billing_service.record_token_usage(tenant_id, total_tokens)

        should_escalate = await self.playbook_handler.should_escalate(agent, full_response_text, messages)
        if should_escalate:
            session.status = "escalated"

        if stream_source_citations:
            yield StreamChatEvent(type="sources", data=[c.model_dump() for c in stream_source_citations], session_id=session_id)

        yield StreamChatEvent(
            type="done",
            data={
                "session_id": session_id, "latency_ms": latency_ms, "tokens_used": total_tokens, "tool_calls_made": len(tool_calls_made),
                "escalate_to_human": should_escalate, "guardrail_actions": stream_guardrail_actions, "turn_count": session.turn_count,
            },
            session_id=session_id,
        )

    # ------------------------------------------------------------------
    # Async streaming (non-SSE)
    # ------------------------------------------------------------------

    async def stream_response_async(self, agent: Agent, session: Session, user_message: str) -> ChatResponse:
        start_time = time.monotonic()
        tenant_id = str(session.tenant_id)
        session_id = session.id
        tool_calls_made: list = []
        total_tokens = 0

        user_message = self.guardrail_service.sanitize_user_message(user_message)

        session_meta = dict(session.metadata_ or {})
        escalation_state = session_meta.get("_escalation_state")
        if escalation_state:
            return await self.playbook_handler.handle_escalation_info_collection(
                agent, session, user_message, start_time, escalation_state, session_meta
            )

        emergency_response = self.guardrail_service.check_emergency(user_message, agent)
        if emergency_response:
            session.status = "escalated"
            latency_ms = int((time.monotonic() - start_time) * 1000)
            return ChatResponse(session_id=session_id, message=emergency_response, tool_calls_made=[], suggested_actions=["Call 911"], escalate_to_human=True, latency_ms=latency_ms, tokens_used=0)

        jailbreak_response = self.guardrail_service.check_jailbreak(user_message, agent)
        if jailbreak_response:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            return ChatResponse(session_id=session_id, message=jailbreak_response, tool_calls_made=[], suggested_actions=[], escalate_to_human=False, latency_ms=latency_ms, tokens_used=0)

        intent = self.intent_detector.detect_intent(user_message)
        if self.intent_detector.should_escalate_immediately(user_message):
            return await self.playbook_handler.build_escalation_response(agent, session, user_message, start_time)

        playbook = await self.playbook_handler.route_active_playbook(str(agent.id), user_message)
        playbook_exec, local_vars = await self.playbook_handler.ensure_playbook_execution(str(agent.id), session_id, playbook)
        corrections = await self.context_builder.load_corrections(str(agent.id))
        await self.billing_service.maybe_send_greeting(agent, session, playbook)

        guardrails = await self.context_builder.load_guardrails(str(agent.id))
        variables = await self.context_builder.load_variables(str(agent.id), str(playbook.id) if playbook else None)

        block_reason = self.guardrail_service.check_input_guardrails(user_message, guardrails)
        if block_reason:
            block_msg = (guardrails.blocked_message if guardrails else "I'm sorry, I can't help with that.")
            self.db.add(Message(session_id=session_id, tenant_id=session.tenant_id, role="user", content=user_message, guardrail_triggered=block_reason, tokens_used=0, latency_ms=0))
            return ChatResponse(session_id=session_id, message=block_msg, tool_calls_made=[], suggested_actions=[], escalate_to_human=False, latency_ms=int((time.monotonic() - start_time) * 1000), tokens_used=0, guardrail_triggered=block_reason)

        history = await self.memory.get_short_term_memory(session_id)
        summary = await self.memory.get_session_summary(session_id)

        pii_ctx = await self.guardrail_service.get_pii_context(session_id)
        llm_user_message = self.guardrail_service.redact_user_message(user_message, pii_ctx, session_id)

        kb_ids = agent.knowledge_base_ids or []
        context_items = await self.mcp.retrieve_context(
            tenant_id=tenant_id, query=user_message, session_id=session_id, context_types=["knowledge", "history"],
            knowledge_base_ids=kb_ids if kb_ids else None,
        )

        source_citations = [
            SourceCitation(
                type=item.get("type", "knowledge"), title=item.get("metadata", {}).get("title"), source_url=item.get("metadata", {}).get("source_url"),
                excerpt=(item.get("content", "") or "")[:150], score=float(item.get("score", 1.0)),
                document_id=str(item.get("metadata", {}).get("document_id")) if item.get("metadata", {}).get("document_id") else None,
                chunk_id=str(item.get("metadata", {}).get("chunk_id")) if item.get("metadata", {}).get("chunk_id") else None,
            ) for item in context_items if isinstance(item, dict)
        ]

        customer_profile = {}
        if session.customer_identifier:
            customer_profile = await self.memory.get_long_term_customer_memory(tenant_id, session.customer_identifier)

        session_language = session_meta.get("language")

        system_prompt = self.context_builder.build_system_prompt(
            agent=agent, context_items=context_items, customer_profile=customer_profile, intent=intent,
            session_language=session_language, playbook=playbook, corrections=corrections, guardrails=guardrails,
            variables=variables, session_meta=session_meta, local_vars=local_vars
        )

        tool_schemas = await self.context_builder.get_agent_tools_schema(agent, playbook, tenant_id)

        messages = [{"role": "system", "content": system_prompt}]
        if summary:
            messages.append({"role": "system", "content": f"[Conversation summary so far]: {summary}"})
        messages.extend(history)
        messages.append({"role": "user", "content": llm_user_message})

        if not await self.billing_service.check_token_budget(tenant_id):
            return ChatResponse(session_id=session_id, message="I'm temporarily unavailable due to high usage. Please try again later.", tool_calls_made=[], suggested_actions=[], escalate_to_human=False, latency_ms=int((time.monotonic() - start_time) * 1000), tokens_used=0)

        llm_config = agent.llm_config or {}
        temperature = llm_config.get("temperature", 0.7)
        max_tokens = llm_config.get("max_tokens", settings.MAX_RESPONSE_TOKENS)
        system_tools = agent.tools or []
        playbook_tools = playbook.tools or [] if playbook else []
        enabled_tools = list(dict.fromkeys(system_tools + playbook_tools))

        full_response_text = ""
        iterations = 0

        while iterations < MAX_TOOL_ITERATIONS:
            llm_response = await self._llm_complete_with_timeout(
                messages=messages, tools=tool_schemas if tool_schemas else None, temperature=temperature, max_tokens=max_tokens, stream=False, session_id=session_id
            )
            total_tokens += llm_response.usage.total_tokens

            if llm_response.finish_reason == "timeout":
                full_response_text = llm_response.content or "I'm sorry, I'm taking longer than expected."
                break

            if not llm_response.tool_calls:
                full_response_text = llm_response.content or ""
                break

            iterations += 1
            allowed_calls = self.tool_executor.filter_unauthorized_tool_calls(llm_response.tool_calls, enabled_tools)
            if not allowed_calls:
                full_response_text = llm_response.content or "I wasn't able to complete that action."
                break

            confirmation_prompt = self.tool_executor.requires_confirmation(allowed_calls, user_message, history)
            if confirmation_prompt:
                full_response_text = confirmation_prompt
                break

            if pii_ctx is not None and pii_ctx.has_mappings():
                for tc in allowed_calls:
                    if isinstance(tc.arguments, dict):
                        tc.arguments = pii_service.restore_dict(tc.arguments, pii_ctx, session_id)

            tool_results = await self.tool_executor.execute_tool_calls(tool_calls=allowed_calls, tenant_id=tenant_id, session_id=session_id)
            tool_results = [{k: self.guardrail_service.scrub_credentials(str(v)) if isinstance(v, str) else v for k, v in r.items()} if isinstance(r, dict) else r for r in tool_results]

            if pii_ctx is not None:
                _re_anon = []
                for _r in tool_results:
                    if isinstance(_r, dict):
                        _re_anon.append(pii_service.redact_dict(_r, pii_ctx, session_id))
                    else:
                        _re_anon.append(_r)
                tool_results = _re_anon

            for tc, result in zip(allowed_calls, tool_results):
                safe_args = tc.arguments if not pii_ctx else pii_service.redact_dict(tc.arguments, pii_ctx, session_id) if isinstance(tc.arguments, dict) else tc.arguments
                tool_calls_made.append({"tool": tc.name, "arguments": safe_args, "result": result})

            messages.append({"role": "assistant", "content": llm_response.content or "", "tool_calls": [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in allowed_calls]})
            for tc, result in zip(allowed_calls, tool_results):
                sanitized_result = self.guardrail_service.sanitize_tool_output(str(result))
                messages.append({"role": "tool", "name": tc.name, "tool_call_id": tc.id, "content": sanitized_result})
            continue

        if not full_response_text and llm_response:
            full_response_text = llm_response.content or "I wasn't able to fully complete your request."

        latency_ms = int((time.monotonic() - start_time) * 1000)
        receipt = self.tool_executor.build_receipt_summary(tool_calls_made)
        if receipt:
            full_response_text = full_response_text.rstrip() + " " + receipt

        pseudo_full_response = full_response_text

        full_response_text, guardrail_actions = self.guardrail_service.apply_output_guardrails(full_response_text, guardrails, pii_ctx, session_id)
        if pii_ctx is not None:
            await self.guardrail_service.save_pii_context(session_id, pii_ctx)

        full_response_text = self.guardrail_service.check_professional_claims(full_response_text)
        is_fallback = self.playbook_handler.is_fallback_response(full_response_text, playbook)

        if is_fallback:
            fallback_count = await self.playbook_handler.increment_fallback_counter(session_id)
            if fallback_count >= _FALLBACK_ESCALATION_THRESHOLD:
                session.status = "escalated"
                full_response_text = "I've been unable to help with your last few requests. Let me connect you with a human agent."
                pseudo_full_response = full_response_text
                await self.playbook_handler.reset_fallback_counter(session_id)
        else:
            await self.playbook_handler.reset_fallback_counter(session_id)

        await self.memory.add_to_short_term_memory(session_id, {"role": "user", "content": llm_user_message})
        await self.memory.add_to_short_term_memory(session_id, {"role": "assistant", "content": pseudo_full_response})

        try:
            await self.memory.maybe_summarize(session_id, self.llm)
            if session.customer_identifier:
                await self.memory.extract_and_store_long_term_memory(
                    tenant_id=tenant_id, customer_identifier=session.customer_identifier,
                    conversation_text=f"User: {user_message}\nAssistant: {full_response_text}",
                    llm_client=self.llm,
                )
        except Exception as _mem_exc:
            logger.warning("stream_memory_post_turn_error", error=str(_mem_exc))

        user_msg = Message(session_id=session_id, tenant_id=session.tenant_id, role="user", content=pii_service.redact_for_display(user_message, pii_ctx) if pii_ctx else user_message, tokens_used=0, latency_ms=0)
        assistant_msg = Message(
            session_id=session_id, tenant_id=session.tenant_id, role="assistant",
            content=pii_service.redact_for_display(full_response_text, pii_ctx) if pii_ctx else full_response_text,
            tool_calls=tool_calls_made if tool_calls_made else None, tokens_used=total_tokens, latency_ms=latency_ms,
            is_fallback=is_fallback, playbook_name=playbook.name if playbook else None,
            sources=json.loads(json.dumps([c.model_dump() for c in source_citations])) if source_citations else [],
        )
        self.db.add(user_msg)
        self.db.add(assistant_msg)

        session.turn_count += 1
        await self.billing_service.update_analytics(tenant_id=session.tenant_id, agent_id=session.agent_id, tokens=total_tokens, latency_ms=latency_ms, tool_count=len(tool_calls_made))
        await self.billing_service.record_token_usage(tenant_id, total_tokens)

        should_escalate = await self.playbook_handler.should_escalate(agent, full_response_text, messages)
        if should_escalate:
            session.status = "escalated"

        return ChatResponse(
            session_id=session_id, message=full_response_text, tool_calls_made=tool_calls_made,
            source_citations=source_citations if source_citations else None,
            suggested_actions=self.billing_service.extract_suggested_actions(full_response_text, intent),
            escalate_to_human=should_escalate, latency_ms=latency_ms, tokens_used=total_tokens,
            playbook_executed=playbook.name if playbook else None,
            playbook_variables=local_vars if local_vars else None,
            turn_count=session.turn_count, session_status=session.status,
            guardrail_actions=guardrail_actions,
        )
