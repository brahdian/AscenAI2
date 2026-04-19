import asyncio
import time
import json
import uuid
from typing import AsyncGenerator, Optional
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.config import settings
from app.models.agent import Agent, Session, Message, GuardrailEvent
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
from app.services.grounding_service import GroundingService
from app.services.settings_service import SettingsService
from app.core.metrics import CONTEXT_RETRIEVALS
from app.services.session_state_machine import SessionStateMachine
from app.services.trace_logger import TraceLogger

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
        self.guardrail_service = GuardrailService(redis_client=self.redis, db=self.db)
        self.tool_executor = ToolExecutionService(db=self.db, mcp=self.mcp, redis_client=self.redis)
        self.context_builder = ContextBuilderService(db=self.db, mcp=self.mcp, redis_client=self.redis)
        self.playbook_handler = PlaybookHandler(db=self.db, llm_client=self.llm, redis_client=self.redis)
        self.billing_service = SessionBillingService(db=self.db, memory_manager=self.memory, redis_client=self.redis)
        self.grounding_service = GroundingService(llm_client=self.llm)

    async def _get_hipaa_mode(self, tenant_id: str) -> bool:
        """Fetch hipaa_mode flag from tenant metadata."""
        try:
            if self.redis:
                cached = await self.redis.get(f"tenant_compliance:{tenant_id}")
                if cached:
                    return json.loads(cached).get("hipaa_mode", False)
            
            from sqlalchemy import text
            res = await self.db.execute(text("SELECT metadata FROM tenants WHERE id = cast(:tid as uuid)"), {"tid": tenant_id})
            row = res.fetchone()
            if row and row[0]:
                compliance = row[0].get("compliance", {})
                if self.redis:
                    await self.redis.setex(f"tenant_compliance:{tenant_id}", 300, json.dumps(compliance))
                return compliance.get("hipaa_mode", False)
        except Exception as e:
            logger.warning("failed_to_fetch_hipaa_mode", error=str(e), tenant_id=tenant_id)
        return False

    async def _get_tenant_region(self, tenant_id: str) -> Optional[str]:
        """Fetch the tenant's data residency region for sovereign RAG routing."""
        try:
            if self.redis:
                cached = await self.redis.get(f"tenant_compliance:{tenant_id}")
                if cached:
                    return json.loads(cached).get("residency_region")
            from sqlalchemy import text
            res = await self.db.execute(text("SELECT metadata FROM tenants WHERE id = cast(:tid as uuid)"), {"tid": tenant_id})
            row = res.fetchone()
            if row and row[0]:
                return row[0].get("compliance", {}).get("residency_region")
        except Exception as e:
            logger.warning("failed_to_fetch_tenant_region", error=str(e), tenant_id=tenant_id)
        return None

    async def _maybe_send_payment_link_sms(self, agent: Agent, session: Session, tool_results: list[dict]):
        """Detect payment links in tool results and send them via SMS for voice interactions."""
        if session.channel != "voice":
            return

        for result in tool_results:
            if not isinstance(result, dict):
                continue
            
            # Detect payment link in result (handles various tool return schemas)
            payment_url = (
                result.get("payment_url") or 
                result.get("url") or 
                result.get("payment_link")
            )
            if not payment_url and isinstance(result.get("data"), dict):
                 payment_url = result["data"].get("payment_url") or result["data"].get("url")
            
            if payment_url and ("stripe.com" in str(payment_url) or "checkout.session" in str(payment_url)):
                phone = session.customer_identifier
                # Simple phone validation: starts with + or is largely numeric
                if phone and (str(phone).startswith("+") or (str(phone).replace("-", "").replace(" ", "").isdigit() and len(str(phone)) > 7)):
                    logger.info("triggering_payment_link_sms", session_id=session.id, phone=phone, url=payment_url)
                    sms_body = f"Here is the secure payment link for your {agent.name} request: {payment_url}"
                    try:
                        await self.mcp.execute_tool(
                            tenant_id=str(session.tenant_id),
                            tool_name="twilio_send_sms",
                            parameters={"to": phone, "body": sms_body},
                            session_id=session.id,
                            trace_id=f"payment_sms_{session.id}"
                        )
                    except Exception as e:
                        logger.error("failed_to_send_payment_sms", error=str(e), session_id=session.id)

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

    async def process_message(self, agent: Agent, session: Session, user_message: str, stream: bool = False, request_id: Optional[str] = None) -> ChatResponse | AsyncGenerator:
        if stream:
            return self.stream_response(agent, session, user_message, request_id=request_id)

        start_time = time.monotonic()
        tenant_id = str(session.tenant_id)
        session_id = session.id
        
        tracer = TraceLogger(session_id, session.tenant_id, agent.id, session.turn_count)

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

        emergency_response = await self.guardrail_service.check_emergency(user_message, agent, session_id, request_id=request_id)
        if emergency_response:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            # Service now records event to DB; orchestrator just adds messages
            self.db.add(Message(session_id=session_id, tenant_id=session.tenant_id, role="user", content=user_message, tokens_used=0, latency_ms=0))
            self.db.add(Message(session_id=session_id, tenant_id=session.tenant_id, role="assistant", content=emergency_response, tokens_used=0, latency_ms=latency_ms))
            SessionStateMachine.escalate(session, reason="emergency_detected")
            return ChatResponse(session_id=session_id, message=emergency_response, tool_calls_made=[], suggested_actions=["Call 911"], escalate_to_human=True, latency_ms=latency_ms, tokens_used=0)

        jailbreak_response = await self.guardrail_service.check_jailbreak(user_message, agent, session_id, request_id=request_id)
        if jailbreak_response:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            return ChatResponse(session_id=session_id, message=jailbreak_response, tool_calls_made=[], suggested_actions=[], escalate_to_human=False, latency_ms=latency_ms, tokens_used=0)

        if self.intent_detector.should_escalate_immediately(user_message):
            return await self.playbook_handler.build_escalation_response(agent, session, user_message, start_time)

        playbook = await self.playbook_handler.route_active_playbook(str(agent.id), user_message)

        # Derive intent from the routed playbook name (free — no extra I/O).
        # Fall back to keyword scoring across all active playbooks only when
        # routing returns None (agent has no active playbooks).
        if playbook:
            intent = playbook.name
        else:
            _fallback_playbooks = await self.playbook_handler.get_active_playbooks(str(agent.id))
            intent = self.intent_detector.classify_from_playbooks(user_message, _fallback_playbooks)

        playbook_exec, local_vars = await self.playbook_handler.ensure_playbook_execution(str(agent.id), str(session.id), playbook)
        corrections = await self.context_builder.load_corrections(str(agent.id))
        voice_opening = await self.billing_service.maybe_send_greeting(agent, session, playbook)
        if voice_opening and "_voice_opening" not in session_meta:
            new_meta = dict(session_meta)
            new_meta["_voice_opening"] = voice_opening
            session.metadata_ = new_meta
            session_meta = new_meta

        guardrails = await self.context_builder.load_guardrails(str(agent.id))
        custom_guardrails = await self.context_builder.load_custom_guardrails(str(agent.id))
        platform_guardrails = await self.context_builder.load_platform_guardrails()
        variables = await self.context_builder.load_variables(str(agent.id), str(playbook.id) if playbook else None)

        block_reason = await self.guardrail_service.check_input_guardrails(user_message, agent, session_id, guardrails, platform_guardrails, request_id=request_id)
        if block_reason:
            # Service now handles logging applied actions internally
            block_msg = (guardrails.get("blocked_message") if guardrails else "I'm sorry, I can't help with that.")
            self.db.add(Message(session_id=session_id, tenant_id=session.tenant_id, role="user", content=user_message, guardrail_triggered=block_reason, tokens_used=0, latency_ms=0))
            return ChatResponse(session_id=session_id, message=block_msg, tool_calls_made=[], suggested_actions=[], escalate_to_human=False, latency_ms=int((time.monotonic() - start_time) * 1000), tokens_used=0, guardrail_triggered=block_reason)

        history = await self.memory.get_short_term_memory(session_id)
        summary = await self.memory.get_session_summary(session_id)

        hipaa_mode = await self._get_hipaa_mode(tenant_id)
        pii_ctx = await self.guardrail_service.get_pii_context(session_id, tenant_id=tenant_id)
        llm_user_message = self.guardrail_service.redact_user_message(user_message, pii_ctx, session_id, hipaa_mode=hipaa_mode)

        agent_cfg = agent.agent_config or {}
        # GAP FIX: Orchestrator must auto-discover the agent's primary KB ID if not in config.
        # This ensures RAG works without manual config mapping.
        kb_ids = agent_cfg.get("knowledge_base_ids", []) or []
        primary_kb_id = str(agent.id) # By convention, the primary KB ID matches agent_id on MCP
        if primary_kb_id not in kb_ids:
            kb_ids.append(primary_kb_id)

        try:
            tenant_region = await self._get_tenant_region(tenant_id)
            tracer.start_timer("retrieval")
            context_items = await self.mcp.retrieve_context(
                tenant_id=tenant_id, query=user_message, session_id=session_id,
                context_types=["knowledge", "history"], knowledge_base_ids=kb_ids,
                region=tenant_region,
            )
            tracer.stop_timer("retrieval")
            tracer.set_retrieved_chunks([c for c in context_items if getattr(c, "type", c.get("type")) == "knowledge"])
            CONTEXT_RETRIEVALS.labels(status="success").inc()
            
            # G10: Sanitize knowledge chunks to prevent "Poisoned Knowledge" role-injection
            for item in context_items:
                if item.get("type") == "knowledge" and "content" in item:
                    item["content"] = await self.guardrail_service.sanitize_and_log_knowledge(
                        item["content"], agent, session_id, metadata=item.get("metadata"), request_id=request_id
                    )

            if "pii_ctx" in locals() and pii_ctx:
                context_items = pii_service.restore_context(context_items, pii_ctx, session_id)
            elif "stream_pii_ctx" in locals() and stream_pii_ctx:
                context_items = pii_service.restore_context(context_items, stream_pii_ctx, session_id)

        except Exception as _rag_exc:
            logger.error("rag_retrieval_failed_degraded_state", session_id=str(session_id), tenant_id=tenant_id, error=str(_rag_exc))
            CONTEXT_RETRIEVALS.labels(status="error").inc()
            # Phase 8: Propagate degraded state so LLM can inform user
            context_items = [{
                "type": "system_warning",
                "content": "The knowledge base is currently unreachable. You do not have access to internal documents for this turn.",
                "metadata": {"source": "system", "error": str(_rag_exc)}
            }]

        source_citations = [
            SourceCitation(
                type=item.get("type", "knowledge"), title=item.get("metadata", {}).get("title"), source_url=item.get("metadata", {}).get("source_url"),
                excerpt=(item.get("content", "") or "")[:150], score=float(item.get("score", 1.0)),
                document_id=str(item.get("metadata", {}).get("document_id")) if item.get("metadata", {}).get("document_id") else None,
                chunk_id=str(item.get("metadata", {}).get("chunk_id")) if item.get("metadata", {}).get("chunk_id") else None,
            ) for item in context_items if isinstance(item, dict) and item.get("type") != "system_warning"
        ]

        customer_profile = {}
        if session.customer_identifier:
            customer_profile = await self.memory.get_long_term_customer_memory(tenant_id, session.customer_identifier)

        session_language = session_meta.get("language")

        if agent_cfg.get("auto_detect_language", False):
            detected_lang = self.intent_detector.detect_language(
                user_message, agent_cfg.get("supported_languages", []) or []
            )
            if detected_lang and detected_lang != session_language:
                session_language = detected_lang
                # B5 FIX: fresh dict assignment so MutableDict tracks the change
                new_meta = dict(session_meta)
                new_meta["language"] = detected_lang
                session.metadata_ = new_meta
                session_meta = new_meta

        voice_sys_prompt_setting = await SettingsService.get_setting(self.db, "voice_agent_system_prompt", {})
        voice_system_prompt_template = voice_sys_prompt_setting.get("template", "")
        platform_limits = await self.context_builder.load_platform_limits()

        system_prompt = self.context_builder.build_system_prompt(
            agent=agent, context_items=context_items, customer_profile=customer_profile, intent=intent,
            session_language=session_language, playbook=playbook, corrections=corrections,
            guardrails=guardrails, custom_guardrails=custom_guardrails,
            platform_guardrails=platform_guardrails,
            variables=variables, session_meta=session_meta, local_vars=local_vars,
            voice_system_prompt_template=voice_system_prompt_template,
            platform_limits=platform_limits,
        )
        
        tracer.set_system_prompt(pii_service.redact(system_prompt))
        tracer.set_memory(
            short_term=pii_service.redact_deep(history or []),
            summary=pii_service.redact(summary or ""),
            long_term=pii_service.redact_deep(customer_profile or {})
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
        llm_config = agent_cfg.get("llm_config", {}) or {}
        temperature = llm_config.get("temperature", 0.7)
        max_tokens = llm_config.get("max_tokens", settings.MAX_RESPONSE_TOKENS)

        final_response = None
        iterations = 0
        system_tools = agent_cfg.get("tools", []) or []
        playbook_tools = (playbook.config or {}).get("tools", []) if playbook else []
        enabled_tools = list(dict.fromkeys(system_tools + playbook_tools))

        tracer.set_messages_sent(pii_service.redact_deep(messages))

        while iterations < MAX_TOOL_ITERATIONS:
            tracer.start_timer("llm")
            llm_response = await self._llm_complete_with_timeout(messages=messages, tools=tool_schemas if tool_schemas else None, temperature=temperature, max_tokens=max_tokens, stream=False, session_id=session_id)
            tracer.stop_timer("llm")
            tracer.set_llm_response(
                raw=llm_response.content or "", provider=agent_cfg.get("llm_provider", ""), model=agent_cfg.get("llm_model", "")
            )
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

                tracer.start_timer("tools")
                tool_results = await self.tool_executor.execute_tool_calls(tool_calls=allowed_calls, tenant_id=tenant_id, session_id=session_id)
                tracer.stop_timer("tools")
                
                tool_results = [{k: self.guardrail_service.scrub_credentials(str(v)) if isinstance(v, str) else v for k, v in r.items()} if isinstance(r, dict) else r for r in tool_results]

                if pii_ctx is not None:
                    _re_anon = []
                    for _r in tool_results:
                        if isinstance(_r, dict):
                            _re_anon.append(pii_service.redact_dict(_r, pii_ctx, session_id, hipaa_mode=hipaa_mode))
                        else:
                            _re_anon.append(_r)
                    tool_results = _re_anon
                
                # Payment Link Hardening: Send SMS for voice agents
                await self._maybe_send_payment_link_sms(agent, session, tool_results)

                for tc, result in zip(allowed_calls, tool_results):
                    safe_args = tc.arguments if not pii_ctx else pii_service.redact_dict(tc.arguments, pii_ctx, session_id, hipaa_mode=hipaa_mode) if isinstance(tc.arguments, dict) else tc.arguments
                    tool_calls_made.append({"tool": tc.name, "arguments": safe_args, "result": result})
                    tracer.add_tool_call(tc.name, safe_args, result, latency_ms=0)

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

        final_response, guardrail_actions = await self.guardrail_service.apply_output_guardrails(
            final_response, agent, guardrails, platform_guardrails, pii_ctx, session_id, hipaa_mode=hipaa_mode
        )
        # Service now handles logging applied actions internally
        if pii_ctx is not None:
            await self.guardrail_service.save_pii_context(session_id, pii_ctx)

        final_response = self.guardrail_service.check_professional_claims(final_response)
        is_fallback = self.playbook_handler.is_fallback_response(final_response, playbook)

        if is_fallback:
            fallback_count = await self.playbook_handler.increment_fallback_counter(session_id)
            if fallback_count >= _FALLBACK_ESCALATION_THRESHOLD:
                SessionStateMachine.escalate(session, reason="fallback_threshold_exceeded")
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

        tracer.set_guardrail_actions(guardrail_actions)
        if pii_ctx:
            tracer.set_pii_entity_types([type(e).__name__ for e in getattr(pii_ctx, "entities", [])] if hasattr(pii_ctx, "entities") else [])
        tracer.set_final_response(final_response)

        user_msg = Message(
            session_id=session_id,
            tenant_id=session.tenant_id,
            role="user",
            content=pii_service.redact_for_display(user_message, pii_ctx, hipaa_mode=hipaa_mode) if (pii_ctx and guardrails and guardrails.pii_redaction) else user_message,
            tokens_used=0,
            latency_ms=0
        )
        assistant_msg = Message(
            session_id=session_id,
            tenant_id=session.tenant_id,
            role="assistant",
            content=pii_service.redact_for_display(final_response, pii_ctx, hipaa_mode=hipaa_mode) if (pii_ctx and guardrails and guardrails.pii_redaction) else final_response,
            tool_calls=tool_calls_made if tool_calls_made else None, tokens_used=total_tokens, latency_ms=latency_ms,
            is_fallback=is_fallback, playbook_name=playbook.name if playbook else None,
            sources=json.loads(json.dumps([c.model_dump() for c in source_citations])) if source_citations else [],
        )
        self.db.add(user_msg)
        self.db.add(assistant_msg)
        await self.db.flush() # Populate assistant_msg.id for billing idempotency

        is_new = (session.turn_count == 0)

        # Clear the greeting-only flag now that a real user turn has completed.
        # Sessions that disconnect after only the greeting never reach this point,
        # so they remain turn_count==0 and update_analytics is never called for them.
        if session_meta.get("_greeting_only"):
            cleared_meta = dict(session_meta)
            cleared_meta.pop("_greeting_only", None)
            session.metadata_ = cleared_meta
            session_meta = cleared_meta

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
            chat_units=chat_unit_increment,
            turn_id=str(assistant_msg.id),
        )
        await self.billing_service.record_token_usage(tenant_id, total_tokens)

        # Phase 11: Finalize forensic trace
        tracer.set_message_id(assistant_msg.id)
        await tracer.persist(self.db, tokens_used=total_tokens)

        should_escalate = await self.playbook_handler.should_escalate(agent, final_response, messages)
        if should_escalate:
            SessionStateMachine.escalate(session, reason="should_escalate_check")

        # Phase 6: Non-blocking NLI Grounding Verification
        is_grounded: Optional[bool] = None
        grounding_explanation: Optional[str] = None
        if source_citations and final_response:
            try:
                is_grounded, grounding_explanation = await self.grounding_service.verify_grounding(
                    final_response, source_citations
                )
            except Exception as _grounding_exc:
                logger.warning("grounding_check_error", error=str(_grounding_exc))

        return ChatResponse(
            session_id=session_id, message=final_response, tool_calls_made=tool_calls_made,
            source_citations=source_citations if source_citations else None,
            suggested_actions=self.billing_service.extract_suggested_actions(final_response, intent),
            escalate_to_human=should_escalate, latency_ms=latency_ms, tokens_used=total_tokens,
            playbook_executed=playbook.name if playbook else None,
            playbook_variables=local_vars if local_vars else None,
            turn_count=session.turn_count, session_status=session.status,
            guardrail_actions=guardrail_actions,
            is_grounded=is_grounded,
            grounding_explanation=grounding_explanation,
        )

    # ------------------------------------------------------------------
    # Streaming path
    # ------------------------------------------------------------------

    async def stream_response(self, agent: Agent, session: Session, user_message: str, request_id: Optional[str] = None) -> AsyncGenerator:
        start_time = time.monotonic()
        tenant_id = str(session.tenant_id)
        session_id = session.id
        tool_calls_made: list = []
        total_tokens = 0
        
        tracer = TraceLogger(session_id, session.tenant_id, agent.id, session.turn_count)

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

        emergency_response = await self.guardrail_service.check_emergency(user_message, agent, session_id)
        if emergency_response:
            # Service now records event to DB; orchestrator session logic remains
            SessionStateMachine.escalate(session, reason="stream_emergency_detected")
            yield StreamChatEvent(type="text_delta", data=emergency_response, session_id=session_id)
            yield StreamChatEvent(type="done", data={"session_id": session_id, "latency_ms": int((time.monotonic() - start_time) * 1000), "tokens_used": 0, "escalate_to_human": True}, session_id=session_id)
            return

        jailbreak_response = await self.guardrail_service.check_jailbreak(user_message, agent, session_id)
        if jailbreak_response:
            yield StreamChatEvent(type="text_delta", data=jailbreak_response, session_id=session_id)
            yield StreamChatEvent(type="done", data={"session_id": session_id, "latency_ms": int((time.monotonic() - start_time) * 1000), "tokens_used": 0, "escalate_to_human": False}, session_id=session_id)
            return

        if self.intent_detector.should_escalate_immediately(user_message):
            escalation_response = await self.playbook_handler.build_escalation_response(agent, session, user_message, start_time)
            yield StreamChatEvent(type="text_delta", data=escalation_response.message, session_id=session_id)
            yield StreamChatEvent(type="done", data={"session_id": session_id, "latency_ms": escalation_response.latency_ms, "tokens_used": 0, "escalate_to_human": True, "escalation_action": escalation_response.escalation_action}, session_id=session_id)
            return

        playbook = await self.playbook_handler.route_active_playbook(str(agent.id), user_message)

        # Derive intent from the routed playbook name (free — no extra I/O).
        if playbook:
            intent = playbook.name
        else:
            _fallback_playbooks = await self.playbook_handler.get_active_playbooks(str(agent.id))
            intent = self.intent_detector.classify_from_playbooks(user_message, _fallback_playbooks)

        playbook_exec, local_vars = await self.playbook_handler.ensure_playbook_execution(str(agent.id), session_id, playbook)
        corrections = await self.context_builder.load_corrections(str(agent.id))
        voice_opening = await self.billing_service.maybe_send_greeting(agent, session, playbook)
        if voice_opening and "_voice_opening" not in session_meta:
            new_meta = dict(session_meta)
            new_meta["_voice_opening"] = voice_opening
            session.metadata_ = new_meta
            session_meta = new_meta

        guardrails = await self.context_builder.load_guardrails(str(agent.id))
        custom_guardrails = await self.context_builder.load_custom_guardrails(str(agent.id))
        platform_guardrails = await self.context_builder.load_platform_guardrails()
        variables = await self.context_builder.load_variables(str(agent.id), str(playbook.id) if playbook else None)
 
        stream_agent_cfg = agent.agent_config or {}
        llm_config = stream_agent_cfg.get("llm_config", {}) or {}
 
        block_reason = await self.guardrail_service.check_input_guardrails(user_message, agent, session_id, guardrails, platform_guardrails, request_id=request_id)
        if block_reason:
            block_msg = (guardrails.get("blocked_message") if guardrails else "I'm sorry, I can't help with that.")
            yield StreamChatEvent(type="text_delta", data=block_msg, session_id=session_id)
            yield StreamChatEvent(type="done", data={"session_id": session_id, "latency_ms": int((time.monotonic() - start_time) * 1000), "tokens_used": 0, "escalate_to_human": False, "guardrail_triggered": block_reason}, session_id=session_id)
            return

        history = await self.memory.get_short_term_memory(session_id)
        summary = await self.memory.get_session_summary(session_id)

        hipaa_mode = await self._get_hipaa_mode(tenant_id)
        stream_pii_ctx = await self.guardrail_service.get_pii_context(session_id, tenant_id=tenant_id)
        llm_user_message = self.guardrail_service.redact_user_message(user_message, stream_pii_ctx, session_id, hipaa_mode=hipaa_mode)
        _pii_active = stream_pii_ctx is not None and stream_pii_ctx.has_mappings()

        # GAP FIX: Orchestrator must auto-discover the agent's primary KB ID if not in config.
        kb_ids = stream_agent_cfg.get("knowledge_base_ids", []) or []
        primary_kb_id = str(agent.id)
        if primary_kb_id not in kb_ids:
            kb_ids.append(primary_kb_id)

        try:
            stream_tenant_region = await self._get_tenant_region(tenant_id)
            context_items = await self.mcp.retrieve_context(
                tenant_id=tenant_id, query=user_message, session_id=session_id,
                context_types=["knowledge", "history"],
                knowledge_base_ids=kb_ids,
                region=stream_tenant_region,
            )
            CONTEXT_RETRIEVALS.labels(status="success").inc()

            # G10: Sanitize knowledge chunks in streaming path
            for item in context_items:
                if item.get("type") == "knowledge" and "content" in item:
                    item["content"] = await self.guardrail_service.sanitize_and_log_knowledge(
                        item["content"], agent, session_id, metadata=item.get("metadata")
                    )

            if "pii_ctx" in locals() and pii_ctx:
                context_items = pii_service.restore_context(context_items, pii_ctx, session_id)
            elif "stream_pii_ctx" in locals() and stream_pii_ctx:
                context_items = pii_service.restore_context(context_items, stream_pii_ctx, session_id)

        except Exception as _stream_rag_exc:
            logger.error("rag_retrieval_failed_degraded_stream", session_id=str(session_id), tenant_id=tenant_id, error=str(_stream_rag_exc))
            CONTEXT_RETRIEVALS.labels(status="error").inc()
            # Phase 8: Propagate degraded state in stream
            context_items = [{
                "type": "system_warning",
                "content": "The knowledge base is currently unreachable. You do not have access to internal documents for this turn.",
                "metadata": {"source": "system", "error": str(_stream_rag_exc)}
            }]

        stream_source_citations = [
            SourceCitation(
                type=item.get("type", "knowledge"), title=item.get("metadata", {}).get("title"), source_url=item.get("metadata", {}).get("source_url"),
                excerpt=(item.get("content", "") or "")[:150], score=float(item.get("score", 1.0)),
                document_id=str(item.get("metadata", {}).get("document_id")) if item.get("metadata", {}).get("document_id") else None,
                chunk_id=str(item.get("metadata", {}).get("chunk_id")) if item.get("metadata", {}).get("chunk_id") else None,
            ) for item in context_items
            if isinstance(item, dict) and item.get("type") != "system_warning"
        ]
        stream_llm_config = stream_agent_cfg.get("llm_config", {}) or {}

        customer_profile = {}
        if session.customer_identifier:
            customer_profile = await self.memory.get_long_term_customer_memory(tenant_id, session.customer_identifier)

        session_meta = dict(session.metadata_ or {}) if hasattr(session, "metadata_") else {}
        session_language = session_meta.get("language")

        voice_sys_prompt_setting = await SettingsService.get_setting(self.db, "voice_agent_system_prompt", {})
        voice_system_prompt_template = voice_sys_prompt_setting.get("template", "")
        platform_limits = await self.context_builder.load_platform_limits()

        system_prompt = self.context_builder.build_system_prompt(
            agent=agent, context_items=context_items, customer_profile=customer_profile, intent=intent,
            session_language=session_language, playbook=playbook, corrections=corrections,
            guardrails=guardrails, custom_guardrails=custom_guardrails,
            platform_guardrails=platform_guardrails,
            variables=variables, session_meta=session_meta, local_vars=local_vars,
            voice_system_prompt_template=voice_system_prompt_template,
            platform_limits=platform_limits,
        )
        
        tracer.set_system_prompt(pii_service.redact(system_prompt))
        tracer.set_memory(short_term=pii_service.redact_deep(history or []), summary=pii_service.redact(summary or ""), long_term=pii_service.redact_deep(customer_profile or {}))

        tool_schemas = await self.context_builder.get_agent_tools_schema(agent, playbook, tenant_id)

        messages = [{"role": "system", "content": system_prompt}]
        if summary:
            messages.append({"role": "system", "content": f"[Conversation summary so far]: {summary}"})
        messages.extend(history)
        messages.append({"role": "user", "content": llm_user_message})

        latency_ms = int((time.monotonic() - start_time) * 1000)
        
        # Calculate Chat Units and New Session flags (TC-B01)
        is_new = (session.turn_count == 0)
        chat_unit_increment = 0
        if is_new:
            chat_unit_increment = 1
        elif session.turn_count > 0 and (session.turn_count + 1) % 10 == 0:
            chat_unit_increment = 1

        latency_ms = int((time.monotonic() - start_time) * 1000)
        temperature = stream_llm_config.get("temperature", 0.7)
        max_tokens = stream_llm_config.get("max_tokens", settings.MAX_RESPONSE_TOKENS)
        system_tools = stream_agent_cfg.get("tools", []) or []
        playbook_tools = (playbook.config or {}).get("tools", []) if playbook else []
        enabled_tools = list(dict.fromkeys(system_tools + playbook_tools))

        full_response_text = ""
        iterations = 0
        llm_response = None
        
        tracer.set_messages_sent(pii_service.redact_deep(messages))

        while iterations < MAX_TOOL_ITERATIONS:
            tracer.start_timer("llm")
            llm_response = await self._llm_complete_with_timeout(
                messages=messages, tools=tool_schemas if tool_schemas else None, temperature=temperature, max_tokens=max_tokens, stream=False, session_id=session_id
            )
            tracer.stop_timer("llm")
            tracer.set_llm_response(raw=llm_response.content or "", provider=stream_agent_cfg.get("llm_provider", ""), model=stream_agent_cfg.get("llm_model", ""))
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

            tracer.start_timer("tools")
            tool_results = await self.tool_executor.execute_tool_calls(tool_calls=allowed_calls, tenant_id=tenant_id, session_id=session_id)
            tracer.stop_timer("tools")
            tool_results = [{k: self.guardrail_service.scrub_credentials(str(v)) if isinstance(v, str) else v for k, v in r.items()} if isinstance(r, dict) else r for r in tool_results]

            if stream_pii_ctx is not None:
                _re_anon_s = []
                for _r in tool_results:
                    if isinstance(_r, dict):
                        _re_anon_s.append(pii_service.redact_dict(_r, stream_pii_ctx, session_id, hipaa_mode=hipaa_mode))
                    else:
                        _re_anon_s.append(_r)
                tool_results = _re_anon_s
            
            # Payment Link Hardening: Send SMS for voice agents
            await self._maybe_send_payment_link_sms(agent, session, tool_results)

            for tc, result in zip(allowed_calls, tool_results):
                safe_args = tc.arguments if not stream_pii_ctx else pii_service.redact_dict(tc.arguments, stream_pii_ctx, session_id, hipaa_mode=hipaa_mode) if isinstance(tc.arguments, dict) else tc.arguments
                tool_calls_made.append({"tool": tc.name, "arguments": safe_args, "result": result})
                tracer.add_tool_call(tc.name, safe_args, result, latency_ms=0)
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

        # Apply output guardrails (including PII restoration and output scanning) BEFORE streaming to client
        full_response_text, stream_guardrail_actions = await self.guardrail_service.apply_output_guardrails(
            full_response_text, agent, guardrails, platform_guardrails, stream_pii_ctx, session_id, hipaa_mode=hipaa_mode, request_id=request_id
        )

        # G11: Moderation parity for streaming completions
        if self.moderation_service:
            try:
                await self.moderation_service.check_output(full_response_text)
            except OutputBlockedError as _mod_exc:
                logger.warning("streaming_output_moderation_blocked", session_id=session_id)
                full_response_text = "I'm sorry, I cannot fulfill this request as it violates safety policies."
                pseudo_full_response = full_response_text

        # Service now handles logging applied actions internally

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
                SessionStateMachine.escalate(session, reason="stream_fallback_threshold_exceeded")
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

        user_msg_content = pii_service.redact_for_display(user_message, stream_pii_ctx, hipaa_mode=hipaa_mode) if stream_pii_ctx else user_message
        assistant_msg_content = pii_service.redact_for_display(full_response_text, stream_pii_ctx, hipaa_mode=hipaa_mode) if stream_pii_ctx else full_response_text

        user_msg = Message(session_id=session_id, tenant_id=session.tenant_id, role="user", content=user_msg_content, tokens_used=0, latency_ms=0)
        assistant_msg = Message(
            session_id=session_id, tenant_id=session.tenant_id, role="assistant", content=assistant_msg_content,
            tool_calls=tool_calls_made if tool_calls_made else None, tokens_used=total_tokens, latency_ms=latency_ms,
            is_fallback=is_fallback, playbook_name=playbook.name if playbook else None,
            sources=json.loads(json.dumps([c.model_dump() for c in stream_source_citations])) if stream_source_citations else [],
        )
        self.db.add(user_msg)
        self.db.add(assistant_msg)
        await self.db.flush() # Populate assistant_msg.id for billing idempotency

        # Clear greeting-only flag on first real user turn.
        if session_meta.get("_greeting_only"):
            cleared_meta = dict(session_meta)
            cleared_meta.pop("_greeting_only", None)
            session.metadata_ = cleared_meta
            session_meta = cleared_meta

        session.turn_count += 1
        await self.billing_service.update_analytics(
            tenant_id=session.tenant_id,
            agent_id=session.agent_id,
            tokens=total_tokens,
            latency_ms=latency_ms,
            tool_count=len(tool_calls_made),
            is_new_session=is_new,
            chat_units=chat_unit_increment,
            turn_id=str(assistant_msg.id),
        )
        await self.billing_service.record_token_usage(tenant_id, total_tokens)

        # Phase 11: Finalize forensic trace (Streaming Path)
        tracer.set_guardrail_actions(stream_guardrail_actions)
        tracer.set_final_response(full_response_text)
        tracer.set_message_id(assistant_msg.id)
        if stream_pii_ctx:
            tracer.set_pii_entity_types([type(e).__name__ for e in getattr(stream_pii_ctx, "entities", [])] if hasattr(stream_pii_ctx, "entities") else [])
        await tracer.persist(self.db, tokens_used=total_tokens)

        should_escalate = await self.playbook_handler.should_escalate(agent, full_response_text, messages)
        if should_escalate:
            SessionStateMachine.escalate(session, reason="stream_should_escalate_check")

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

    async def stream_response_async(self, agent_id: str, session_id: str, user_message: str, request_id: Optional[str] = None) -> ChatResponse:
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
            )

        emergency_response = await self.guardrail_service.check_emergency(user_message, agent, session_id)
        if emergency_response:
            # Service records event internally
            SessionStateMachine.escalate(session, reason="async_stream_emergency_detected")
            latency_ms = int((time.monotonic() - start_time) * 1000)
            return ChatResponse(session_id=session_id, message=emergency_response, tool_calls_made=[], suggested_actions=["Call 911"], escalate_to_human=True, latency_ms=latency_ms, tokens_used=0)

        jailbreak_response = await self.guardrail_service.check_jailbreak(user_message, agent, session_id)
        if jailbreak_response:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            return ChatResponse(session_id=session_id, message=jailbreak_response, tool_calls_made=[], suggested_actions=[], escalate_to_human=False, latency_ms=latency_ms, tokens_used=0)

        if self.intent_detector.should_escalate_immediately(user_message):
            return await self.playbook_handler.build_escalation_response(agent, session, user_message, start_time)

        playbook = await self.playbook_handler.route_active_playbook(str(agent.id), user_message)

        # Derive intent from the routed playbook name (free — no extra I/O).
        if playbook:
            intent = playbook.name
        else:
            _fallback_playbooks = await self.playbook_handler.get_active_playbooks(str(agent.id))
            intent = self.intent_detector.classify_from_playbooks(user_message, _fallback_playbooks)

        playbook_exec, local_vars = await self.playbook_handler.ensure_playbook_execution(str(agent.id), session_id, playbook)
        corrections = await self.context_builder.load_corrections(str(agent.id))
        voice_opening = await self.billing_service.maybe_send_greeting(agent, session, playbook)
        if voice_opening and "_voice_opening" not in session_meta:
            new_meta = dict(session_meta)
            new_meta["_voice_opening"] = voice_opening
            session.metadata_ = new_meta
            session_meta = new_meta

        guardrails = await self.context_builder.load_guardrails(str(agent.id))
        custom_guardrails = await self.context_builder.load_custom_guardrails(str(agent.id))
        platform_guardrails = await self.context_builder.load_platform_guardrails()
        variables = await self.context_builder.load_variables(str(agent.id), str(playbook.id) if playbook else None)

        block_reason = await self.guardrail_service.check_input_guardrails(user_message, agent, session_id, guardrails, platform_guardrails, request_id=request_id)
        if block_reason:
            block_msg = (guardrails.get("blocked_message") if guardrails else "I'm sorry, I can't help with that.")
            self.db.add(Message(session_id=session_id, tenant_id=session.tenant_id, role="user", content=user_message, guardrail_triggered=block_reason, tokens_used=0, latency_ms=0))
            return ChatResponse(session_id=session_id, message=block_msg, tool_calls_made=[], suggested_actions=[], escalate_to_human=False, latency_ms=int((time.monotonic() - start_time) * 1000), tokens_used=0, guardrail_triggered=block_reason)

        history = await self.memory.get_short_term_memory(session_id)
        summary = await self.memory.get_session_summary(session_id)

        pii_ctx = await self.guardrail_service.get_pii_context(session_id, tenant_id=tenant_id)
        llm_user_message = self.guardrail_service.redact_user_message(user_message, pii_ctx, session_id)

        agent_cfg = agent.agent_config or {}
        kb_ids = agent_cfg.get("knowledge_base_ids", []) or []
        try:
            voice_tenant_region = await self._get_tenant_region(tenant_id)
            context_items = await self.mcp.retrieve_context(
                tenant_id=tenant_id, query=user_message, session_id=session_id,
                context_types=["knowledge", "history"],
                knowledge_base_ids=kb_ids if kb_ids else None,
                region=voice_tenant_region,
            )
            CONTEXT_RETRIEVALS.labels(status="success").inc()

            # G10: Sanitize knowledge chunks for Zero Trust RAG safety
            for item in context_items:
                if item.get("type") == "knowledge" and "content" in item:
                    item["content"] = await self.guardrail_service.sanitize_and_log_knowledge(
                        item["content"], agent, session_id, metadata=item.get("metadata")
                    )

            if "pii_ctx" in locals() and pii_ctx:
                context_items = pii_service.restore_context(context_items, pii_ctx, session_id)
            elif "stream_pii_ctx" in locals() and stream_pii_ctx:
                context_items = pii_service.restore_context(context_items, stream_pii_ctx, session_id)

        except Exception as _rag_exc:
            logger.warning("rag_retrieval_failed_async_stream", session_id=str(session_id), tenant_id=tenant_id, error=str(_rag_exc))
            CONTEXT_RETRIEVALS.labels(status="error").inc()
            # Phase 8: Propagate degraded state in async stream
            context_items = [{
                "type": "system_warning",
                "content": "The knowledge base is currently unreachable. You do not have access to internal documents for this turn.",
                "metadata": {"source": "system", "error": str(_rag_exc)}
            }]

        source_citations = [
            SourceCitation(
                type=item.get("type", "knowledge"), title=item.get("metadata", {}).get("title"), source_url=item.get("metadata", {}).get("source_url"),
                excerpt=(item.get("content", "") or "")[:150], score=float(item.get("score", 1.0)),
                document_id=str(item.get("metadata", {}).get("document_id")) if item.get("metadata", {}).get("document_id") else None,
                chunk_id=str(item.get("metadata", {}).get("chunk_id")) if item.get("metadata", {}).get("chunk_id") else None,
            ) for item in context_items if isinstance(item, dict) and item.get("type") != "system_warning"
        ]

        customer_profile = {}
        if session.customer_identifier:
            customer_profile = await self.memory.get_long_term_customer_memory(tenant_id, session.customer_identifier)

        session_language = session_meta.get("language")

        voice_sys_prompt_setting = await SettingsService.get_setting(self.db, "voice_agent_system_prompt", {})
        voice_system_prompt_template = voice_sys_prompt_setting.get("template", "")
        platform_limits = await self.context_builder.load_platform_limits()

        system_prompt = self.context_builder.build_system_prompt(
            agent=agent, context_items=context_items, customer_profile=customer_profile, intent=intent,
            session_language=session_language, playbook=playbook, corrections=corrections,
            guardrails=guardrails, custom_guardrails=custom_guardrails,
            platform_guardrails=platform_guardrails,
            variables=variables, session_meta=session_meta, local_vars=local_vars,
            voice_system_prompt_template=voice_system_prompt_template,
            platform_limits=platform_limits,
        )

        tool_schemas = await self.context_builder.get_agent_tools_schema(agent, playbook, tenant_id)

        messages = [{"role": "system", "content": system_prompt}]
        if summary:
            messages.append({"role": "system", "content": f"[Conversation summary so far]: {summary}"})
        messages.extend(history)
        messages.append({"role": "user", "content": llm_user_message})

        if not await self.billing_service.check_token_budget(tenant_id):
            return ChatResponse(session_id=session_id, message="I'm temporarily unavailable due to high usage. Please try again later.", tool_calls_made=[], suggested_actions=[], escalate_to_human=False, latency_ms=int((time.monotonic() - start_time) * 1000), tokens_used=0)

        llm_config = agent_cfg.get("llm_config", {}) or {}
        temperature = llm_config.get("temperature", 0.7)
        max_tokens = llm_config.get("max_tokens", settings.MAX_RESPONSE_TOKENS)
        system_tools = agent_cfg.get("tools", []) or []
        playbook_tools = (playbook.config or {}).get("tools", []) if playbook else []
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
            
            # Payment Link Hardening: Send SMS for voice agents
            await self._maybe_send_payment_link_sms(agent, session, tool_results)

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

        final_response, guardrail_actions = await self.guardrail_service.apply_output_guardrails(
            full_response_text, agent, guardrails, platform_guardrails, pii_ctx, session_id, request_id=request_id
        )

        # G11: Moderation parity for async streaming path
        if self.moderation_service:
            try:
                await self.moderation_service.check_output(full_response_text)
            except OutputBlockedError as _mod_exc_async:
                logger.warning("async_output_moderation_blocked", session_id=session_id)
                full_response_text = "I'm sorry, I cannot fulfill this request as it violates safety policies."
                pseudo_full_response = full_response_text

        # Service now handles logging applied actions internally
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
        await self.db.flush()  # Populate assistant_msg.id for billing idempotency
        
        tracer.set_guardrail_actions(guardrail_actions)
        if pii_ctx:
            tracer.set_pii_entity_types([type(e).__name__ for e in getattr(pii_ctx, "entities", [])] if hasattr(pii_ctx, "entities") else [])
        tracer.set_final_response(full_response_text)
        tracer.set_message_id(assistant_msg.id)
        await tracer.persist(self.db, tokens_used=total_tokens)

        # Clear greeting-only flag on first real user turn.
        if session_meta.get("_greeting_only"):
            cleared_meta = dict(session_meta)
            cleared_meta.pop("_greeting_only", None)
            session.metadata_ = cleared_meta
            session_meta = cleared_meta

        is_new = (session.turn_count == 0)
        chat_unit_increment = 1 if is_new else (1 if session.turn_count > 0 and (session.turn_count + 1) % 10 == 0 else 0)
        session.turn_count += 1
        await self.billing_service.update_analytics(
            tenant_id=session.tenant_id, agent_id=session.agent_id,
            tokens=total_tokens, latency_ms=latency_ms, tool_count=len(tool_calls_made),
            is_new_session=is_new, chat_units=chat_unit_increment,
            turn_id=str(assistant_msg.id),
        )
        await self.billing_service.record_token_usage(tenant_id, total_tokens)

        should_escalate = await self.playbook_handler.should_escalate(agent, full_response_text, messages)
        if should_escalate:
            SessionStateMachine.escalate(session, reason="async_should_escalate_check")

        # Phase 6: Non-blocking NLI Grounding Verification
        is_grounded: Optional[bool] = None
        grounding_explanation: Optional[str] = None
        if stream_source_citations and full_response_text:
            try:
                is_grounded, grounding_explanation = await self.grounding_service.verify_grounding(
                    full_response_text, stream_source_citations
                )
            except Exception as _grounding_exc:
                logger.warning("stream_grounding_check_error", error=str(_grounding_exc))

        return ChatResponse(
            session_id=session_id, message=full_response_text, tool_calls_made=tool_calls_made,
            source_citations=stream_source_citations if stream_source_citations else None,
            suggested_actions=self.billing_service.extract_suggested_actions(full_response_text, intent),
            escalate_to_human=should_escalate, latency_ms=latency_ms, tokens_used=total_tokens,
            playbook_executed=playbook.name if playbook else None,
            playbook_variables=local_vars if local_vars else None,
            turn_count=session.turn_count, session_status=session.status,
            guardrail_actions=guardrail_actions,
            is_grounded=is_grounded,
            grounding_explanation=grounding_explanation,
        )
        

