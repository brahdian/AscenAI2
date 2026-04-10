import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis
import sentry_sdk
import structlog
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.redis import RedisIntegration
from sqlalchemy import text

from app.core.config import settings
from app.core.database import close_db, init_db, SessionLocal
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.tenant import TenantMiddleware
from app.schemas.mcp import HealthResponse, StreamMessage, WebSocketMessage
from app.services import pii_service

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

        resource = Resource.create({"service.name": "mcp-server", "service.version": settings.APP_VERSION})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.OTEL_ENDPOINT)))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument()
        logger.info("opentelemetry_initialized", endpoint=settings.OTEL_ENDPOINT)
    except ImportError:
        logger.warning("opentelemetry_packages_missing")


_setup_opentelemetry()

# ---------------------------------------------------------------------------
# Sentry
# ---------------------------------------------------------------------------
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=getattr(settings, "ENVIRONMENT", "production"),
        release=f"mcp-server@{settings.APP_VERSION}",
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
            RedisIntegration(),
        ],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )

# Module-level Redis client (shared)
redis_client: aioredis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown logic."""
    global redis_client
    logger.info("mcp_server_starting", version=settings.APP_VERSION)

    # --- Startup ---
    # 1. Initialize database tables
    try:
        await init_db()
        logger.info("database_initialized")
    except Exception as exc:
        logger.error("database_init_failed", error=str(exc))
        raise

    # 2. Connect to Redis
    try:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        await redis_client.ping()
        # Store on app state so middleware/routes can access it
        app.state.redis = redis_client
        logger.info("redis_connected", url=settings.REDIS_URL)
    except Exception as exc:
        logger.error("redis_connect_failed", error=str(exc))
        raise

    # 3. Warm up PII service (Presidio)
    try:
        await pii_service.warmup()
        logger.info("pii_service_initialized")
    except Exception as exc:
        logger.error("pii_service_init_failed", error=str(exc))
        # Don't fail the whole app if PII fails, but log it loudly

    logger.info("mcp_server_ready")
    yield

    # --- Shutdown ---
    logger.info("mcp_server_shutting_down")
    if redis_client:
        await redis_client.aclose()
        logger.info("redis_disconnected")
    await close_db()
    logger.info("mcp_server_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="MCP (Model Context Protocol) Server — multi-tenant AI tool orchestration",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ---- Middlewares (order matters: outermost first) ----

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=settings.ALLOWED_METHODS,
        allow_headers=settings.ALLOWED_HEADERS,
    )

    # Tenant extraction (populates request.state.tenant_id)
    app.add_middleware(TenantMiddleware)

    # Sliding-window rate limiter
    app.add_middleware(RateLimitMiddleware)

    # ---- Prometheus metrics ----
    if settings.PROMETHEUS_ENABLED:
        Instrumentator().instrument(app).expose(app, endpoint="/metrics")

    # ---- Routers ----
    from app.api.v1.tools import router as tools_router
    from app.api.v1.execution import router as execution_router
    from app.api.v1.context import router as context_router
    from app.api.v1.streaming import router as streaming_router

    app.include_router(tools_router, prefix="/api/v1", tags=["tools"])
    app.include_router(execution_router, prefix="/api/v1", tags=["execution"])
    app.include_router(context_router, prefix="/api/v1", tags=["context"])
    app.include_router(streaming_router, tags=["streaming"])

    from app.api.v1.webhooks import router as webhooks_router
    app.include_router(webhooks_router, prefix="/api/v1", tags=["webhooks"])

    # ---- Health check ----
    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health_check() -> HealthResponse:
        db_status = "ok"
        redis_status = "ok"

        # Check DB
        try:
            async with SessionLocal() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:
            db_status = f"error: {exc}"

        # Check Redis
        try:
            r: aioredis.Redis = app.state.redis
            await r.ping()
        except Exception as exc:
            redis_status = f"error: {exc}"

        overall = "ok" if all(
            s == "ok" for s in [db_status, redis_status]
        ) else "degraded"

        return HealthResponse(
            status=overall,
            version=settings.APP_VERSION,
            database=db_status,
            redis=redis_status,
        )

    # ---- Global exception handler ----
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=str(exc),
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "type": type(exc).__name__},
        )

    return app


app = create_app()
