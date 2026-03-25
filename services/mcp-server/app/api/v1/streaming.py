from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.schemas.mcp import StreamMessage, WebSocketMessage

logger = structlog.get_logger(__name__)
router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self.active: dict[str, WebSocket] = {}

    async def connect(self, client_id: str, ws: WebSocket):
        await ws.accept()
        self.active[client_id] = ws
        logger.info("ws_connected", client_id=client_id, total=len(self.active))

    def disconnect(self, client_id: str):
        self.active.pop(client_id, None)
        logger.info("ws_disconnected", client_id=client_id, total=len(self.active))

    async def send(self, client_id: str, msg: dict):
        ws = self.active.get(client_id)
        if ws:
            await ws.send_json(msg)


manager = ConnectionManager()


def _verify_ws_token(token: str, path_tenant_id: str) -> bool:
    """Verify JWT access token and confirm tenant claim matches URL path."""
    try:
        from jose import jwt as jose_jwt
        payload = jose_jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        if payload.get("type") != "access":
            return False
        jwt_tenant = payload.get("tenant_id")
        return bool(jwt_tenant and jwt_tenant == path_tenant_id)
    except Exception:
        return False


@router.websocket("/ws/{tenant_id}")
async def websocket_endpoint(websocket: WebSocket, tenant_id: str):
    """
    WebSocket endpoint for real-time MCP streaming.
    Clients send WebSocketMessage JSON; server responds with StreamMessage JSON.
    """
    token = websocket.query_params.get("token", "")
    if not token or not _verify_ws_token(token, tenant_id):
        await websocket.close(code=4401, reason="Unauthorized")
        return

    client_id = f"{tenant_id}:{uuid.uuid4()}"
    await manager.connect(client_id, websocket)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
                msg = WebSocketMessage(**data)
            except Exception:
                await websocket.send_json(
                    {
                        "type": "error",
                        "payload": {"message": "Invalid message format"},
                        "trace_id": "",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
                continue

            if msg.type == "ping":
                await websocket.send_json(
                    {
                        "type": "pong",
                        "payload": {},
                        "trace_id": msg.trace_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )

            elif msg.type == "tool_call":
                # Delegate to tool executor
                from app.core.database import AsyncSessionLocal
                from app.services.tool_executor import ToolExecutor
                from app.services.tool_registry import ToolRegistry
                from app.schemas.mcp import MCPToolCall

                try:
                    tool_call = MCPToolCall(**msg.payload)
                    async with AsyncSessionLocal() as db:
                        registry = ToolRegistry(db)
                        executor = ToolExecutor(db, registry)
                        result = await executor.execute(tenant_id, tool_call)
                    await websocket.send_json(
                        {
                            "type": "tool_result",
                            "payload": result.model_dump(),
                            "trace_id": msg.trace_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                except Exception as exc:
                    logger.error("tool_call_error", tenant_id=tenant_id, error=str(exc))
                    await websocket.send_json(
                        {
                            "type": "error",
                            "payload": {"message": "Tool execution failed"},
                            "trace_id": msg.trace_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )

            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "payload": {"message": f"Unknown message type: {msg.type}"},
                        "trace_id": msg.trace_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )

    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as exc:
        logger.error("ws_error", client_id=client_id, error=str(exc))
        manager.disconnect(client_id)
