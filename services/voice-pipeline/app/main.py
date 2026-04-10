from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import sentry_sdk
import structlog
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sentry_sdk.integrations.fastapi import FastApiIntegration

from app.core.config import settings
from app.core.redis_client import init_redis, close_redis, get_redis
from app.api.v1 import voice as voice_router

# ---------------------------------------------------------------------------
# Sentry
# ---------------------------------------------------------------------------
if getattr(settings, "SENTRY_DSN", ""):
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=getattr(settings, "ENVIRONMENT", "production"),
        release=f"voice-pipeline@{settings.APP_VERSION}",
        integrations=[FastApiIntegration(transaction_style="endpoint")],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )

logger = structlog.get_logger(__name__)


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

        resource = Resource.create({"service.name": "voice-pipeline", "service.version": settings.APP_VERSION})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.OTEL_ENDPOINT)))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument()
        logger.info("opentelemetry_initialized", endpoint=settings.OTEL_ENDPOINT)
    except ImportError:
        logger.warning("opentelemetry_packages_missing")


_setup_opentelemetry()


class ConnectionManager:
    """Track active WebSocket connections."""

    def __init__(self):
        self.active: dict[str, WebSocket] = {}

    async def connect(self, client_id: str, ws: WebSocket):
        await ws.accept()
        self.active[client_id] = ws
        logger.info("voice_ws_connected", client_id=client_id)

    def disconnect(self, client_id: str):
        self.active.pop(client_id, None)
        logger.info("voice_ws_disconnected", client_id=client_id)

    async def send_json(self, client_id: str, data: dict):
        ws = self.active.get(client_id)
        if ws:
            await ws.send_json(data)

    async def send_bytes(self, client_id: str, data: bytes):
        ws = self.active.get(client_id)
        if ws:
            await ws.send_bytes(data)


manager = ConnectionManager()


_AUDIO_CLEANUP_DIRS = [
    Path(os.environ.get("GREETING_AUDIO_PATH", "/tmp/voice-greetings")),
    Path(os.environ.get("TTS_AUDIO_PATH", "/tmp/tts-cache")),
]
_AUDIO_MAX_AGE_SECONDS = 86400  # 24 hours


async def _cleanup_audio_files() -> None:
    """Periodically remove audio files older than 24 hours to prevent disk exhaustion."""
    while True:
        try:
            await asyncio.sleep(3600)  # run every hour
            cutoff = time.time() - _AUDIO_MAX_AGE_SECONDS
            for base_dir in _AUDIO_CLEANUP_DIRS:
                if not base_dir.exists():
                    continue
                removed = 0
                for f in base_dir.iterdir():
                    if f.is_file() and f.stat().st_mtime < cutoff:
                        f.unlink(missing_ok=True)
                        removed += 1
                if removed:
                    logger.info("audio_cleanup_complete", directory=str(base_dir), removed=removed)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("audio_cleanup_error", error=type(exc).__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("voice_pipeline_starting", version=settings.APP_VERSION)

    # Ensure audio directories exist
    for d in _AUDIO_CLEANUP_DIRS:
        d.mkdir(parents=True, exist_ok=True)

    redis = await init_redis()
    app.state.redis = redis

    # Pre-synthesise backchannel filler clips to disk so they are ready for realtime use
    try:
        from app.services.voice_pipeline import VoicePipeline
        from app.services.stt_service import STTService
        from app.services.tts_service import TTSService
        # Instantiate temporarily just to run the synthesis
        temp_pipeline = VoicePipeline(
            stt=STTService(),
            tts=TTSService(),
            orchestrator_url="",
            redis=None
        )
        # Note: _presynthesize_backchannels is a fast no-op if files already exist
        await temp_pipeline._presynthesize_backchannels()
    except Exception as exc:
        logger.error("backchannel_presynthesis_failed", error=str(exc))

    # Start audio cleanup background task
    cleanup_task = asyncio.create_task(_cleanup_audio_files())

    app.state.startup_complete = True
    logger.info("voice_pipeline_ready")
    yield

    cleanup_task.cancel()
    await asyncio.gather(cleanup_task, return_exceptions=True)
    await close_redis()
    logger.info("voice_pipeline_stopped")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Real-time voice pipeline: STT → AI Orchestrator → TTS",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(voice_router.router, prefix="/api/v1", tags=["voice"])

# Prometheus metrics
Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "service": settings.APP_NAME, "version": settings.APP_VERSION}


@app.get("/health/startup", include_in_schema=False)
async def health_startup(request: Request):
    """Kubernetes startupProbe — Redis check. Returns 503 until startup_complete."""
    if not getattr(request.app.state, "startup_complete", False):
        return JSONResponse(status_code=503, content={"status": "starting", "service": settings.APP_NAME})

    checks: dict = {"status": "ok", "service": settings.APP_NAME}
    failed = False

    try:
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"
        failed = True

    if failed:
        checks["status"] = "degraded"
        return JSONResponse(status_code=503, content=checks)
    return checks


