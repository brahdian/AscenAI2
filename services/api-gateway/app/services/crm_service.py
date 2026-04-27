from __future__ import annotations

import re
import uuid
import json
import structlog
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, List

from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import create_async_engine
from redis.asyncio import Redis

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.tenant import TenantCRMWorkspace

logger = structlog.get_logger(__name__)

# Twenty CRM uses a schema-per-tenant-ish metadata approach, but core tables
# like 'user' and 'workspace' live in the 'core' schema.
SCHEMA = "core"

def slugify(text_val: str) -> str:
    """Simple slugify implementation for subdomains."""
    text_val = text_val.lower().strip()
    text_val = re.sub(r'[^\w\s-]', '', text_val)
    text_val = re.sub(r'[\s_-]+', '-', text_val)
    text_val = re.sub(r'^-+|-+$', '', text_val)
    return text_val

class CRMService:
    """
    Service for provisioning and managing Twenty CRM workspaces and users.
    Interacts directly with Twenty's database via the shared PostgreSQL instance.
    Supports Multi-Company (Multiple Workspaces) per AscenAI Tenant.
    """

    def __init__(self):
        # We create a dedicated engine for the Twenty database
        self.engine = create_async_engine(
            settings.TWENTY_DATABASE_URL,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )

    async def generate_sso_session(self, email: str) -> str:
        """
        Inject a valid Twenty session into Redis and return the session ID.
        This provides a seamless "Best in Industry" SSO experience.
        """
        logger.info("generating_crm_sso_session", email=email)

        # 1. Find Twenty User ID
        async with self.engine.connect() as conn:
            res = await conn.execute(
                text(f"SELECT id FROM {SCHEMA}.user WHERE email = :email"),
                {"email": email}
            )
            user_id = res.scalar_one_or_none()
            if not user_id:
                logger.error("crm_user_not_found", email=email)
                raise ValueError("User not found in Twenty CRM. Please ensure integration is active.")

        # 2. Create Session ID and Data
        session_id = uuid.uuid4().hex
        # Twenty uses express-session. Standard format for passport:
        session_data = {
            "cookie": {
                "originalMaxAge": 86400000,
                "expires": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                "secure": False, 
                "httpOnly": True,
                "domain": settings.COOKIE_DOMAIN or f".{settings.ROOT_DOMAIN}",
                "path": "/"
            },
            "passport": { "user": str(user_id) }
        }
        
        # 3. Write to Twenty's Redis (Index 1 by convention for sessions)
        # We derive the Twenty Redis URL by changing the DB index
        redis_url = settings.REDIS_URL
        if "/0" in redis_url:
            redis_url = redis_url.replace("/0", "/1")
        elif not any(f"/{i}" in redis_url for i in range(1, 16)):
            # No index specified, append /1
            redis_url = f"{redis_url.rstrip('/')}/1"
            
        twenty_redis = Redis.from_url(redis_url, decode_responses=False)
        try:
            # express-session's RedisStore usually uses 'sess:' prefix
            await twenty_redis.set(f"sess:{session_id}", json.dumps(session_data), ex=86400)
            logger.info("crm_sso_session_injected", session_id=session_id)
        finally:
            await twenty_redis.close()
        
        return session_id

    async def create_crm_workspace(
        self, 
        tenant_id: uuid.UUID, 
        company_name: str,
        owner_email: str,
        owner_full_name: str = "Admin"
    ) -> dict[str, Any]:
        """
        Create a new Twenty Workspace (Company) for a tenant.
        """
        logger.info("creating_crm_workspace", tenant_id=str(tenant_id), company=company_name)

        workspace_id = uuid.uuid4()
        user_id = uuid.uuid4()
        
        # Slugify company name for subdomain
        subdomain = slugify(company_name)
        if not subdomain:
            subdomain = f"co-{str(uuid.uuid4())[:8]}"
        
        # Ensure subdomain is unique in Twenty (simple check)
        async with self.engine.connect() as conn:
            res = await conn.execute(
                text(f"SELECT id FROM {SCHEMA}.workspace WHERE subdomain = :subdomain"),
                {"subdomain": subdomain}
            )
            if res.fetchone():
                subdomain = f"{subdomain}-{str(uuid.uuid4())[:4]}"

        async with self.engine.begin() as conn:
            # 1. Insert Workspace into Twenty
            await conn.execute(
                text(f"""
                    INSERT INTO {SCHEMA}."workspace" (
                        id, "displayName", subdomain, "activationStatus", 
                        "isPasswordAuthEnabled", "isGoogleAuthEnabled", "isMicrosoftAuthEnabled",
                        "createdAt", "updatedAt"
                    ) VALUES (
                        :id, :name, :subdomain, 'ACTIVE', 
                        true, false, false,
                        NOW(), NOW()
                    )
                """),
                {"id": workspace_id, "name": company_name, "subdomain": subdomain}
            )

            # 2. Ensure User exists in Twenty
            names = owner_full_name.split(" ", 1)
            first_name = names[0] if names else "Admin"
            last_name = names[1] if len(names) > 1 else ""

            result = await conn.execute(
                text(f"SELECT id FROM {SCHEMA}.user WHERE email = :email"),
                {"email": owner_email}
            )
            existing_user = result.scalar_one_or_none()

            if existing_user:
                user_id = existing_user
            else:
                await conn.execute(
                    text(f"""
                        INSERT INTO {SCHEMA}."user" (
                            id, email, "firstName", "lastName", "isEmailVerified", 
                            "createdAt", "updatedAt", locale
                        ) VALUES (
                            :id, :email, :first, :last, true, 
                            NOW(), NOW(), 'en'
                        )
                    """),
                    {"id": user_id, "email": owner_email, "first": first_name, "last": last_name}
                )

            # 3. Link User to Workspace
            await conn.execute(
                text(f"""
                    INSERT INTO {SCHEMA}."userWorkspace" (
                        "userId", "workspaceId"
                    ) VALUES (
                        :user_id, :workspace_id
                    )
                    ON CONFLICT ("userId", "workspaceId") DO NOTHING
                """),
                {"user_id": user_id, "workspace_id": workspace_id}
            )

        # 4. Record the mapping in AscenAI Database
        async with AsyncSessionLocal() as db:
            mapping = TenantCRMWorkspace(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                company_name=company_name,
                subdomain=subdomain,
                user_slots=1 # Default 1 slot for the owner
            )
            db.add(mapping)
            await db.commit()
            await db.refresh(mapping)

        return {
            "id": str(mapping.id),
            "workspace_id": str(workspace_id),
            "subdomain": subdomain,
            "url": f"http://{subdomain}.{settings.ROOT_DOMAIN}:{settings.CRM_PORT}"
        }

    async def list_workspaces(self, tenant_id: uuid.UUID) -> List[dict]:
        """List all CRM workspaces for a tenant."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(TenantCRMWorkspace).where(TenantCRMWorkspace.tenant_id == tenant_id)
            )
            workspaces = result.scalars().all()
            return [
                {
                    "id": str(w.id),
                    "company_name": w.company_name,
                    "subdomain": w.subdomain,
                    "user_slots": w.user_slots,
                    "url": f"http://{w.subdomain}.{settings.ROOT_DOMAIN}:{settings.CRM_PORT}"
                }
                for w in workspaces
            ]

    async def add_user_slots(self, mapping_id: uuid.UUID, slots: int = 1) -> int:
        """Add user slots to a specific CRM workspace."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(TenantCRMWorkspace).where(TenantCRMWorkspace.id == mapping_id)
            )
            mapping = result.scalar_one_or_none()
            if not mapping:
                raise ValueError("CRM mapping not found")
            
            mapping.user_slots += slots
            await db.commit()
            return mapping.user_slots

    async def provision_user(
        self, 
        mapping_id: uuid.UUID, 
        email: str, 
        full_name: str
    ) -> bool:
        """
        Add a new user to a Twenty Workspace, checking slot limits.
        """
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(TenantCRMWorkspace).where(TenantCRMWorkspace.id == mapping_id)
            )
            mapping = result.scalar_one_or_none()
            if not mapping:
                return False

            # Check current user count in Twenty for this workspace
            async with self.engine.connect() as conn:
                res = await conn.execute(
                    text(f'SELECT COUNT(*) FROM {SCHEMA}."userWorkspace" WHERE "workspaceId" = :wid'),
                    {"wid": mapping.workspace_id}
                )
                current_count = res.scalar() or 0
                
                if current_count >= mapping.user_slots:
                    logger.warning("crm_slot_limit_reached", mapping_id=str(mapping_id))
                    return False

                # Proceed to add user to Twenty
                user_id = uuid.uuid4()
                names = full_name.split(" ", 1)
                first = names[0]
                last = names[1] if len(names) > 1 else ""

                # Check if user exists globally in Twenty
                res = await conn.execute(
                    text(f"SELECT id FROM {SCHEMA}.user WHERE email = :email"),
                    {"email": email}
                )
                existing_user = res.scalar_one_or_none()
                
                if existing_user:
                    user_id = existing_user
                else:
                    await conn.execute(
                        text(f"""
                            INSERT INTO {SCHEMA}."user" (
                                id, email, "firstName", "lastName", "isEmailVerified", 
                                "createdAt", "updatedAt", locale
                            ) VALUES (:id, :email, :first, :last, true, NOW(), NOW(), 'en')
                        """),
                        {"id": user_id, "email": email, "first": first, "last": last}
                    )

                # Link to workspace
                await conn.execute(
                    text(f"""
                        INSERT INTO {SCHEMA}."userWorkspace" ("userId", "workspaceId")
                        VALUES (:user_id, :workspace_id)
                        ON CONFLICT DO NOTHING
                    """),
                    {"user_id": user_id, "workspace_id": mapping.workspace_id}
                )
                await conn.commit()
                return True

# Singleton instance
crm_service = CRMService()
