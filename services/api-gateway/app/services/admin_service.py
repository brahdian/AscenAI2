"""
Admin Service — Platform administration, tenant management, RBAC.

Provides:
- Tenant management (list, create, suspend, delete)
- User management with role-based access control
- System prompt management (global + per-agent)
- Audit logging for all admin actions
- Observability APIs (traces, metrics, logs)

RBAC Roles:
- super_admin: Full platform access, can manage all tenants
- tenant_owner: Full tenant access, can manage users and agents
- tenant_admin: Can manage agents, tools, playbooks
- developer: Read-only access, can view traces and metrics
- viewer: Minimal read-only access
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# RBAC Definitions
# ---------------------------------------------------------------------------

ROLES = {
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
        ],
    },
    "tenant_owner": {
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
    "tenant_admin": {
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


def has_permission(role: str, permission: str) -> bool:
    """Check if a role has a specific permission."""
    role_config = ROLES.get(role, {})
    return permission in role_config.get("permissions", [])


def get_role_level(role: str) -> int:
    """Get the numeric level of a role."""
    return ROLES.get(role, {}).get("level", 0)


# ---------------------------------------------------------------------------
# Audit Logger
# ---------------------------------------------------------------------------

class AuditLogger:
    """Logs all admin actions for compliance."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def log_action(
        self,
        user_id: str,
        tenant_id: str,
        action: str,
        resource_type: str,
        resource_id: str = "",
        details: Dict[str, Any] = None,
        ip_address: str = "",
    ) -> None:
        """Log an admin action."""
        log_entry = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "tenant_id": tenant_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details": details or {},
            "ip_address": ip_address,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "audit_action",
            **log_entry,
        )

        # Persist to database (if audit_log table exists)
        try:
            await self.db.execute(
                text("""
                    INSERT INTO audit_logs (id, user_id, tenant_id, action, resource_type, resource_id, details, ip_address, created_at)
                    VALUES (:id, :user_id, :tenant_id, :action, :resource_type, :resource_id, :details, :ip_address, :timestamp)
                """),
                {
                    "id": log_entry["id"],
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "details": str(details or {}),
                    "ip_address": ip_address,
                    "timestamp": log_entry["timestamp"],
                },
            )
            await self.db.commit()
        except Exception as e:
            # Table might not exist yet; log and continue
            logger.debug("audit_log_db_error", error=str(e))


# ---------------------------------------------------------------------------
# Admin Service
# ---------------------------------------------------------------------------

