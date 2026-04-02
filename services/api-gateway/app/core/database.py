from typing import AsyncGenerator

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import settings

logger = structlog.get_logger(__name__)


class Base(DeclarativeBase):
    pass


# Use NullPool for SQLite (tests), regular pooling for PostgreSQL
_pool_kwargs: dict = {}
if "sqlite" not in settings.DATABASE_URL:
    _pool_kwargs = {
        "pool_size": 10,
        "max_overflow": 20,
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


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
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
