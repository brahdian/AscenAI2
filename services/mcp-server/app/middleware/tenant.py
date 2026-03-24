from typing import Optional

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from app.core.security import extract_tenant_from_token, hash_api_key

logger = structlog.get_logger(__name__)

# Paths that don't require tenant identification
SKIP_PATHS = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
}


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Extract tenant_id from one of three sources (in priority order):
    1. Authorization: Bearer <JWT>  —  reads 'tenant_id' or 'sub' claim
    2. X-Tenant-ID header           —  direct tenant UUID header
    3. X-API-Key header             —  looks up the hashed key in the database

    Sets request.state.tenant_id (str UUID) on success.
    Returns HTTP 403 if no valid tenant could be resolved for protected routes.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        # Skip health / docs / metrics
        if path in SKIP_PATHS or path.startswith("/metrics"):
            return await call_next(request)

        tenant_id: Optional[str] = None

        # --- 1. JWT Bearer token ---
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):]
            tenant_id = extract_tenant_from_token(token)
            if tenant_id:
                logger.debug("tenant_from_jwt", tenant_id=tenant_id, path=path)

        # --- 2. X-Tenant-ID header (plain UUID or slug) ---
        if not tenant_id:
            tenant_id = request.headers.get("X-Tenant-ID")
            if tenant_id:
                logger.debug("tenant_from_header", tenant_id=tenant_id, path=path)

        # --- 3. API Key lookup ---
        if not tenant_id:
            api_key = request.headers.get("X-API-Key")
            if api_key:
                tenant_id = await self._lookup_api_key(request, api_key)
                if tenant_id:
                    logger.debug("tenant_from_api_key", tenant_id=tenant_id, path=path)

        # --- WebSocket paths: tenant_id is in the path itself ---
        # e.g. /ws/{tenant_id}/{session_id}
        if not tenant_id and path.startswith("/ws/"):
            parts = path.split("/")  # ['', 'ws', tenant_id, session_id]
            if len(parts) >= 3 and parts[2]:
                tenant_id = parts[2]
                logger.debug("tenant_from_ws_path", tenant_id=tenant_id, path=path)

        if not tenant_id:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Tenant identification required. "
                              "Provide a Bearer token, X-Tenant-ID header, or X-API-Key."
                },
            )

        request.state.tenant_id = tenant_id
        response = await call_next(request)
        return response

    @staticmethod
    async def _lookup_api_key(request: Request, api_key: str) -> Optional[str]:
        """Look up the hashed API key in the database and return tenant_id."""
        try:
            from app.core.database import SessionLocal
            from sqlalchemy import text

            hashed = hash_api_key(api_key)
            async with SessionLocal() as session:
                result = await session.execute(
                    text(
                        "SELECT tenant_id FROM api_keys "
                        "WHERE key_hash = :key_hash AND is_active = true LIMIT 1"
                    ),
                    {"key_hash": hashed},
                )
                row = result.fetchone()
                if row:
                    return str(row[0])
        except Exception as exc:
            logger.warning("api_key_db_lookup_failed", error=str(exc))
        return None
