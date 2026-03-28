from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool
from typing import AsyncGenerator
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


class Base(DeclarativeBase):
    pass


_is_sqlite = "sqlite" in settings.DATABASE_URL
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    poolclass=NullPool if _is_sqlite else None,
    pool_pre_ping=True,
    pool_size=10 if not _is_sqlite else None,
    max_overflow=20 if not _is_sqlite else None,
    # Recycle connections every 30 min to avoid stale TCP connections after
    # PostgreSQL's tcp_keepalives_idle or firewall idle-connection timeouts.
    pool_recycle=1800 if not _is_sqlite else None,
    pool_timeout=30 if not _is_sqlite else None,
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Idempotent ALTER TABLE migrations for columns added after initial create_all.
        # Safe to run on every startup — IF NOT EXISTS prevents errors on re-run.
        await conn.execute(
            __import__("sqlalchemy", fromlist=["text"]).text(
                "ALTER TABLE message_feedback "
                "ADD COLUMN IF NOT EXISTS playbook_correction JSONB"
            )
        )
        await conn.execute(
            __import__("sqlalchemy", fromlist=["text"]).text(
                "ALTER TABLE message_feedback "
                "ADD COLUMN IF NOT EXISTS tool_corrections JSONB"
            )
        )
        await conn.execute(
            __import__("sqlalchemy", fromlist=["text"]).text(
                "ALTER TABLE agents "
                "ADD COLUMN IF NOT EXISTS greeting_message TEXT"
            )
        )
        await conn.execute(
            __import__("sqlalchemy", fromlist=["text"]).text(
                "ALTER TABLE agents "
                "ADD COLUMN IF NOT EXISTS voice_greeting_url VARCHAR(500)"
            )
        )
        # Escalation audit trail — DLQ for failed connector attempts
        _t = __import__("sqlalchemy", fromlist=["text"]).text
        await conn.execute(_t(
            "CREATE TABLE IF NOT EXISTS escalation_attempts ("
            "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
            "  tenant_id UUID NOT NULL,"
            "  session_id VARCHAR(255) NOT NULL,"
            "  agent_name VARCHAR(255) NOT NULL DEFAULT '',"
            "  connector_type VARCHAR(50) NOT NULL DEFAULT '',"
            "  channel VARCHAR(20) NOT NULL DEFAULT 'web',"
            "  contact_name VARCHAR(255),"
            "  contact_phone VARCHAR(50),"
            "  contact_email VARCHAR(255),"
            "  trigger_message TEXT,"
            "  status VARCHAR(20) NOT NULL DEFAULT 'pending',"
            "  ticket_id VARCHAR(255),"
            "  conversation_url VARCHAR(500),"
            "  error_message TEXT,"
            "  payload_snapshot JSONB,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        ))
        await conn.execute(_t(
            "CREATE INDEX IF NOT EXISTS ix_escalation_tenant_session "
            "ON escalation_attempts (tenant_id, session_id)"
        ))
        await conn.execute(_t(
            "CREATE INDEX IF NOT EXISTS ix_escalation_status "
            "ON escalation_attempts (status)"
        ))
    logger.info("database_initialized")


async def close_db() -> None:
    await engine.dispose()
    logger.info("database_connection_closed")
