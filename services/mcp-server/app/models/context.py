import uuid
from datetime import datetime, timezone
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        Index("ix_knowledge_bases_tenant_id", "tenant_id"),
        Index("ix_knowledge_bases_agent_id", "agent_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )

    # Relationships
    documents: Mapped[list["KnowledgeDocument"]] = relationship(
        "KnowledgeDocument", back_populates="knowledge_base", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<KnowledgeBase name={self.name} tenant={self.tenant_id}>"


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        Index("ix_knowledge_documents_kb_id", "kb_id"),
        Index("ix_knowledge_documents_tenant_id", "tenant_id"),
        Index("ix_knowledge_documents_content_type", "content_type"),
        Index("ix_knowledge_documents_vector_id", "vector_id"),
        Index("ix_knowledge_documents_metadata", "doc_metadata", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # content_type: "text" | "faq" | "policy" | "product" | "procedure"
    content_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="text"
    )

    # pgvector embedding column (768-dim, Gemini text-embedding-004)
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(768), nullable=True
    )

    # Legacy Vector ID (kept for backwards compat, no longer used for lookup)
    vector_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    doc_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )

    # Relationship
    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        "KnowledgeBase", back_populates="documents"
    )

    def __repr__(self) -> str:
        return f"<KnowledgeDocument title={self.title} kb={self.kb_id}>"
