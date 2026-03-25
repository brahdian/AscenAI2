import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import sentry_sdk
import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.core.config import settings
from app.core.database import init_db, close_db
from app.core.redis_client import init_redis, close_redis, get_redis
from app.core.security import get_current_tenant

# ---------------------------------------------------------------------------
# Sentry
# ---------------------------------------------------------------------------
if getattr(settings, "SENTRY_DSN", ""):
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=getattr(settings, "ENVIRONMENT", "production"),
        release=f"ai-orchestrator@{settings.APP_VERSION}",
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
        ],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )
def _setup_opentelemetry() -> None:
    if not getattr(settings, "OTEL_ENABLED", False) or not getattr(settings, "OTEL_ENDPOINT", ""):
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        resource = Resource.create({"service.name": "ai-orchestrator", "service.version": settings.APP_VERSION})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.OTEL_ENDPOINT)))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument()
        logger.info("opentelemetry_initialized", endpoint=settings.OTEL_ENDPOINT)
    except ImportError:
        logger.warning("opentelemetry_packages_missing")


_setup_opentelemetry()

from app.services.llm_client import create_llm_client
from app.services.mcp_client import MCPClient
from app.services.memory_manager import MemoryManager
from app.services.orchestrator import Orchestrator
from app.api.v1 import chat as chat_router
from app.api.v1 import agents as agents_router
from app.api.v1 import sessions as sessions_router
from app.api.v1 import feedback as feedback_router
from app.api.v1 import analytics as analytics_router
from app.api.v1 import playbook as playbook_router
from app.api.v1 import guardrails as guardrails_router
from app.api.v1 import learning as learning_router

logger = structlog.get_logger(__name__)

# Global service instances
_llm_client = None
_mcp_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _llm_client, _mcp_client

    logger.info("ai_orchestrator_starting", version=settings.APP_VERSION)

    # Initialize database
    await init_db()
    logger.info("database_ready")

    # Initialize Redis
    redis_client = await init_redis()
    app.state.redis = redis_client
    logger.info("redis_ready")

    # Initialize LLM client
    _llm_client = create_llm_client()
    app.state.llm_client = _llm_client
    logger.info("llm_client_ready", provider=settings.LLM_PROVIDER, model=settings.GEMINI_MODEL if settings.LLM_PROVIDER == "gemini" else settings.OPENAI_MODEL)

    # Initialize MCP client
    _mcp_client = MCPClient(
        base_url=settings.MCP_SERVER_URL,
        ws_url=settings.MCP_WS_URL,
    )
    await _mcp_client.initialize()
    app.state.mcp_client = _mcp_client
    logger.info("mcp_client_ready", url=settings.MCP_SERVER_URL)

    logger.info("ai_orchestrator_started")
    yield

    # Shutdown
    logger.info("ai_orchestrator_shutting_down")
    await _mcp_client.close()
    await close_redis()
    await close_db()
    logger.info("ai_orchestrator_stopped")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI Orchestrator: handles reasoning, intent detection, memory, and MCP coordination",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(chat_router.router, prefix="/api/v1", tags=["chat"])
app.include_router(agents_router.router, prefix="/api/v1/agents", tags=["agents"])
app.include_router(sessions_router.router, prefix="/api/v1/sessions", tags=["sessions"])
app.include_router(feedback_router.router, prefix="/api/v1/feedback", tags=["feedback"])
app.include_router(analytics_router.router, prefix="/api/v1/analytics", tags=["analytics"])
app.include_router(playbook_router.router, prefix="/api/v1/agents", tags=["playbook"])
app.include_router(guardrails_router.router, prefix="/api/v1/agents", tags=["guardrails"])
app.include_router(learning_router.router, prefix="/api/v1/agents", tags=["learning"])

# Prometheus metrics
Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.get("/health", tags=["health"])
async def health_check():
    health_status = {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }
    try:
        redis = await get_redis()
        await redis.ping()
        health_status["redis"] = "connected"
    except Exception as exc:
        health_status["redis"] = f"error: {exc}"
        health_status["status"] = "degraded"

    return JSONResponse(content=health_status)


@app.get("/", tags=["health"])
async def root():
    return {"service": settings.APP_NAME, "version": settings.APP_VERSION, "status": "running"}


# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, session_key: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[session_key] = websocket
        logger.info("websocket_connected", session_key=session_key)

    def disconnect(self, session_key: str):
        self.active_connections.pop(session_key, None)
        logger.info("websocket_disconnected", session_key=session_key)

    async def send_json(self, session_key: str, data: dict):
        ws = self.active_connections.get(session_key)
        if ws:
            await ws.send_json(data)

    async def send_text(self, session_key: str, text: str):
        ws = self.active_connections.get(session_key)
        if ws:
            await ws.send_text(text)


manager = ConnectionManager()


def _verify_ws_token(token: str, path_tenant_id: str) -> Optional[str]:
    """
    Validate a JWT from a WebSocket handshake.
    Returns the tenant_id claim if valid AND it matches path_tenant_id, else None.
    """
    from jose import JWTError, jwt as jose_jwt
    try:
        payload = jose_jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        if payload.get("type") != "access":
            return None
        jwt_tenant = payload.get("tenant_id")
        if not jwt_tenant or jwt_tenant != path_tenant_id:
            return None
        return jwt_tenant
    except JWTError:
        return None


@app.websocket("/ws/{tenant_id}/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    tenant_id: str,
    session_id: str,
):
    # ── Authentication ────────────────────────────────────────────────────
    # Accept token from query param (?token=...) or Authorization header
    token = websocket.query_params.get("token") or ""
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token or not _verify_ws_token(token, tenant_id):
        await websocket.close(code=4401, reason="Unauthorized")
        logger.warning("websocket_auth_rejected", tenant_id=tenant_id, session_id=session_id)
        return

    session_key = f"{tenant_id}:{session_id}"
    await manager.connect(session_key, websocket)

    from app.core.database import AsyncSessionLocal
    from app.models.agent import Agent, Session as AgentSession
    from sqlalchemy import select

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "data": "Invalid JSON", "session_id": session_id})
                continue

            agent_id = payload.get("agent_id")
            message = payload.get("message", "")
            customer_identifier = payload.get("customer_identifier")

            if not agent_id or not message:
                await websocket.send_json({"type": "error", "data": "agent_id and message are required", "session_id": session_id})
                continue

            # Validate agent_id format before UUID conversion
            try:
                agent_uuid = uuid.UUID(agent_id)
                tenant_uuid = uuid.UUID(tenant_id)
            except ValueError:
                await websocket.send_json({"type": "error", "data": "Invalid agent_id or tenant_id format", "session_id": session_id})
                continue

            async with AsyncSessionLocal() as db:
                # Load agent — must belong to this tenant
                result = await db.execute(
                    select(Agent).where(
                        Agent.id == agent_uuid,
                        Agent.tenant_id == tenant_uuid,
                        Agent.is_active.is_(True),
                    )
                )
                agent = result.scalar_one_or_none()
                if not agent:
                    await websocket.send_json({"type": "error", "data": "Agent not found", "session_id": session_id})
                    continue

                # Load or create session — enforce tenant ownership
                sess_result = await db.execute(
                    select(AgentSession).where(
                        AgentSession.id == session_id,
                        AgentSession.tenant_id == tenant_uuid,
                    )
                )
                session_obj = sess_result.scalar_one_or_none()
                if not session_obj:
                    session_obj = AgentSession(
                        id=session_id,
                        tenant_id=tenant_uuid,
                        agent_id=agent.id,
                        customer_identifier=customer_identifier,
                        channel="web",
                        status="active",
                    )
                    db.add(session_obj)
                    await db.flush()

                redis_client = app.state.redis
                memory_manager = MemoryManager(redis_client=redis_client, db=db)
                orchestrator = Orchestrator(
                    llm_client=app.state.llm_client,
                    mcp_client=app.state.mcp_client,
                    memory_manager=memory_manager,
                    db=db,
                    redis_client=redis_client,
                )

                # Stream response via WebSocket
                async for event in orchestrator.stream_response(
                    agent=agent,
                    session=session_obj,
                    user_message=message,
                ):
                    await websocket.send_json({
                        "type": event.type,
                        "data": event.data,
                        "session_id": session_id,
                    })

                await db.commit()

    except WebSocketDisconnect:
        manager.disconnect(session_key)
    except Exception as exc:
        logger.error("websocket_error", session_key=session_key, error=str(exc))
        try:
            # Never expose internal error details to the client
            await websocket.send_json({"type": "error", "data": "An internal error occurred", "session_id": session_id})
        except Exception:
            pass
        manager.disconnect(session_key)
