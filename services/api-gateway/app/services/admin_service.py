"""
Admin Service — platform administration, tenant management, and RBAC metadata.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import stripe
import structlog
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import PlatformSetting
from app.models.tenant import Tenant, TenantUsage
from app.models.user import User
from app.services.audit_service import audit_log
from app.services.auth_service import auth_service

logger = structlog.get_logger(__name__)

CANONICAL_TENANT_ROLES = ("owner", "admin", "developer", "viewer")

DEFAULT_ROLES = {
    "super_admin": {
        "level": 100,
        "permissions": [
            "tenants:read", "tenants:write", "tenants:delete",
            "users:read", "users:write", "users:delete",
            "agents:read", "agents:write", "agents:delete",
            "system_prompts:read", "system_prompts:write",
            "playbooks:read", "playbooks:write",
            "tools:read", "tools:write",
            "traces:read", "metrics:read", "logs:read",
            "billing:read", "billing:write",
            "compliance:read", "compliance:write",
            "settings:read", "settings:write",
        ],
    },
    "owner": {
        "level": 80,
        "permissions": [
            "tenants:read", "tenants:write",
            "users:read", "users:write",
            "agents:read", "agents:write", "agents:delete",
            "system_prompts:read", "system_prompts:write",
            "playbooks:read", "playbooks:write",
            "tools:read", "tools:write",
            "traces:read", "metrics:read",
            "billing:read",
        ],
    },
    "admin": {
        "level": 60,
        "permissions": [
            "agents:read", "agents:write",
            "playbooks:read", "playbooks:write",
            "tools:read", "tools:write",
            "traces:read", "metrics:read",
        ],
    },
    "developer": {
        "level": 40,
        "permissions": [
            "agents:read",
            "playbooks:read",
            "tools:read",
            "traces:read", "metrics:read",
        ],
    },
    "viewer": {
        "level": 20,
        "permissions": [
            "agents:read",
            "metrics:read",
        ],
    },
}

_ROLES_CACHE: Dict[str, Any] = {}
_LAST_ROLES_FETCH: Optional[datetime] = None
_CACHE_TTL_SECONDS = 300


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _tenant_lifecycle(tenant: Tenant) -> str:
    if not tenant.is_active:
        return "suspended"
    status = (tenant.subscription_status or "").lower()
    if status in {"canceled", "cancelled"}:
        return "cancelled"
    if status in {"past_due", "unpaid"}:
        return "past_due"
    if tenant.trial_ends_at and tenant.trial_ends_at > _utcnow():
        return "trial"
    return "active"


def _serialize_tenant(tenant: Tenant, *, agent_count: int = 0, user_count: int = 0) -> dict[str, Any]:
    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "slug": tenant.slug,
        "business_name": tenant.business_name,
        "business_type": tenant.business_type,
        "email": tenant.email,
        "phone": tenant.phone,
        "plan": tenant.plan,
        "plan_display_name": tenant.plan_display_name,
        "subscription_status": tenant.subscription_status,
        "subscription_id": tenant.subscription_id,
        "stripe_customer_id": tenant.stripe_customer_id,
        "is_active": tenant.is_active,
        "status": _tenant_lifecycle(tenant),
        "trial_ends_at": tenant.trial_ends_at.isoformat() if tenant.trial_ends_at else None,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
        "updated_at": tenant.updated_at.isoformat() if tenant.updated_at else None,
        "agent_count": agent_count,
        "user_count": user_count,
    }


def _serialize_user(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "tenant_id": str(user.tenant_id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
        "is_email_verified": user.is_email_verified,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


async def get_all_roles(db: AsyncSession) -> Dict[str, Any]:
    global _ROLES_CACHE, _LAST_ROLES_FETCH

    now = _utcnow()
    if _ROLES_CACHE and _LAST_ROLES_FETCH:
        age = (now - _LAST_ROLES_FETCH).total_seconds()
        if age < _CACHE_TTL_SECONDS:
            return _ROLES_CACHE

    try:
        result = await db.execute(
            select(PlatformSetting).where(PlatformSetting.key == "rbac_roles")
        )
        setting = result.scalar_one_or_none()
        if setting and setting.value:
            merged_roles = dict(DEFAULT_ROLES)
            for role_name, role_value in setting.value.items():
                merged_roles[role_name] = role_value
            _ROLES_CACHE = merged_roles
            _LAST_ROLES_FETCH = now
            return _ROLES_CACHE
    except Exception as exc:
        logger.warning("failed_to_fetch_roles_from_db", error=str(exc))

    return DEFAULT_ROLES


class AdminService:
    def __init__(self, db: AsyncSession, redis_client):
        self.db = db
        self.redis = redis_client

    async def list_tenants(
        self,
        page: int = 1,
        per_page: int = 50,
        status: str = "",
    ) -> Dict[str, Any]:
        offset = (page - 1) * per_page

        tenant_query = select(Tenant).order_by(Tenant.created_at.desc())
        if status == "active":
            tenant_query = tenant_query.where(
                Tenant.is_active.is_(True),
                ~Tenant.subscription_status.in_(["canceled", "cancelled", "past_due", "unpaid"]),
                or_(Tenant.trial_ends_at.is_(None), Tenant.trial_ends_at <= func.now()),
            )
        elif status == "suspended":
            tenant_query = tenant_query.where(Tenant.is_active.is_(False))
        elif status in ("cancelled", "canceled"):
            tenant_query = tenant_query.where(
                Tenant.is_active.is_(True),
                Tenant.subscription_status.in_(["canceled", "cancelled"]),
            )
        elif status == "past_due":
            tenant_query = tenant_query.where(
                Tenant.is_active.is_(True),
                Tenant.subscription_status.in_(["past_due", "unpaid"]),
            )
        elif status == "trial":
            tenant_query = tenant_query.where(
                Tenant.is_active.is_(True),
                Tenant.trial_ends_at.isnot(None),
                Tenant.trial_ends_at > func.now(),
            )

        total_result = await self.db.execute(
            select(func.count()).select_from(tenant_query.subquery())
        )
        total = total_result.scalar_one()

        result = await self.db.execute(tenant_query.offset(offset).limit(per_page))
        tenants = list(result.scalars().all())
        tenant_ids = [tenant.id for tenant in tenants]

        agent_counts: dict[uuid.UUID, int] = {}
        user_counts: dict[uuid.UUID, int] = {}
        if tenant_ids:
            agent_count_rows = await self.db.execute(
                text("""
                    SELECT tenant_id, COUNT(*) AS count
                    FROM agents
                    WHERE tenant_id = ANY(:tenant_ids)
                    GROUP BY tenant_id
                """),
                {"tenant_ids": tenant_ids},
            )
            agent_counts = {
                row.tenant_id: int(row.count or 0)
                for row in agent_count_rows
            }

            user_count_rows = await self.db.execute(
                select(User.tenant_id, func.count())
                .where(User.tenant_id.in_(tenant_ids))
                .group_by(User.tenant_id)
            )
            user_counts = {
                tenant_id: int(count or 0)
                for tenant_id, count in user_count_rows.all()
            }

        serialized = [
            _serialize_tenant(
                tenant,
                agent_count=agent_counts.get(tenant.id, 0),
                user_count=user_counts.get(tenant.id, 0),
            )
            for tenant in tenants
        ]

        return {
            "tenants": serialized,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page if total else 0,
            },
        }

    async def get_tenant_details(self, tenant_id: str) -> Dict[str, Any]:
        tenant_uuid = uuid.UUID(tenant_id)
        result = await self.db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
        tenant = result.scalar_one_or_none()
        if not tenant:
            return {"error": "Tenant not found"}

        usage_result = await self.db.execute(
            select(TenantUsage).where(TenantUsage.tenant_id == tenant_uuid)
        )
        usage = usage_result.scalar_one_or_none()

        user_count_result = await self.db.execute(
            select(func.count()).select_from(User).where(User.tenant_id == tenant_uuid)
        )
        user_count = int(user_count_result.scalar() or 0)

        agent_count_result = await self.db.execute(
            text("SELECT COUNT(*) FROM agents WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_uuid},
        )
        agent_count = int(agent_count_result.scalar() or 0)

        data = _serialize_tenant(tenant, agent_count=agent_count, user_count=user_count)
        data["usage"] = {
            "agent_count": usage.agent_count if usage else 0,
            "current_month_sessions": usage.current_month_sessions if usage else 0,
            "current_month_messages": usage.current_month_messages if usage else 0,
            "current_month_chat_units": usage.current_month_chat_units if usage else 0,
            "current_month_tokens": usage.current_month_tokens if usage else 0,
            "current_month_voice_minutes": usage.current_month_voice_minutes if usage else 0.0,
            "total_cost_usd": usage.total_cost_usd if usage else 0.0,
        }
        return data

    async def suspend_tenant(self, tenant_id: str, reason: str, admin_user_id: str) -> Dict[str, Any]:
        tenant_uuid = uuid.UUID(tenant_id)
        result = await self.db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
        tenant = result.scalar_one_or_none()
        if not tenant:
            return {"error": "Tenant not found"}

        tenant.is_active = False
        await audit_log(
            self.db,
            "tenant.suspended",
            tenant_id=str(tenant.id),
            actor_user_id=admin_user_id,
            actor_role="super_admin",
            category="admin",
            resource_type="tenant",
            resource_id=str(tenant.id),
            details={"reason": reason},
        )
        await self.db.commit()
        logger.info("tenant_suspended", tenant_id=tenant_id, reason=reason)
        return {"status": "suspended", "tenant_id": tenant_id}

    async def reactivate_tenant(self, tenant_id: str, admin_user_id: str) -> Dict[str, Any]:
        tenant_uuid = uuid.UUID(tenant_id)
        result = await self.db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
        tenant = result.scalar_one_or_none()
        if not tenant:
            return {"error": "Tenant not found"}

        tenant.is_active = True
        await audit_log(
            self.db,
            "tenant.reactivated",
            tenant_id=str(tenant.id),
            actor_user_id=admin_user_id,
            actor_role="super_admin",
            category="admin",
            resource_type="tenant",
            resource_id=str(tenant.id),
        )
        await self.db.commit()
        logger.info("tenant_reactivated", tenant_id=tenant_id)
        return {"status": "active", "tenant_id": tenant_id}

    async def delete_tenant(
        self,
        tenant_id: str,
        admin_user_id: str,
        hard_delete: bool = False,
    ) -> Dict[str, Any]:
        tenant_uuid = uuid.UUID(tenant_id)
        result = await self.db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
        tenant = result.scalar_one_or_none()
        if not tenant:
            return {"error": "Tenant not found"}

        # 1. Cancel financial commitment to prevent zombie billing
        await self._cancel_stripe_subscriptions(tenant)

        if hard_delete:
            # 2. Wipe database and volatile data silos (Redis)
            await self._wipe_tenant_data(tenant_uuid)
            await self.db.delete(tenant)
        else:
            tenant.is_active = False
            tenant.subscription_status = "cancelled"

        await audit_log(
            self.db,
            "tenant.deleted",
            tenant_id=str(tenant.id),
            actor_user_id=admin_user_id,
            actor_role="super_admin",
            category="admin",
            resource_type="tenant",
            resource_id=str(tenant.id),
            details={"hard_delete": hard_delete},
        )
        await self.db.commit()
        logger.info("tenant_deleted", tenant_id=tenant_id, hard_delete=hard_delete)
        return {"status": "deleted", "tenant_id": tenant_id, "hard": hard_delete}

    async def _cancel_stripe_subscriptions(self, tenant: Tenant) -> None:
        """Cancel all active Stripe subscriptions for the tenant to prevent billing leaks."""
        if not tenant.stripe_customer_id:
            return
            
        try:
            from app.core.config import settings
            stripe.api_key = settings.STRIPE_SECRET_KEY
            
            # Use asyncio.to_thread for blocking Stripe calls
            subs = await asyncio.to_thread(
                stripe.Subscription.list,
                customer=tenant.stripe_customer_id,
                status="active"
            )
            
            for sub in subs.data:
                await asyncio.to_thread(stripe.Subscription.delete, sub.id)
                logger.info("stripe_subscription_cancelled", tenant_id=str(tenant.id), sub_id=sub.id)
        except Exception as e:
            logger.error("stripe_cancellation_failed", tenant_id=str(tenant.id), error=str(e))

    async def _wipe_tenant_data(self, tenant_id: uuid.UUID) -> None:
        """
        Hard-purge all data associated with a tenant across all platform tables.
        Ensures GDPR/HIPAA compliance by scrubbing sensitive orphaned data.
        """
        # 3. Cascading database purge across all platform silos
        # Order: Leaf-tables and dependent resources first to avoid FK violations
        tables = [
            "messages", "sessions", "conversation_traces",
            "agent_documents", "agent_document_chunks", "agent_analytics", "message_feedback",
            "agent_variables", "agent_custom_guardrails", "agent_guardrails",
            "agent_playbooks", "playbook_executions", "playbook_state",
            "escalation_attempts", "guardrail_change_requests", "guardrail_events",
            "agent_state_transitions", "agent_lifecycle_audit",
            
            # Security Silos
            "api_keys", "webhooks", "user_invites",
            
            # Templates and Instances
            "agent_template_instances", "template_versions", "template_variables", 
            "template_playbooks", "template_tools", "agent_templates",
            
            # Workflows
            "workflow_step_executions", "workflow_events", "workflow_executions", "workflows",
            
            # Evaluations
            "eval_scores", "eval_runs", "eval_cases",
            
            # Safety, Compliance & Marketplace
            "template_compliance", "template_guardrails", "template_emergency_protocols",
            "template_evaluations", "template_analytics", "template_marketplace",
            
            # Billing and Agents
            "pending_agent_purchases", "agents"
        ]
        
        for table in tables:
            try:
                await self.db.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tid"),
                    {"tid": tenant_id}
                )
            except Exception as e:
                # Some tables might not exist in this schema or have different FKs
                logger.warning("wipe_table_failed", table=table, error=str(e))

        # --- Redis Scrubbing (Volatile PII & Cache) ---
        if not self.redis:
            return

        try:
            # A. Purge Session-specific volatile state (PII context, playbook engine)
            sessions_query = text("SELECT session_id FROM sessions WHERE tenant_id = :tid")
            sessions_res = await self.db.execute(sessions_query, {"tid": tenant_id})
            session_ids = [row[0] for row in sessions_res.fetchall()]
            
            for sid in session_ids:
                keys = [f"pii_ctx:{sid}", f"playbook_state:{sid}", f"tool_lock:{tenant_id}:{sid}"]
                await self.redis.delete(*keys)

            # B. Purge Agent-specific caches (Semantic RAG cache)
            agents_query = text("SELECT id FROM agents WHERE tenant_id = :tid")
            agents_res = await self.db.execute(agents_query, {"tid": tenant_id})
            agent_ids = [str(row[0]) for row in agents_res.fetchall()]
            
            for aid in agent_ids:
                await self.redis.delete(f"semantic_cache:{tenant_id}:{aid}")

            # C. Purge Global Tenant Volatile State
            await self.redis.delete(f"tenant_compliance:{tenant_id}")
            
            # D. Purge Billing and Throttling (patterns)
            async for key in self.redis.scan_iter(f"billing:*:{tenant_id}:*"):
                await self.redis.delete(key)
            async for key in self.redis.scan_iter(f"rate_limit:*:{tenant_id}:*"):
                await self.redis.delete(key)
                
            logger.info("redis_scrubbing_complete", tenant_id=str(tenant_id), sessions=len(session_ids))
        except Exception as e:
            logger.warning("redis_scrubbing_failed", tenant_id=str(tenant_id), error=str(e))

    async def list_users(
        self,
        tenant_id: str = "",
        page: int = 1,
        per_page: int = 50,
        enforced_tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Security: Override if scoped to a specific tenant
        if enforced_tenant_id:
            tenant_id = str(enforced_tenant_id)

        offset = (page - 1) * per_page
        query = select(User).order_by(User.created_at.desc())
        if tenant_id:
            query = query.where(User.tenant_id == uuid.UUID(tenant_id))

        total_result = await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = total_result.scalar_one()

        result = await self.db.execute(query.offset(offset).limit(per_page))
        users = result.scalars().all()

        return {
            "users": [_serialize_user(user) for user in users],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page if total else 0,
            },
        }

    async def update_user_role(
        self,
        user_id: str,
        new_role: str,
        admin_user_id: str,
        enforced_tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_role = new_role.strip().lower()
        if normalized_role not in CANONICAL_TENANT_ROLES:
            return {"error": f"Invalid role: {new_role}"}

        user_uuid = uuid.UUID(user_id)
        result = await self.db.execute(select(User).where(User.id == user_uuid))
        user = result.scalar_one_or_none()
        if not user:
            return {"error": "User not found"}
            
        # Security: Verify ownership if scoped
        if enforced_tenant_id and str(user.tenant_id) != str(enforced_tenant_id):
            return {"error": "Unauthorized to modify user in another tenant"}

        user.role = normalized_role
        await audit_log(
            self.db,
            "user.role_changed",
            tenant_id=str(user.tenant_id),
            actor_user_id=admin_user_id,
            actor_role="super_admin",
            category="user",
            resource_type="user",
            resource_id=str(user.id),
            details={"new_role": normalized_role},
        )
        await self.db.commit()
        logger.info("user_role_updated", user_id=user_id, new_role=normalized_role)
        return {
            "status": "updated",
            "user_id": user_id,
            "role": normalized_role,
            "tenant_id": str(user.tenant_id),
        }

    async def get_system_prompts(self, agent_id: str = "", tenant_id: Optional[str] = None) -> Dict[str, Any]:
        if agent_id:
            query = text("SELECT system_prompt, system_prompt_version, tenant_id FROM agents WHERE id = :id")
            result = await self.db.execute(query, {"id": agent_id})
            row = result.fetchone()
            if row:
                # Security Check: Ensure tenant_id matches if provided
                if tenant_id and str(row._mapping.get("tenant_id")) != str(tenant_id):
                     return {"error": "Unauthorized access to agent prompt"}

                return {
                    "agent_id": agent_id,
                    "system_prompt": row._mapping.get("system_prompt", ""),
                    "version": row._mapping.get("system_prompt_version", 1),
                }
            return {"error": "Agent not found"}

        result = await self.db.execute(
            select(PlatformSetting).where(PlatformSetting.key.in_(["voice_agent_system_prompt", "system_defaults"]))
        )
        settings_rows = result.scalars().all()
        return {
            "settings": [
                {
                    "key": row.key,
                    "value": row.value,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                }
                for row in settings_rows
            ]
        }

    async def update_system_prompt(
        self,
        agent_id: str,
        system_prompt: str,
        admin_user_id: str,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Security Check: Verify agent ownership if not super_admin (implied by tenant_id presence)
        if tenant_id:
            agent_check = await self.db.execute(
                text("SELECT tenant_id FROM agents WHERE id = :id"),
                {"id": agent_id}
            )
            row = agent_check.fetchone()
            if not row or str(row._mapping.get("tenant_id")) != str(tenant_id):
                return {"error": "Unauthorized to update this agent prompt"}

        await self.db.execute(
            text("""
                UPDATE agents
                SET system_prompt = :prompt,
                    system_prompt_version = COALESCE(system_prompt_version, 0) + 1,
                    updated_at = NOW()
                WHERE id = :id
            """),
            {"prompt": system_prompt, "id": agent_id},
        )
        await audit_log(
            self.db,
            "agent.system_prompt_updated",
            actor_user_id=admin_user_id,
            actor_role="super_admin",
            category="admin",
            resource_type="agent",
            resource_id=agent_id,
            details={"prompt_length": len(system_prompt)},
        )
        await self.db.commit()
        logger.info("system_prompt_updated", agent_id=agent_id)
        return {"status": "updated", "agent_id": agent_id}

    async def get_traces(
        self,
        session_id: str = "",
        tenant_id: str = "",
        limit: int = 50,
        enforced_tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Security: Override tenant_id if enforced (for non-super-admins)
        if enforced_tenant_id:
            tenant_id = str(enforced_tenant_id)

        params: Dict[str, Any] = {"limit": limit}
        # Use SQLAlchemy text() with named parameters for safety and clarity
        stmt = "SELECT * FROM conversation_traces WHERE 1=1"
        if session_id:
            stmt += " AND session_id = :session_id"
            params["session_id"] = session_id
        if tenant_id:
            stmt += " AND tenant_id = :tenant_id"
            params["tenant_id"] = tenant_id
        stmt += " ORDER BY created_at DESC LIMIT :limit"
        
        result = await self.db.execute(text(stmt), params)
        traces = [dict(row._mapping) for row in result.fetchall()]
        return {"traces": traces, "count": len(traces)}

    async def get_platform_metrics(self) -> Dict[str, Any]:
        active_tenants_result = await self.db.execute(
            select(func.count()).select_from(Tenant).where(Tenant.is_active.is_(True))
        )
        active_tenants = int(active_tenants_result.scalar() or 0)

        total_agents_result = await self.db.execute(text("SELECT COUNT(*) FROM agents"))
        total_agents = int(total_agents_result.scalar() or 0)

        sessions_today_result = await self.db.execute(
            text("SELECT COUNT(*) FROM sessions WHERE created_at > NOW() - INTERVAL '24 hours'")
        )
        sessions_today = int(sessions_today_result.scalar() or 0)

        messages_today_result = await self.db.execute(
            text("SELECT COUNT(*) FROM messages WHERE created_at > NOW() - INTERVAL '24 hours'")
        )
        messages_today = int(messages_today_result.scalar() or 0)

        # Calculate average latency from traces (last 24h)
        latency_result = await self.db.execute(
            text("""
                SELECT 
                    AVG((latency_breakdown->>'llm_ms')::float + (latency_breakdown->>'retrieval_ms')::float) as avg_latency,
                    COUNT(*) FILTER (WHERE guardrail_input_check IS NOT NULL) as blocked_count,
                    COUNT(*) as total_count
                FROM conversation_traces 
                WHERE created_at > NOW() - INTERVAL '24 hours'
            """)
        )
        latency_row = latency_result.fetchone()
        avg_latency = float(latency_row.avg_latency or 0)
        blocked_count = int(latency_row.blocked_count or 0)
        total_traces = int(latency_row.total_count or 0)
        error_rate = (blocked_count / total_traces * 100) if total_traces > 0 else 0.0

        # Calculate Customer Satisfaction (CSAT) from feedback (last 30 days)
        csat_result = await self.db.execute(
            text("""
                SELECT AVG(rating) as avg_csat, COUNT(*) as feedback_count
                FROM message_feedback
                WHERE created_at > NOW() - INTERVAL '30 days'
            """)
        )
        csat_row = csat_result.fetchone()
        avg_csat = float(csat_row.avg_csat or 0)
        feedback_count = int(csat_row.feedback_count or 0)

        return {
            "active_tenants": active_tenants,
            "total_agents": total_agents,
            "sessions_today": sessions_today,
            "messages_today": messages_today,
            "avg_latency_ms": round(avg_latency, 2),
            "error_rate_percent": round(error_rate, 2),
            "avg_satisfaction": round(avg_csat, 2),
            "feedback_volume_30d": feedback_count,
            "timestamp": _utcnow().isoformat(),
        }

    async def get_platform_settings(self) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(PlatformSetting).order_by(PlatformSetting.key.asc())
        )
        settings = []
        for row in result.scalars().all():
            value = row.value
            # COMPLIANCE: Mask sensitive values to prevent accidental exposure to Admin UI
            if row.is_sensitive and value:
                if isinstance(value, str):
                    value = value[:4] + "*" * (len(value) - 4) if len(value) > 8 else "********"
                else:
                    value = "********"
            
            settings.append({
                "key": row.key,
                "value": value,
                "description": row.description,
                "is_sensitive": row.is_sensitive,
                "is_public": row.is_public,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            })
        return settings

    async def update_platform_setting(
        self,
        key: str,
        value: Any,
        admin_user_id: str,
    ) -> Dict[str, Any]:
        result = await self.db.execute(
            select(PlatformSetting).where(PlatformSetting.key == key)
        )
        setting = result.scalar_one_or_none()
        if not setting:
            return {"error": f"Setting '{key}' not found"}

        old_value = setting.value
        setting.value = value
        
        # Mask sensitive values before logging to audit log
        log_old = old_value
        log_new = value
        if setting.is_sensitive:
            log_old = "********" if old_value else None
            log_new = "********" if value else None

        await audit_log(
            self.db,
            "admin.platform_setting_changed",
            actor_user_id=admin_user_id,
            actor_role="super_admin",
            category="admin",
            resource_type="platform_setting",
            resource_id=key,
            details={
                "key": key,
                "old_value": log_old,
                "new_value": log_new
            },
        )
        await self.db.commit()

        if key == "rbac_roles":
            global _ROLES_CACHE, _LAST_ROLES_FETCH
            _ROLES_CACHE = {}
            _LAST_ROLES_FETCH = None

        logger.info("platform_setting_updated", key=key)
        return {"status": "updated", "key": key}

    async def create_trial_tenant(
        self,
        name: str,
        business_name: str,
        plan: str,
        admin_email: str,
        admin_password: str,
        created_by: str,
    ) -> Dict[str, Any]:
        normalized_email = admin_email.strip().lower()
        slug = name.strip().lower().replace(" ", "-")

        existing_slug = await self.db.execute(select(Tenant).where(Tenant.slug == slug))
        if existing_slug.scalar_one_or_none():
            return {"error": "Tenant slug already exists"}

        existing_user = await self.db.execute(select(User).where(User.email == normalized_email))
        if existing_user.scalar_one_or_none():
            return {"error": "Admin email already exists"}

        tenant = Tenant(
            id=uuid.uuid4(),
            name=name,
            slug=slug,
            business_type="other",
            business_name=business_name,
            email=normalized_email,
            phone="",
            address={},
            timezone="UTC",
            plan=plan,
            plan_limits={},
            is_active=True,
            subscription_status="trialing",
            trial_ends_at=_utcnow() + timedelta(days=14),
            metadata_={"created_via": "admin_trial_tenant"},
        )
        self.db.add(tenant)
        await self.db.flush()

        usage = TenantUsage(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            agent_count=1,
            last_reset_at=_utcnow(),
        )
        self.db.add(usage)

        user = User(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            email=normalized_email,
            hashed_password=auth_service.hash_password(admin_password),
            full_name=business_name,
            role="owner",
            is_active=True,
            is_email_verified=True,
        )
        self.db.add(user)

        await audit_log(
            self.db,
            "tenant.trial_created",
            tenant_id=str(tenant.id),
            actor_user_id=created_by,
            actor_role="super_admin",
            category="admin",
            resource_type="tenant",
            resource_id=str(tenant.id),
            details={"name": name, "business_name": business_name, "plan": plan},
        )
        await self.db.commit()
        logger.info("trial_tenant_created", tenant_id=str(tenant.id), slug=slug)
        return _serialize_tenant(tenant, agent_count=1, user_count=1)

    async def get_all_tenants_usage(self) -> Dict[str, Any]:
        result = await self.db.execute(
            select(Tenant, TenantUsage)
            .join(TenantUsage, TenantUsage.tenant_id == Tenant.id, isouter=True)
            .where(Tenant.subscription_status != "deleted")
            .order_by(TenantUsage.total_cost_usd.desc().nullslast(), Tenant.created_at.desc())
        )

        tenants: list[dict[str, Any]] = []
        for tenant, usage in result.all():
            tenants.append(
                {
                    "tenant_id": str(tenant.id),
                    "tenant_name": tenant.business_name,
                    "status": _tenant_lifecycle(tenant),
                    "plan": tenant.plan,
                    "current_month_messages": usage.current_month_messages if usage else 0,
                    "current_month_chat_units": usage.current_month_chat_units if usage else 0,
                    "current_month_sessions": usage.current_month_sessions if usage else 0,
                    "current_month_tokens": usage.current_month_tokens if usage else 0,
                    "current_month_voice_minutes": usage.current_month_voice_minutes if usage else 0.0,
                    "total_cost_usd": usage.total_cost_usd if usage else 0.0,
                    "agent_count": usage.agent_count if usage else 0,
                }
            )
        return {"tenants": tenants}
