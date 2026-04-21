import asyncio
import time
import uuid
from contextlib import asynccontextmanager

import sentry_sdk
import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from redis.asyncio import Redis
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.redis import RedisIntegration
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.database import close_db, init_db
from app.core.scheduler import BACKGROUND_TASKS
from app.core.tracing import TracingMiddleware
from app.middleware.auth import AuthMiddleware
from app.middleware.rate_limiter import RateLimitMiddleware
from app.middleware.security import SecurityHeadersMiddleware
from app.middleware.logging import RequestLoggingMiddleware

from app.api.v1 import auth, tenants, api_keys, webhooks, proxy, team, billing, compliance
from app.api.v1 import channels as channels_router
from app.api.v1 import admin as admin_router
from app.api.v1 import compliance_audit as compliance_audit_router
from app.api.v1 import playbooks as playbooks_router
from app.api.v1 import console as console_router
from app.utils.pii import mask_sensitive_data


logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Sentry (initialized at module load so it captures startup errors too)
# ---------------------------------------------------------------------------
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        release=f"api-gateway@{settings.APP_VERSION}",
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
            RedisIntegration(),
        ],
        traces_sample_rate=0.1,
        profiles_sample_rate=0.05,
        send_default_pii=False,
    )
    logger.info("sentry_initialized", service="api-gateway")

# ---------------------------------------------------------------------------
# Rate limiter (sliding window using Redis)
# ---------------------------------------------------------------------------

redis_client: Redis | None = None


async def get_redis() -> Redis:
    global redis_client
    if redis_client is None:
        redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return redis_client


# Middlewares are now imported from app.middleware.*




# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


def _setup_opentelemetry(app: FastAPI) -> None:
    """Wire OpenTelemetry tracing if enabled."""
    if not getattr(settings, "OTEL_ENABLED", False) or not getattr(settings, "OTEL_ENDPOINT", ""):
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        resource = Resource.create({"service.name": "api-gateway", "service.version": settings.APP_VERSION})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.OTEL_ENDPOINT)))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor().instrument_app(app)
        logger.info("opentelemetry_initialized", endpoint=settings.OTEL_ENDPOINT)
    except ImportError:
        logger.warning("opentelemetry_packages_missing")





@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("api_gateway_starting", version=settings.APP_VERSION)
    await init_db()

    global redis_client
    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    app.state.redis = redis_client  # expose for password reset and other routes
    logger.info("redis_connected", url=settings.REDIS_URL)

    # Automatically start all native asyncio background loops
    bg_tasks = []
    for coroutine_func in BACKGROUND_TASKS:
        # Determine if it needs Redis (the first two loops do, the purge loop doesn't)
        if coroutine_func.__name__ == "_audit_purge_loop":
            task = asyncio.create_task(coroutine_func())
        else:
            task = asyncio.create_task(coroutine_func(redis=redis_client))
        bg_tasks.append(task)
        
    logger.info("background_scheduler_started", tasks_running=len(bg_tasks))

    app.state.startup_complete = True
    logger.info("api_gateway_started")

    # Serve requests
    yield

    # Clean shutdown
    for task in bg_tasks:
        task.cancel()
        
    # Wait briefly for tasks to acknowledge cancellation
    await asyncio.gather(*bg_tasks, return_exceptions=True)
    logger.info("background_scheduler_stopped")

    await close_db()
    if redis_client:
        await redis_client.aclose()
    logger.info("api_gateway_stopped")



# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AscenAI API Gateway",
    version=settings.APP_VERSION,
    description="Single entry point for all AscenAI frontend requests.",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

_setup_opentelemetry(app)

# --- Middlewares (Added inside out: last added is outermost in execution) ---

# 1. Rate limiting (Innermost, relies on Auth having run)
app.add_middleware(RateLimitMiddleware)

# 2. Auth (Protects the router, sets request.state.user for ratelimit)
app.add_middleware(AuthMiddleware)

# 3. Request logging 
app.add_middleware(RequestLoggingMiddleware)

# 4. CORS (Must be outer so it catches 401s from Auth and 429s from RateLimit)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-ID", "X-Response-Time", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)

# 5. Quality of Service / Security Headers (Outermost)
app.add_middleware(SecurityHeadersMiddleware)

# 6. W3C traceparent propagation (Wraps everything)
app.add_middleware(TracingMiddleware)


# --- Global Exception Handlers ----------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Hardened error handler: returns only a trace_id to the client.
    Internal details are logged but never exposed (Anti-Information Disclosure).
    """
    trace_id = getattr(request.state, "trace_id", "none")
    
    # 1. Log the full traceback internally for SREs
    logger.exception(
        "unhandled_exception",
        trace_id=trace_id,
        method=request.method,
        path=request.url.path,
        error=str(exc)
    )
    
    # 2. Return sanitized response (Zenith Pillar 5: Stealth)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal Server Error",
            "trace_id": trace_id
        }
    )



# --- Prometheus metrics -----------------------------------------------------
Instrumentator().instrument(app).expose(app, endpoint="/metrics")

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(tenants.router, prefix="/api/v1", tags=["tenants"])
app.include_router(api_keys.router, prefix="/api/v1", tags=["api-keys"])
app.include_router(webhooks.router, prefix="/api/v1", tags=["webhooks"])
app.include_router(team.router, prefix="/api/v1", tags=["team"])
app.include_router(billing.router, prefix="/api/v1", tags=["billing"])
app.include_router(compliance.router, prefix="/api/v1", tags=["compliance"])
app.include_router(proxy.router, prefix="/api/v1", tags=["proxy"])
app.include_router(channels_router.router, prefix="/api/v1/channels", tags=["channels"])
app.include_router(admin_router.router, prefix="/api/v1", tags=["admin"])
app.include_router(compliance_audit_router.router, prefix="/api/v1", tags=["compliance-audit"])
app.include_router(playbooks_router.router, prefix="/api/v1", tags=["playbooks"])
app.include_router(console_router.router, prefix="/api/v1", tags=["console"])

# ── Static assets — widget.js served at /widget/widget.js ─────────────────
import os as _os
_static_dir = _os.path.join(_os.path.dirname(__file__), "..", "static")
if _os.path.isdir(_static_dir):
    app.mount("/widget", StaticFiles(directory=_static_dir), name="widget")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health", include_in_schema=False)
async def health():
    checks: dict = {"status": "ok", "service": "api-gateway"}
    try:
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"
        checks["status"] = "degraded"
    return checks


@app.get("/health/startup", include_in_schema=False)
async def health_startup(request: Request):
    """Kubernetes startupProbe — heavy check: DB + Redis. Returns 503 until startup_complete."""
    if not getattr(request.app.state, "startup_complete", False):
        return JSONResponse(status_code=503, content={"status": "starting", "service": "api-gateway"})

    checks: dict = {"status": "ok", "service": "api-gateway"}
    failed = False

    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"error: {exc}"
        failed = True

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
async def health_ready(request: Request):
    """Kubernetes readinessProbe — checks DB + Redis. Returns 503 if a critical dependency is down."""
    checks: dict = {"status": "ok", "service": "api-gateway"}
    failed = False

    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"error: {exc}"
        failed = True

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
