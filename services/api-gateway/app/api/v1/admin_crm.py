from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
import structlog
from typing import List, Dict, Any

from app.api.deps import get_db, require_super_admin
from app.models.tenant import Tenant, TenantCRMWorkspace
from app.services.crm_service import CRMService
from app.core.config import settings

logger = structlog.get_logger(__name__)
router = APIRouter()

@router.get("/workspaces")
async def list_crm_workspaces(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_super_admin)
) -> List[Dict[str, Any]]:
    """
    Fetch all provisioned Twenty CRM workspaces, cross-referenced with Tenants.
    """
    stmt = (
        select(TenantCRMWorkspace, Tenant)
        .join(Tenant, Tenant.id == TenantCRMWorkspace.tenant_id)
    )
    result = await db.execute(stmt)
    rows = result.all()

    workspaces = []
    crm_service = CRMService()
    
    try:
        async with crm_service.engine.connect() as conn:
            for workspace, tenant in rows:
                # Count active users in the core.workspaceMember table if possible
                # Or core.user. We just query the twenty DB.
                active_users_count = 0
                try:
                    res = await conn.execute(
                        text("SELECT count(*) FROM core.\"workspaceMember\" WHERE \"workspaceId\" = :w_id"),
                        {"w_id": workspace.twenty_workspace_id}
                    )
                    active_users_count = res.scalar() or 0
                except Exception as e:
                    logger.warning("failed_to_count_workspace_members", error=str(e), workspace_id=workspace.id)

                workspaces.append({
                    "id": str(workspace.id),
                    "tenant_id": str(tenant.id),
                    "tenant_name": tenant.name,
                    "twenty_workspace_id": str(workspace.twenty_workspace_id),
                    "custom_subdomain": workspace.custom_subdomain,
                    "is_active": workspace.is_active,
                    "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
                    "active_users": active_users_count,
                    "allowed_seats": tenant.crm_seats
                })
    except Exception as e:
        logger.error("failed_to_connect_to_twenty_db", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to connect to Twenty database")

    return workspaces

@router.get("/health")
async def check_crm_health(_=Depends(require_super_admin)):
    """
    Perform a diagnostic check on the Twenty CRM integration.
    """
    health = {
        "database": "unknown",
        "redis_sso": "unknown",
        "details": {}
    }
    
    crm_service = CRMService()
    
    # 1. Check DB
    try:
        async with crm_service.engine.connect() as conn:
            res = await conn.execute(text("SELECT 1"))
            if res.scalar() == 1:
                health["database"] = "healthy"
            
            # Check if core schema exists
            schema_res = await conn.execute(text("SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'core'"))
            if schema_res.scalar():
                health["details"]["schema_core"] = "present"
            else:
                health["details"]["schema_core"] = "missing"
                health["database"] = "degraded"
    except Exception as e:
        health["database"] = "unhealthy"
        health["details"]["db_error"] = str(e)
        
    # 2. Check Redis (SSO)
    from redis.asyncio import Redis
    redis_url = settings.REDIS_URL
    if "/0" in redis_url:
        redis_url = redis_url.replace("/0", "/1")
    elif not any(f"/{i}" in redis_url for i in range(1, 16)):
        redis_url = f"{redis_url.rstrip('/')}/1"
        
    try:
        twenty_redis = Redis.from_url(redis_url, decode_responses=False)
        await twenty_redis.ping()
        health["redis_sso"] = "healthy"
        await twenty_redis.close()
    except Exception as e:
        health["redis_sso"] = "unhealthy"
        health["details"]["redis_error"] = str(e)
        
    status_code = 200 if health["database"] == "healthy" and health["redis_sso"] == "healthy" else 503
    return health

@router.post("/workspaces/{workspace_id}/repair")
async def repair_workspace(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_super_admin)
):
    """
    Attempt to repair a workspace mapping.
    """
    stmt = select(TenantCRMWorkspace).where(TenantCRMWorkspace.id == workspace_id)
    res = await db.execute(stmt)
    workspace = res.scalar_one_or_none()
    
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
        
    crm_service = CRMService()
    repair_log = []
    
    try:
        async with crm_service.engine.connect() as conn:
            # Check if twenty workspace exists
            w_res = await conn.execute(
                text("SELECT id FROM core.workspace WHERE id = :w_id"),
                {"w_id": workspace.twenty_workspace_id}
            )
            if w_res.scalar_one_or_none():
                repair_log.append("Twenty workspace exists.")
            else:
                repair_log.append("Twenty workspace MISSING. Manual intervention required.")
                workspace.is_active = False
                await db.commit()
                return {"status": "failed", "log": repair_log}
                
    except Exception as e:
        logger.error("workspace_repair_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Repair failed: {str(e)}")
        
    return {"status": "success", "log": repair_log}
