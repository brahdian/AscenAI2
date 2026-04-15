from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool
from sqlalchemy import text
from typing import AsyncGenerator, Optional
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


async def get_db(
    tenant_id: Optional[str] = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a DB session, optionally scoped to a tenant via Postgres RLS.

    When *tenant_id* is supplied (non-empty string) the session variable
    ``app.current_tenant_id`` is SET LOCAL so that every statement in this
    transaction is filtered by the RLS policies defined in ``init_db``.

    This is the **only** place where the tenant context is injected — never
    rely on application-level WHERE clauses alone for tenant isolation.
    """
    async with AsyncSessionLocal() as session:
        try:
            if tenant_id:
                # Use SET LOCAL so the variable is scoped to this transaction
                # and cannot bleed into a connection-pool reuse.
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


async def get_db_no_rls() -> AsyncGenerator[AsyncSession, None]:
    """Yield an unrestricted session for internal background tasks and migrations.

    **Never** expose this via a public API route — it bypasses RLS entirely.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.error("database_session_error_no_rls", error=str(exc))
            raise
        finally:
            await session.close()


async def init_db() -> None:
    # Import all ORM models so they register with Base.metadata before create_all
    import app.models  # noqa: F401 — side-effect: registers all models
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # ── Migration Centralization ──────────────────────────────────────────
        # Manual ALTER TABLE statements have been moved to Alembic Migration 0014
        # (residing in api-gateway) to ensure a single source of truth for schema.
        # Only service-specific table-level initialization remains here.
        # ──────────────────────────────────────────────────────────────────────

        # AgentDocument migrations (storage_path nullable fix)
        _t = __import__("sqlalchemy", fromlist=["text"]).text

        await conn.execute(_t("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS blocked_keywords JSONB"))
        await conn.execute(_t("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS blocked_topics JSONB"))
        await conn.execute(_t("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS allowed_topics JSONB"))
        await conn.execute(_t("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS profanity_filter BOOLEAN DEFAULT TRUE"))
        await conn.execute(_t("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS pii_redaction BOOLEAN DEFAULT FALSE"))
        await conn.execute(_t("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS pii_pseudonymization BOOLEAN DEFAULT TRUE"))
        await conn.execute(_t("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS max_response_length INTEGER DEFAULT 0"))
        await conn.execute(_t("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS require_disclaimer TEXT"))
        await conn.execute(_t("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS blocked_message TEXT"))
        await conn.execute(_t("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS off_topic_message TEXT"))
        await conn.execute(_t("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS content_filter_level VARCHAR(20) DEFAULT 'medium'"))

        # AgentPlaybook migrations
        await conn.execute(_t("ALTER TABLE agent_playbooks ADD COLUMN IF NOT EXISTS input_schema JSONB"))
        await conn.execute(_t("ALTER TABLE agent_playbooks ADD COLUMN IF NOT EXISTS output_schema JSONB"))
        await conn.execute(_t("ALTER TABLE agent_playbooks ADD COLUMN IF NOT EXISTS tools JSONB"))

        # AgentVariable migrations
        await conn.execute(_t("ALTER TABLE agent_variables ADD COLUMN IF NOT EXISTS playbook_id UUID"))
        await conn.execute(_t("ALTER TABLE agent_variables ADD COLUMN IF NOT EXISTS is_secret BOOLEAN NOT NULL DEFAULT FALSE"))

        # Session auto-close: last_activity_at column
        await conn.execute(_t("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ"))
        await conn.execute(_t("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS turn_count INTEGER DEFAULT 0"))
        await conn.execute(_t("CREATE INDEX IF NOT EXISTS ix_sessions_last_activity ON sessions (last_activity_at)"))

        try:
            await conn.execute(_t("ALTER TABLE agent_documents ALTER COLUMN storage_path DROP NOT NULL"))
        except Exception as e:
            logger.warning("failed_to_drop_not_null_storage_path", error=str(e))

        # Agent expiry and status migrations
        await conn.execute(_t("ALTER TABLE agents ADD COLUMN IF NOT EXISTS status VARCHAR(30) NOT NULL DEFAULT 'DRAFT'"))
        await conn.execute(_t("ALTER TABLE agents ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ"))
        await conn.execute(_t("ALTER TABLE agents ADD COLUMN IF NOT EXISTS grace_period_ends_at TIMESTAMPTZ"))
        await conn.execute(_t("ALTER TABLE agent_documents ADD COLUMN IF NOT EXISTS content TEXT"))
        await conn.execute(_t("ALTER TABLE agent_documents ADD COLUMN IF NOT EXISTS embedding vector(768)"))

        # Register pgvector with asyncpg
        from pgvector.asyncpg import register_vector

        async def _register(conn):
            await register_vector(conn)

        # Get the raw asyncpg connection from the SQLAlchemy connection
        raw_conn = await conn.get_raw_connection()
        dbapi_conn = raw_conn.dbapi_connection
        # dbapi_conn is AsyncAdapt_asyncpg_connection, _connection is the actual asyncpg.Connection
        await _register(dbapi_conn._connection)

        # AgentDocumentChunk table and HNSW index
        await conn.execute(_t(
            "CREATE TABLE IF NOT EXISTS agent_document_chunks ("
            "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
            "  doc_id UUID NOT NULL REFERENCES agent_documents(id) ON DELETE CASCADE,"
            "  tenant_id UUID NOT NULL,"
            "  content TEXT NOT NULL,"
            "  embedding vector(768) NOT NULL,"
            "  chunk_index INTEGER NOT NULL"
            ")"
        ))
        await conn.execute(_t("CREATE INDEX IF NOT EXISTS ix_agent_doc_chunks_doc_id ON agent_document_chunks (doc_id)"))
        await conn.execute(_t("CREATE INDEX IF NOT EXISTS ix_agent_doc_chunks_tenant_id ON agent_document_chunks (tenant_id)"))
        # HNSW index for cosine similarity performance
        await conn.execute(_t(
            "CREATE INDEX IF NOT EXISTS ix_agent_doc_chunks_embedding_hnsw "
            "ON agent_document_chunks USING hnsw (embedding vector_cosine_ops)"
        ))

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
        
        # Message metadata migrations
        await conn.execute(_t("ALTER TABLE messages ADD COLUMN IF NOT EXISTS playbook_name VARCHAR(255)"))
        await conn.execute(_t("ALTER TABLE messages ADD COLUMN IF NOT EXISTS sources JSONB"))

        # Workflow engine — create execution_status and step_status ENUM types
        await conn.execute(_t("""
            DO $$ BEGIN
                CREATE TYPE execution_status AS ENUM (
                    'RUNNING','AWAITING_INPUT','AWAITING_EVENT',
                    'COMPLETED','FAILED','EXPIRED'
                );
            EXCEPTION WHEN duplicate_object THEN null;
            END $$
        """))
        await conn.execute(_t("""
            DO $$ BEGIN
                CREATE TYPE step_status AS ENUM (
                    'RUNNING','COMPLETED','FAILED','SKIPPED'
                );
            EXCEPTION WHEN duplicate_object THEN null;
            END $$
        """))

        # Agent mode — "conversational" | "automation" | "hybrid"
        await conn.execute(_t(
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS agent_mode VARCHAR(20) NOT NULL DEFAULT 'conversational'"
        ))
        await conn.execute(_t(
            "CREATE INDEX IF NOT EXISTS ix_agents_agent_mode ON agents (agent_mode)"
        ))
        
        # Workflow execution customer_phone index for fast SMS lookup
        await conn.execute(_t(
            "CREATE INDEX IF NOT EXISTS ix_workflow_executions_customer_phone ON workflow_executions (customer_phone)"
        ))

        # Agent lifecycle state machine — add status column if not present
        await conn.execute(_t(
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS status VARCHAR(30) NOT NULL DEFAULT 'active'"
        ))
        # Backfill: archived agents (is_active=FALSE) must have status='archived'
        if not _is_sqlite:
            await conn.execute(_t(
                "UPDATE agents SET status = 'archived' WHERE is_active = FALSE AND status = 'active'"
            ))

        # ── PostgreSQL Row-Level Security (RLS) ─────────────────────────────
        # Skip RLS for SQLite (dev/test environment)
        if not _is_sqlite:
            _rls_tables = [
                "agents", "sessions", "messages", "agent_playbooks",
                "agent_guardrails", "agent_documents", "agent_analytics",
                "message_feedback", "conversation_traces", "playbook_executions",
                # Extended coverage
                "agent_tools", "agent_variables", "agent_lifecycle_audit",
            ]

            # Create helper function to read current_tenant_id from session variables
            await conn.execute(_t("""
                CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS UUID AS $$
                BEGIN
                    RETURN current_setting('app.current_tenant_id', TRUE)::UUID;
                EXCEPTION
                    WHEN invalid_text_representation OR undefined_object THEN
                        RETURN NULL;
                END;
                $$ LANGUAGE plpgsql STABLE SECURITY DEFINER;
            """))

            for _tbl in _rls_tables:
                # Enable RLS
                await conn.execute(_t(f"ALTER TABLE {_tbl} ENABLE ROW LEVEL SECURITY"))
                # Force all rows to be filtered — NO IS NULL bypass.
                # The table owner / superuser role bypasses RLS implicitly via
                # BYPASSRLS privilege; application workers must always set the
                # tenant context using get_db(tenant_id=...).
                await conn.execute(_t(
                    f"DROP POLICY IF EXISTS tenant_isolation ON {_tbl}"
                ))
                await conn.execute(_t(f"""
                    CREATE POLICY tenant_isolation ON {_tbl}
                    USING (tenant_id = current_tenant_id())
                """))

    logger.info("database_initialized")


async def close_db() -> None:
    await engine.dispose()
    logger.info("database_connection_closed")