@app.get("/health/ready", include_in_schema=False)
async def health_ready():
    """Kubernetes readinessProbe — Redis fast check. Returns 503 if Redis is down."""
    checks: dict = {"status": "ok", "service": settings.APP_NAME}
    failed = False

    try:
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"
        failed = True

    if failed:
        checks["status"] = "degraded"
        return JSONResponse(status_code=503, content=checks)
    return checks


@app.get("/health/live", include_in_schema=False)
async def health_live():
    """Kubernetes livenessProbe — lightweight check that process and event loop are alive."""
    return {"alive": True}


def _verify_ws_token(token: str, path_tenant_id: str) -> bool:
    """Verify JWT and confirm tenant_id claim matches the URL path."""
    try:
        from jose import jwt as jose_jwt, JWTError
        payload = jose_jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        if payload.get("type") != "access":
            return False
        jwt_tenant = payload.get("tenant_id")
        return bool(jwt_tenant and jwt_tenant == path_tenant_id)
    except Exception:
        return False


@app.websocket("/ws/voice/{tenant_id}/{session_id}")
async def voice_websocket(
    websocket: WebSocket,
    tenant_id: str,
    session_id: str,
):
    """
    WebSocket endpoint for bidirectional real-time voice.

    Client sends:
      - Binary frames: raw PCM audio chunks (16-bit, 16kHz mono)
      - JSON text frames: control messages {"type": "start"|"stop"|"config", ...}

    Server sends:
      - Binary frames: TTS audio (MP3 or PCM)
      - JSON text frames: transcript & status events
    """
    token = websocket.query_params.get("token", "")
    if not token or not _verify_ws_token(token, tenant_id):
        await websocket.close(code=4401, reason="Unauthorized")
        return

    client_id = f"{tenant_id}:{session_id}"
    await manager.connect(client_id, websocket)

    from app.services.voice_pipeline import VoicePipeline

    pipeline = VoicePipeline(
        tenant_id=tenant_id,
        session_id=session_id,
        settings=settings,
    )

    try:
        await pipeline.on_connect()
        await manager.send_json(client_id, {"type": "ready", "session_id": session_id})

        while True:
            try:
                message = await websocket.receive()
            except WebSocketDisconnect:
                break

            if "bytes" in message and message["bytes"]:
                audio_chunk: bytes = message["bytes"]
                async for response in pipeline.process_audio_chunk(audio_chunk):
                    if response["type"] == "audio":
                        await manager.send_bytes(client_id, response["data"])
                    else:
                        await manager.send_json(client_id, response)

            elif "text" in message and message["text"]:
                try:
                    ctrl = json.loads(message["text"])
                except json.JSONDecodeError:
                    await manager.send_json(
                        client_id, {"type": "error", "message": "Invalid JSON"}
                    )
                    continue

                result = await pipeline.handle_control(ctrl)
                if result:
                    await manager.send_json(client_id, result)

    except Exception as exc:
        logger.error("voice_ws_error", client_id=client_id, error=str(exc))
        try:
            await websocket.send_json({"type": "error", "message": "An internal error occurred"})
        except Exception:
            pass
    finally:
        await pipeline.on_disconnect()
        manager.disconnect(client_id)


@app.websocket("/ws/voice/{agent_id}")
async def voice_websocket_agent(
    websocket: WebSocket,
    agent_id: str,
):
    """
    WebSocket endpoint for real-time voice — agent-scoped path used by
    Twilio Media Streams and browser clients that embed agent_id in the path.

    Twilio connects here when the TwiML ``<Stream>`` URL is:
      ``wss://{host}/ws/voice/{agent_id}?tenant_id=...&session_id=...&token=...``

    Browser clients can also use this endpoint to avoid encoding tenant/session
    in the path (they pass them as query parameters instead).

    Query parameters:
      tenant_id  — required; must match the JWT claim
      session_id — optional; auto-generated if absent
      token      — required JWT access token
    """
    from app.services.voice_pipeline import VoicePipeline
    from app.services.stt_service import STTService
    from app.services.tts_service import TTSService

    tenant_id = websocket.query_params.get("tenant_id", "")
    session_id = websocket.query_params.get("session_id") or str(uuid.uuid4())
    token = websocket.query_params.get("token", "")

    if not tenant_id or not token:
        await websocket.close(code=4401, reason="tenant_id and token are required")
        return

    redis = getattr(app.state, "redis", None)

    pipeline = VoicePipeline(
        stt=STTService(),
        tts=TTSService(),
        orchestrator_url=settings.AI_ORCHESTRATOR_URL,
        redis=redis,
    )

    try:
        await pipeline.handle_websocket(
            websocket=websocket,
            tenant_id=tenant_id,
            session_id=session_id,
            agent_id=agent_id,
            token=token,
        )
    except Exception as exc:
        logger.error("voice_ws_agent_error", agent_id=agent_id, error=str(exc))
        try:
            if websocket.client_state.value == 1:  # CONNECTED
                await websocket.send_text(
                    json.dumps({"type": "error", "message": "An internal error occurred"})
                )
        except Exception:
            pass
    finally:
        await pipeline.close()
