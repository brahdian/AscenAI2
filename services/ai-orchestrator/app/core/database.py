from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool
from typing import AsyncGenerator
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    poolclass=NullPool if "sqlite" in settings.DATABASE_URL else None,
    pool_pre_ping=True,
    pool_size=10 if "sqlite" not in settings.DATABASE_URL else None,
    max_overflow=20 if "sqlite" not in settings.DATABASE_URL else None,
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
    logger.info("database_initialized")


async def close_db() -> None:
    await engine.dispose()
    logger.info("database_connection_closed")
