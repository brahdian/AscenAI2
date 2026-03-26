import time
import uuid
from contextlib import asynccontextmanager

import sentry_sdk
import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from redis.asyncio import Redis
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.redis import RedisIntegration
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.database import close_db, init_db
from app.middleware.auth import AuthMiddleware
from app.api.v1 import auth, tenants, api_keys, webhooks, proxy, team, billing

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


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Token-bucket rate limiter backed by Redis.
    Key is tenant_id when authenticated, otherwise IP address.
    Default: 300 requests / minute per tenant, 30 / minute for unauthenticated.
    """

    EXEMPT_PATHS = {"/health", "/metrics"}

    async def dispatch(self, request: Request, call_next: object) -> Response:
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        tenant_id = getattr(request.state, "tenant_id", None)
        if tenant_id:
            key = f"ratelimit:tenant:{tenant_id}"
            limit = 300
        else:
            client_ip = request.client.host if request.client else "unknown"
            key = f"ratelimit:ip:{client_ip}"
            limit = 30

        redis = await get_redis()
        now = int(time.time())
        window_key = f"{key}:{now // 60}"

        try:
            # Atomic INCR + EXPIRE via Lua script to avoid a race where INCR
            # succeeds but EXPIRE is never called (e.g. crash between the two),
            # which would leave the counter key without a TTL and block forever.
            _lua = """
local c = redis.call('INCR', KEYS[1])
if c == 1 then redis.call('EXPIRE', KEYS[1], 120) end
return c
"""
            count = await redis.eval(_lua, 1, window_key)
        except Exception:
            # If Redis is down, allow the request through
            count = 0

        if count > limit:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Please slow down.",
                    "retry_after": 60 - (now % 60),
                },
                headers={"Retry-After": str(60 - (now % 60))},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Attach a trace ID to every request and log request/response."""

    async def dispatch(self, request: Request, call_next: object) -> Response:
        trace_id = request.headers.get("X-Trace-ID") or str(uuid.uuid4())
        request.state.trace_id = trace_id

        start = time.perf_counter()
        logger.info(
            "request_started",
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
            query=str(request.query_params),
        )

        response: Response = await call_next(request)

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "request_finished",
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Response-Time"] = f"{duration_ms}ms"
        return response


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


def _setup_opentelemetry() -> None:
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
        FastAPIInstrumentor.instrument()
        logger.info("opentelemetry_initialized", endpoint=settings.OTEL_ENDPOINT)
    except ImportError:
        logger.warning("opentelemetry_packages_missing")


_setup_opentelemetry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("api_gateway_starting", version=settings.APP_VERSION)
    await init_db()

    global redis_client
    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    app.state.redis = redis_client  # expose for password reset and other routes
    logger.info("redis_connected", url=settings.REDIS_URL)

    yield

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

# --- CORS (must be first so preflight requests are handled) ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-ID", "X-Response-Time", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)

# --- Request logging --------------------------------------------------------
app.add_middleware(RequestLoggingMiddleware)

# --- Auth (sets request.state.user / tenant_id) ----------------------------
app.add_middleware(AuthMiddleware)

# --- Rate limiting (reads tenant_id set by AuthMiddleware) -----------------
app.add_middleware(RateLimitMiddleware)

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
app.include_router(proxy.router, prefix="/api/v1", tags=["proxy"])


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
