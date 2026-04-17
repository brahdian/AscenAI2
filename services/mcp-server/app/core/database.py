from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event, text
import structlog

from app.core.config import settings

from pgvector.asyncpg import register_vector
from sqlalchemy import event

logger = structlog.get_logger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

@event.listens_for(engine.sync_engine, "connect")
def register_pgvector(dbapi_connection, connection_record):
    dbapi_connection.run_async(register_vector)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """Initialize database - create all tables."""
    async with engine.begin() as conn:
        # Import all models to ensure they are registered with Base
        from app.models.tool import Tool, ToolExecution  # noqa: F401
        from app.models.context import KnowledgeBase, KnowledgeDocument  # noqa: F401
        from app.models.booking import BookingWorkflow, BookingEvent  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)

        if "sqlite" not in settings.DATABASE_URL:
            await conn.execute(text("""
                CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS UUID AS $$
                BEGIN
                    RETURN current_setting('app.current_tenant_id', TRUE)::UUID;
                EXCEPTION
                    WHEN invalid_text_representation OR undefined_object THEN
                        RETURN NULL;
                END;
                $$ LANGUAGE plpgsql STABLE SECURITY DEFINER;
            """))

            for table_name in (
                "mcp_tools",
                "mcp_tool_executions",
                "knowledge_bases",
                "knowledge_documents",
                "booking_workflows",
                "booking_events",
            ):
                await conn.execute(text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"))
                await conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {table_name}"))
                await conn.execute(text(f"""
                    CREATE POLICY tenant_isolation ON {table_name}
                    USING (tenant_id = current_tenant_id())
                """))
    logger.info("Database tables created/verified")


async def close_db() -> None:
    """Close database connections."""
    await engine.dispose()
    logger.info("Database connections closed")


async def get_db(tenant_id: str | None = None) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions."""
    async with SessionLocal() as session:
        try:
            if tenant_id:
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, true)"),
                    {"tid": str(tenant_id)},
                )
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
