"""
Database session factory for the voice-pipeline.

Used exclusively by the in-process VoiceOrchestrator bridge.
The voice-pipeline does not own any migrations — those are managed
by the ai-orchestrator. This module only provides a read/write
AsyncSession so the in-process Orchestrator can load Agent/Session
rows and persist messages.
"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# Reuse the same DATABASE_URL the ai-orchestrator uses
_engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=20,
    max_overflow=40,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_timeout=30,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    """Shared declarative base — imported by ai-orchestrator models via orchestrator_src."""
    pass
