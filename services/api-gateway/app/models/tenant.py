import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        Index("ix_tenants_slug", "slug", unique=True),
        Index("ix_tenants_email", "email"),
        Index("ix_tenants_is_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    # Business info
    business_type: Mapped[str] = mapped_column(
        String(100), nullable=False, default="other"
    )  # "pizza_shop", "clinic", "salon", "other"
    business_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    address: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False, default="UTC")

    # Subscription
    plan: Mapped[str] = mapped_column(
        String(50), nullable=False, default="starter"
    )  # "starter", "growth", "enterprise"
    plan_limits: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Arbitrary metadata
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )

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
    users: Mapped[list["User"]] = relationship(  # noqa: F821
        "User", back_populates="tenant", cascade="all, delete-orphan"
    )
    usage: Mapped["TenantUsage"] = relationship(
        "TenantUsage", back_populates="tenant", uselist=False, cascade="all, delete-orphan"
    )
    api_keys: Mapped[list["APIKey"]] = relationship(  # noqa: F821
        "APIKey", back_populates="tenant", cascade="all, delete-orphan"
    )
    webhooks: Mapped[list["Webhook"]] = relationship(  # noqa: F821
        "Webhook", back_populates="tenant", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Tenant slug={self.slug} plan={self.plan}>"


class TenantUsage(Base):
    __tablename__ = "tenant_usage"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_tenant_usage_tenant_id"),
        Index("ix_tenant_usage_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    current_month_sessions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    current_month_messages: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    current_month_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    current_month_voice_minutes: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    total_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    last_reset_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )

    # Relationship
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="usage")

    def __repr__(self) -> str:
        return f"<TenantUsage tenant={self.tenant_id} sessions={self.current_month_sessions}>"
