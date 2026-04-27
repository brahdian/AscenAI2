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


from shared.dates import utcnow


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
    )  # "starter", "growth", "business", "enterprise"
    plan_limits: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subscription_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    
    # Compliance
    audit_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=365)

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

    PLAN_DISPLAY_NAMES: dict[str, str] = {
        "text_growth": "Starter",
        "voice_growth": "Growth",
        "voice_business": "Business",
        "enterprise": "Enterprise",
        "professional": "Growth",
        "business": "Business",
        "starter": "Starter",
        "growth": "Growth",
    }

    @property
    def plan_display_name(self) -> str:
        """Return a human-friendly plan name, including status if not active."""
        if not self.plan or self.plan == "none":
            return "Not Subscribed"
            
        base_name = self.PLAN_DISPLAY_NAMES.get(self.plan, self.plan.replace("_", " ").title())
        
        if self.subscription_status == "active":
            return base_name
        
        status_label = (self.subscription_status or "inactive").title()
        return f"{base_name} ({status_label})"

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

    # Running count of active agents for this tenant (incremented/decremented via proxy)
    agent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    current_month_sessions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    current_month_messages: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    current_month_chat_units: Mapped[int] = mapped_column(
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


class PendingAgentPurchase(Base):
    __tablename__ = "pending_agent_purchases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<PendingAgentPurchase tenant={self.tenant_id} id={self.id}>"


class TenantCRMWorkspace(Base):
    """
    Mapping between an AscenAI Tenant and their Twenty CRM Workspaces (Companies).
    Allows one tenant to have multiple isolated CRM environments.
    """
    __tablename__ = "tenant_crm_workspaces"
    __table_args__ = (
        Index("ix_crm_workspaces_tenant_id", "tenant_id"),
        Index("ix_crm_workspaces_workspace_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The actual ID of the workspace in Twenty's database
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    subdomain: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Track allowed user slots for this specific company
    user_slots: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationship
    tenant: Mapped["Tenant"] = relationship("Tenant")


class TenantMember(Base):
    """
    Cross-product RBAC membership record.
    One row per person per tenant. Governs access to all AscenAI products.
    CRM-only members (is_crm_only=True) have no AscenAI dashboard account.
    """
    __tablename__ = "tenant_members"
    __table_args__ = (
        Index("ix_tenant_members_tenant_id", "tenant_id"),
        Index("ix_tenant_members_user_id", "user_id"),
        Index("ix_tenant_members_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    # Null until the invite is accepted (for pending invites)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    # Product access toggles
    can_access_agents: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_access_crm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_access_billing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_access_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Role within each product
    agents_role: Mapped[str] = mapped_column(String(50), nullable=False, default="viewer")  # viewer|editor|admin
    crm_role: Mapped[str] = mapped_column(String(50), nullable=False, default="viewer")

    # CRM-only = no AscenAI login, enters CRM via magic link only
    is_crm_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Invite tracking
    invite_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    invite_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending|active|revoked

    # CRM workspace assignment (for CRM-only users)
    crm_workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow, nullable=False
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant")
