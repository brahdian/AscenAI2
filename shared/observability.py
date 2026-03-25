"""
Shared observability utilities.
Import and call `setup_observability(app, settings)` in each service's lifespan
or module-level init.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import structlog


def setup_sentry(dsn: Optional[str], service_name: str, version: str, environment: str = "production") -> None:
    """Initialize Sentry SDK if DSN is configured."""
    if not dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.redis import RedisIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=f"{service_name}@{version}",
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
                RedisIntegration(),
                LoggingIntegration(
                    level=logging.WARNING,
                    event_level=logging.ERROR,
                ),
            ],
            traces_sample_rate=0.1,
            profiles_sample_rate=0.05,
            send_default_pii=False,
        )
        structlog.get_logger(__name__).info(
            "sentry_initialized", service=service_name, environment=environment
        )
    except ImportError:
        structlog.get_logger(__name__).warning(
            "sentry_sdk_not_installed",
            hint="pip install sentry-sdk[fastapi]",
        )


def setup_logging(log_level: str = "INFO", service_name: str = "service") -> None:
    """Configure structlog for JSON output in production."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def setup_opentelemetry(
    service_name: str,
    otlp_endpoint: Optional[str] = None,
    enabled: bool = True,
) -> None:
    """
    Set up OpenTelemetry tracing with OTLP export.
    Falls back gracefully if packages are not installed.
    """
    if not enabled or not otlp_endpoint:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        FastAPIInstrumentor.instrument()
        SQLAlchemyInstrumentor().instrument()
        HTTPXClientInstrumentor().instrument()

        structlog.get_logger(__name__).info(
            "opentelemetry_initialized",
            service=service_name,
            endpoint=otlp_endpoint,
        )
    except ImportError:
        structlog.get_logger(__name__).warning(
            "opentelemetry_packages_not_installed",
            hint="pip install opentelemetry-sdk opentelemetry-exporter-otlp opentelemetry-instrumentation-fastapi",
        )
