from typing import AsyncGenerator
import time

import structlog
from sqlalchemy import text, event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import settings

logger = structlog.get_logger(__name__)
_SLOW_QUERY_THRESHOLD_MS = 500


class Base(DeclarativeBase):
    pass


# Use NullPool for SQLite (tests), regular pooling for PostgreSQL
_pool_kwargs: dict = {}
if "sqlite" not in settings.DATABASE_URL:
    _pool_kwargs = {
        "pool_size": 50,
        "max_overflow": 100,
        "pool_pre_ping": True,
        # Recycle connections every 30 min to avoid stale connections after
        # PostgreSQL keepalive / firewall idle-connection timeouts.
        "pool_recycle": 1800,
        "pool_timeout": 30,
    }
else:
    _pool_kwargs = {"poolclass": NullPool}

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    **_pool_kwargs,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# Phase 3.4: Slow Query Observability
@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault("query_start_time", []).append(time.monotonic())


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    elapsed_ms = (time.monotonic() - conn.info["query_start_time"].pop()) * 1000
    if elapsed_ms >= _SLOW_QUERY_THRESHOLD_MS:
        logger.warning(
            "slow_query_detected",
            elapsed_ms=round(elapsed_ms, 2),
            statement=statement[:500],
        )


async def get_db(tenant_id: str | None = None, bypass_rls: bool = False) -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            # SECURITY: Set the per-session Postgres variable that RLS policies
            # use to filter rows by tenant. SET LOCAL scopes this to the
            # current transaction only — it cannot leak across connections.
            if bypass_rls:
                logger.warning("rls_bypassed", tenant_id=tenant_id, action="database_access")
                await session.execute(text("SET LOCAL row_security = 'off'"))
            elif tenant_id:
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, true)"),
                    {"tid": str(tenant_id)},
                )
            yield session
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.error("database_session_error", error=str(exc))
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create all tables (dev / testing only — use Alembic in production)."""
    # Register all models before create_all
    import app.models.audit_log  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # audit_logs schema is managed by Alembic migration 0008.
        # alembic upgrade head runs before this in the startup command.

        # Idempotent migration for missing tenant subscription columns
        await conn.execute(
            text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(50);")
        )
        await conn.execute(
            text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS subscription_id VARCHAR(255);")
        )

        # Idempotent migration for missing agent_count column
        await conn.execute(
            text("ALTER TABLE tenant_usage ADD COLUMN IF NOT EXISTS agent_count INTEGER DEFAULT 0 NOT NULL;")
        )
        await conn.execute(
            text("ALTER TABLE tenant_usage ADD COLUMN IF NOT EXISTS current_month_chat_units INTEGER DEFAULT 0;")
        )
    logger.info("database_initialized")


async def close_db() -> None:
    await engine.dispose()
    logger.info("database_connection_closed")
