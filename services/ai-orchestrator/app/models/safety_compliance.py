"""
Safety and Compliance Framework for Agent Templates

This module adds production-ready safety, compliance, and quality assurance features to the agent template system.
"""

import uuid
from datetime import datetime, date
from typing import Optional
from sqlalchemy import (
    String, Boolean, Text, Integer, ForeignKey, func, Index, DateTime, UniqueConstraint, Float, Date
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TemplateCompliance(Base):
    """
    Industry-specific compliance requirements and safety guidelines for templates.
    """
    __tablename__ = "template_compliance"
    __table_args__ = (
        UniqueConstraint("template_id", "industry"),
        Index("ix_template_compliance_template", "template_id"),
        Index("ix_template_compliance_industry", "industry"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_templates.id"), nullable=False
    )
    industry: Mapped[str] = mapped_column(String(50), nullable=False)  # healthcare, finance, legal, etc.
    compliance_framework: Mapped[str] = mapped_column(String(50), nullable=False)  # HIPAA, PCI-DSS, GDPR, etc.
    
    # Regulatory requirements
    data_retention_policy: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    emergency_protocols: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    content_moderation_rules: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    
    # Safety guidelines
    pii_handling_rules: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    bias_mitigation_rules: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    ethical_guidelines: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    
    # Risk assessment
    risk_level: Mapped[str] = mapped_column(String(20), default="low")  # low, medium, high, critical
    audit_requirements: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    template: Mapped["AgentTemplate"] = relationship("AgentTemplate", back_populates="compliance")


class TemplateGuardrail(Base):
    """
    Advanced guardrail rules for template safety and content moderation.
    """
    __tablename__ = "template_guardrails"
    __table_args__ = (
        Index("ix_template_guardrails_template", "template_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_templates.id"), nullable=False
    )
    
    # Content filtering
    blocked_keywords: Mapped[list[str]] = mapped_column(JSONB, default=list)
    blocked_topics: Mapped[list[str]] = mapped_column(JSONB, default=list)
    allowed_topics: Mapped[list[str]] = mapped_column(JSONB, default=list)
    profanity_filter: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # PII handling
    pii_redaction: Mapped[bool] = mapped_column(Boolean, default=False)
    pii_pseudonymization: Mapped[bool] = mapped_column(Boolean, default=True)
    max_response_length: Mapped[int] = mapped_column(Integer, default=0)  # 0 = unlimited
    
    # Response control
    require_disclaimer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    blocked_message: Mapped[str] = mapped_column(
        Text, nullable=False, default="I'm sorry, I can't help with that."
    )
    off_topic_message: Mapped[str] = mapped_column(
        Text, nullable=False, default="I'm only able to help with topics related to our service."
    )
    
    # Safety levels
    content_filter_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default="medium"
    )  # none | low | medium | strict
    safety_threshold: Mapped[float] = mapped_column(Float, default=0.8)  # 0-1 confidence threshold
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    template: Mapped["AgentTemplate"] = relationship("AgentTemplate", back_populates="guardrails")


class TemplateEmergencyProtocol(Base):
    """
    Emergency response protocols for high-risk scenarios.
    """
    __tablename__ = "template_emergency_protocols"
    __table_args__ = (
        Index("ix_template_emergency_template", "template_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_templates.id"), nullable=False
    )
    
    # Medical emergencies
    medical_emergency_triggers: Mapped[list[str]] = mapped_column(JSONB, default=list)
    medical_response_script: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    emergency_contact_info: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    
    # Mental health crises
    mental_health_triggers: Mapped[list[str]] = mapped_column(JSONB, default=list)
    mental_health_response_script: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    crisis_hotline_info: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    
    # Safety threats
    safety_threat_triggers: Mapped[list[str]] = mapped_column(JSONB, default=list)
    safety_response_script: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    law_enforcement_contact: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    
    # Abuse detection
    abuse_detection_triggers: Mapped[list[str]] = mapped_column(JSONB, default=list)
    abuse_response_script: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    support_resources: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    template: Mapped["AgentTemplate"] = relationship("AgentTemplate", back_populates="emergency_protocols")


class TemplateQualityEvaluation(Base):
    """
    Automated quality evaluation framework for template assessment.
    """
    __tablename__ = "template_evaluations"
    __table_args__ = (
        Index("ix_template_evaluation_template", "template_id"),
        Index("ix_template_evaluation_type", "evaluation_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_templates.id"), nullable=False
    )
    evaluation_type: Mapped[str] = mapped_column(String(50), nullable=False)  # safety, accuracy, bias, performance
    
    # Test scenarios
    test_cases: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    evaluation_criteria: Mapped[dict] = mapped_column(JSONB, default=dict)
    
    # Results
    results: Mapped[dict] = mapped_column(JSONB, default=dict)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0-1 rating
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0-1 confidence
    
    # Quality metrics
    safety_score: Mapped[float] = mapped_column(Float, default=0.0)
    accuracy_score: Mapped[float] = mapped_column(Float, default=0.0)
    bias_score: Mapped[float] = mapped_column(Float, default=0.0)
    performance_score: Mapped[float] = mapped_column(Float, default=0.0)
    
    recommendations: Mapped[Optional[list[str]]] = mapped_column(JSONB, nullable=True)
    issues_found: Mapped[Optional[list[dict]]] = mapped_column(JSONB, nullable=True)
    
    is_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_automated: Mapped[bool] = mapped_column(Boolean, default=True)
    
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    next_evaluation_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    template: Mapped["AgentTemplate"] = relationship("AgentTemplate", back_populates="evaluations")


class TemplateAnalytics(Base):
    """
    Usage analytics and performance metrics for templates.
    """
    __tablename__ = "template_analytics"
    __table_args__ = (
        Index("ix_template_analytics_template", "template_id"),
        Index("ix_template_analytics_date", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_templates.id"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    
    # Usage metrics
    total_instances: Mapped[int] = mapped_column(Integer, default=0)
    active_instances: Mapped[int] = mapped_column(Integer, default=0)
    total_conversations: Mapped[int] = mapped_column(Integer, default=0)
    successful_conversations: Mapped[int] = mapped_column(Integer, default=0)
    
    # Performance metrics
    avg_response_time_ms: Mapped[float] = mapped_column(Float, default=0.0)
    error_rate: Mapped[float] = mapped_column(Float, default=0.0)  # 0-1
    escalation_rate: Mapped[float] = mapped_column(Float, default=0.0)  # 0-1
    
    # Quality metrics
    avg_quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    user_satisfaction_score: Mapped[float] = mapped_column(Float, default=0.0)
    completion_rate: Mapped[float] = mapped_column(Float, default=0.0)  # 0-1
    
    # Cost metrics
    total_tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    template: Mapped["AgentTemplate"] = relationship("AgentTemplate", back_populates="analytics")


class TemplateMarketplace(Base):
    """
    Marketplace metadata and visibility settings for templates.
    """
    __tablename__ = "template_marketplace"
    __table_args__ = (
        UniqueConstraint("template_id", "organization_id"),
        Index("ix_template_marketplace_template", "template_id"),
        Index("ix_template_marketplace_org", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_templates.id"), nullable=False
    )
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    
    # Visibility and access
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    visibility: Mapped[str] = mapped_column(String(50), default="private")  # public, private, organization
    
    # Marketplace metadata
    categories: Mapped[list[str]] = mapped_column(JSONB, default=list)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSONB, default=list)
    
    # Quality indicators
    average_rating: Mapped[float] = mapped_column(Float, default=0.0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Usage statistics
    total_installs: Mapped[int] = mapped_column(Integer, default=0)
    monthly_active_users: Mapped[int] = mapped_column(Integer, default=0)
    
    # Template status
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_deprecated: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Pricing and licensing
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    price_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    license_type: Mapped[str] = mapped_column(String(50), default="standard")  # standard, enterprise, open-source
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    template: Mapped["AgentTemplate"] = relationship("AgentTemplate", back_populates="marketplace")


# Extend the AgentTemplate model with new relationships
AgentTemplate.compliance = relationship("TemplateCompliance", back_populates="template", uselist=False, cascade="all, delete-orphan")
AgentTemplate.guardrails = relationship("TemplateGuardrail", back_populates="template", uselist=False, cascade="all, delete-orphan")
AgentTemplate.emergency_protocols = relationship("TemplateEmergencyProtocol", back_populates="template", uselist=False, cascade="all, delete-orphan")
AgentTemplate.evaluations = relationship("TemplateQualityEvaluation", back_populates="template", cascade="all, delete-orphan")
AgentTemplate.analytics = relationship("TemplateAnalytics", back_populates="template", cascade="all, delete-orphan")
AgentTemplate.marketplace = relationship("TemplateMarketplace", back_populates="template", uselist=False, cascade="all, delete-orphan")