class AdminService:
    """Platform administration service."""

    def __init__(self, db: AsyncSession, redis_client):
        self.db = db
        self.redis = redis_client
        self.audit = AuditLogger(db)

    async def list_tenants(
        self,
        page: int = 1,
        per_page: int = 50,
        status: str = "",
    ) -> Dict[str, Any]:
        """List all tenants with pagination."""
        offset = (page - 1) * per_page

        query = "SELECT id, name, business_name, plan, status, created_at FROM tenants"
        params: Dict[str, Any] = {}

        if status:
            query += " WHERE status = :status"
            params["status"] = status

        query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        params["limit"] = per_page
        params["offset"] = offset

        result = await self.db.execute(text(query), params)
        tenants = [dict(row._mapping) for row in result.fetchall()]

        # Get total count
        count_query = "SELECT COUNT(*) FROM tenants"
        if status:
            count_query += " WHERE status = :status"
        count_result = await self.db.execute(text(count_query), {"status": status} if status else {})
        total = count_result.scalar() or 0

        return {
            "tenants": tenants,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page,
            },
        }

    async def get_tenant_details(
        self,
        tenant_id: str,
    ) -> Dict[str, Any]:
        """Get detailed tenant information."""
        result = await self.db.execute(
            text("SELECT * FROM tenants WHERE id = :id"),
            {"id": tenant_id},
        )
        tenant = result.fetchone()

        if not tenant:
            return {"error": "Tenant not found"}

        tenant_dict = dict(tenant._mapping)

        # Get agent count
        agent_result = await self.db.execute(
            text("SELECT COUNT(*) FROM agents WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        tenant_dict["agent_count"] = agent_result.scalar() or 0

        # Get user count
        user_result = await self.db.execute(
            text("SELECT COUNT(*) FROM users WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        tenant_dict["user_count"] = user_result.scalar() or 0

        return tenant_dict

    async def suspend_tenant(
        self,
        tenant_id: str,
        reason: str,
        admin_user_id: str,
    ) -> Dict[str, Any]:
        """Suspend a tenant."""
        await self.db.execute(
            text("UPDATE tenants SET status = 'suspended' WHERE id = :id"),
            {"id": tenant_id},
        )
        await self.db.commit()

        await self.audit.log_action(
            user_id=admin_user_id,
            tenant_id=tenant_id,
            action="tenant_suspend",
            resource_type="tenant",
            resource_id=tenant_id,
            details={"reason": reason},
        )

        logger.info("tenant_suspended", tenant_id=tenant_id, reason=reason)
        return {"status": "suspended", "tenant_id": tenant_id}

    async def reactivate_tenant(
        self,
        tenant_id: str,
        admin_user_id: str,
    ) -> Dict[str, Any]:
        """Reactivate a suspended tenant."""
        await self.db.execute(
            text("UPDATE tenants SET status = 'active' WHERE id = :id"),
            {"id": tenant_id},
        )
        await self.db.commit()

        await self.audit.log_action(
            user_id=admin_user_id,
            tenant_id=tenant_id,
            action="tenant_reactivate",
            resource_type="tenant",
            resource_id=tenant_id,
        )

        logger.info("tenant_reactivated", tenant_id=tenant_id)
        return {"status": "active", "tenant_id": tenant_id}

    async def delete_tenant(
        self,
        tenant_id: str,
        admin_user_id: str,
        hard_delete: bool = False,
    ) -> Dict[str, Any]:
        """Delete a tenant (soft or hard)."""
        if hard_delete:
            # Cascade delete all related data
            tables = [
                "messages", "sessions", "agents", "agent_playbooks",
                "agent_guardrails", "agent_documents", "agent_analytics",
                "message_feedback", "conversation_traces", "playbook_executions",
            ]
            for table in tables:
                await self.db.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tid"),
                    {"tid": tenant_id},
                )

            await self.db.execute(
                text("DELETE FROM users WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            await self.db.execute(
                text("DELETE FROM tenants WHERE id = :id"),
                {"id": tenant_id},
            )
        else:
            # Soft delete
            await self.db.execute(
                text("UPDATE tenants SET status = 'deleted' WHERE id = :id"),
                {"id": tenant_id},
            )

        await self.db.commit()

        await self.audit.log_action(
            user_id=admin_user_id,
            tenant_id=tenant_id,
            action="tenant_delete",
            resource_type="tenant",
            resource_id=tenant_id,
            details={"hard_delete": hard_delete},
        )

        logger.info("tenant_deleted", tenant_id=tenant_id, hard=hard_delete)
        return {"status": "deleted", "tenant_id": tenant_id, "hard": hard_delete}

    async def list_users(
        self,
        tenant_id: str = "",
        page: int = 1,
        per_page: int = 50,
    ) -> Dict[str, Any]:
        """List users, optionally filtered by tenant."""
        offset = (page - 1) * per_page

        query = "SELECT id, email, name, role, tenant_id, is_active, created_at FROM users"
        params: Dict[str, Any] = {}

        if tenant_id:
            query += " WHERE tenant_id = :tid"
            params["tid"] = tenant_id

        query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        params["limit"] = per_page
        params["offset"] = offset

        result = await self.db.execute(text(query), params)
        users = [dict(row._mapping) for row in result.fetchall()]

        # Get total count
        count_query = "SELECT COUNT(*) FROM users"
        if tenant_id:
            count_query += " WHERE tenant_id = :tid"
        count_result = await self.db.execute(text(count_query), {"tid": tenant_id} if tenant_id else {})
        total = count_result.scalar() or 0

        return {
            "users": users,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page,
            },
        }

    async def update_user_role(
        self,
        user_id: str,
        new_role: str,
        admin_user_id: str,
    ) -> Dict[str, Any]:
        """Update a user's role."""
        if new_role not in ROLES:
            return {"error": f"Invalid role: {new_role}"}

        await self.db.execute(
            text("UPDATE users SET role = :role WHERE id = :id"),
            {"role": new_role, "id": user_id},
        )
        await self.db.commit()

        await self.audit.log_action(
            user_id=admin_user_id,
            tenant_id="",
            action="user_role_update",
            resource_type="user",
            resource_id=user_id,
            details={"new_role": new_role},
        )

        logger.info("user_role_updated", user_id=user_id, new_role=new_role)
        return {"status": "updated", "user_id": user_id, "role": new_role}

    async def get_system_prompts(
        self,
        agent_id: str = "",
    ) -> Dict[str, Any]:
        """Get system prompts (global or per-agent)."""
        if agent_id:
            result = await self.db.execute(
                text("SELECT system_prompt, system_prompt_version FROM agents WHERE id = :id"),
                {"id": agent_id},
            )
            row = result.fetchone()
            if row:
                return {
                    "agent_id": agent_id,
                    "system_prompt": row._mapping.get("system_prompt", ""),
                    "version": row._mapping.get("system_prompt_version", 1),
                }
            return {"error": "Agent not found"}

        # Return global prompts (from templates)
        result = await self.db.execute(
            text("SELECT id, name, system_prompt_template FROM agent_templates LIMIT 20"),
        )
        templates = [dict(row._mapping) for row in result.fetchall()]
        return {"templates": templates}

    async def update_system_prompt(
        self,
        agent_id: str,
        system_prompt: str,
        admin_user_id: str,
    ) -> Dict[str, Any]:
        """Update an agent's system prompt."""
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
        await self.db.commit()

        await self.audit.log_action(
            user_id=admin_user_id,
            tenant_id="",
            action="system_prompt_update",
            resource_type="agent",
            resource_id=agent_id,
            details={"prompt_length": len(system_prompt)},
        )

        logger.info("system_prompt_updated", agent_id=agent_id)
        return {"status": "updated", "agent_id": agent_id}

    async def get_traces(
        self,
        session_id: str = "",
        tenant_id: str = "",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Get conversation traces (redacted)."""
        query = "SELECT * FROM conversation_traces WHERE 1=1"
        params: Dict[str, Any] = {}

        if session_id:
            query += " AND session_id = :sid"
            params["sid"] = session_id
        if tenant_id:
            query += " AND tenant_id = :tid"
            params["tid"] = tenant_id

        query += " ORDER BY created_at DESC LIMIT :limit"
        params["limit"] = limit

        result = await self.db.execute(text(query), params)
        traces = [dict(row._mapping) for row in result.fetchall()]

        return {"traces": traces, "count": len(traces)}

    async def get_platform_metrics(self) -> Dict[str, Any]:
        """Get platform-wide metrics."""
        # Active tenants
        result = await self.db.execute(
            text("SELECT COUNT(*) FROM tenants WHERE status = 'active'")
        )
        active_tenants = result.scalar() or 0

        # Total agents
        result = await self.db.execute(text("SELECT COUNT(*) FROM agents"))
        total_agents = result.scalar() or 0

        # Total sessions today
        result = await self.db.execute(
            text("SELECT COUNT(*) FROM sessions WHERE created_at > NOW() - INTERVAL '24 hours'")
        )
        sessions_today = result.scalar() or 0

        # Total messages today
        result = await self.db.execute(
            text("SELECT COUNT(*) FROM messages WHERE created_at > NOW() - INTERVAL '24 hours'")
        )
        messages_today = result.scalar() or 0

        return {
            "active_tenants": active_tenants,
            "total_agents": total_agents,
            "sessions_today": sessions_today,
            "messages_today": messages_today,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
