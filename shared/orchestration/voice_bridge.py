"""
Voice Orchestrator Bridge — shared/orchestration/voice_bridge.py

Instantiates and holds a stateful, in-process `Orchestrator` for the
duration of a voice call. This eliminates the HTTP hop to the
`ai-orchestrator` service, cutting ~100-200ms per turn.

Used by: voice-pipeline
Not used by: ai-orchestrator (it instantiates Orchestrator directly in its API routes)

Design constraints:
  - Do NOT rename any Orchestrator/service methods (per user constraint).
  - All database and redis dependencies are injected at construction time.
  - The bridge is created once per WebSocket session and discarded on hangup.
"""
from __future__ import annotations

import asyncio
from typing import AsyncGenerator, Optional
import structlog

logger = structlog.get_logger(__name__)


class VoiceOrchestrator:
    """
    Stateful, per-session wrapper around the ai-orchestrator's core Orchestrator.

    Lifecycle:
        1. Created by voice_pipeline.handle_websocket() on call connect.
        2. Held in SessionState for the call's lifetime.
        3. Calls process_message() or stream_response() directly — no HTTP.
        4. Discarded when the WebSocket closes.
    """

    def __init__(
        self,
        tenant_id: str,
        agent_id: str,
        session_id: str,
        db,              # AsyncSession — passed from voice-pipeline's DB pool
        redis_client,    # aioredis client — shared with voice-pipeline
    ):
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.session_id = session_id
        self._db = db
        self._redis = redis_client
        self._orchestrator = None  # Lazy-loaded on first turn
        self._agent = None
        self._session = None

    async def _ensure_initialized(self):
        """
        Lazy-initializes the Orchestrator and loads Agent + Session from DB.
        Called before the first message — not in __init__ to avoid blocking
        the WebSocket handshake.
        """
        if self._orchestrator is not None:
            return

        # Import from shared library siblings
        from .llm_client import LLMClient
        from .mcp_client import MCPClient
        from .memory_manager import MemoryManager
        from .orchestrator import Orchestrator
        from .schemas.chat import StreamChatEvent
        
        # models still use app prefix because they are not yet fully moved to shared
        # and are available via orchestrator_src PYTHONPATH
        from app.models.agent import Agent, Session
        from app.core.config import settings as orc_settings
        from sqlalchemy import select
        import uuid

        llm_client = LLMClient(
            api_key=orc_settings.OPENAI_API_KEY,
            model=orc_settings.OPENAI_MODEL,
        )
        mcp_client = MCPClient(
            mcp_url=orc_settings.MCP_SERVER_URL,
            internal_api_key=orc_settings.INTERNAL_API_KEY,
        )
        memory_manager = MemoryManager(
            redis_client=self._redis,
            db=self._db,
        )

        self._orchestrator = Orchestrator(
            llm_client=llm_client,
            mcp_client=mcp_client,
            memory_manager=memory_manager,
            db=self._db,
            redis_client=self._redis,
        )

        # Load Agent
        agent_uuid = uuid.UUID(self.agent_id)
        result = await self._db.execute(select(Agent).where(Agent.id == agent_uuid))
        self._agent = result.scalar_one_or_none()
        if not self._agent:
            raise RuntimeError(f"Agent {self.agent_id} not found in DB")

        # Load or create Session
        result = await self._db.execute(
            select(Session).where(Session.id == self.session_id)
        )
        self._session = result.scalar_one_or_none()
        if not self._session:
            self._session = Session(
                id=self.session_id,
                tenant_id=uuid.UUID(self.tenant_id),
                agent_id=agent_uuid,
                channel="voice",
                status="active",
            )
            self._db.add(self._session)
            await self._db.flush()

        logger.info(
            "voice_orchestrator_initialized",
            session_id=self.session_id,
            agent_id=self.agent_id,
            in_process=True,
        )

    async def stream_response(
        self, user_message: str, request_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        Stream LLM tokens directly — no HTTP, no SSE, no JSON serialization.
        Yields text delta strings exactly as the Orchestrator's stream_response does.
        """
        await self._ensure_initialized()

        async for event in self._orchestrator.stream_response(
            agent=self._agent,
            session=self._session,
            user_message=user_message,
            request_id=request_id,
        ):
            if isinstance(event, StreamChatEvent):
                if event.type == "text_delta" and event.data:
                    yield str(event.data)
            elif isinstance(event, str):
                yield event

    async def cancel(self):
        """
        Called on barge-in — signals the orchestrator to stop generating.
        The asyncio task wrapping stream_response() is cancelled by the FSM;
        this method performs any additional cleanup.
        """
        logger.debug("voice_orchestrator_cancel", session_id=self.session_id)
        # The asyncio task cancellation in the FSM handles the stream teardown.
        # Future: could signal a CancellationToken to the LLM client here.

    async def close(self):
        """Called on WebSocket disconnect to flush session state to DB."""
        if self._session and self._db:
            try:
                from datetime import datetime, timezone
                self._session.status = "closed"
                self._session.ended_at = datetime.now(timezone.utc)
                await self._db.commit()
                logger.info("voice_session_committed", session_id=self.session_id)
            except Exception as e:
                logger.error("voice_session_commit_error", error=str(e))
