from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.redis_client import init_redis, close_redis
from app.api.v1 import voice as voice_router

logger = structlog.get_logger(__name__)


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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("voice_pipeline_starting", version=settings.APP_VERSION)
    redis = await init_redis()
    app.state.redis = redis
    logger.info("voice_pipeline_ready")
    yield
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


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "service": settings.APP_NAME, "version": settings.APP_VERSION}


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
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        await pipeline.on_disconnect()
        manager.disconnect(client_id)
