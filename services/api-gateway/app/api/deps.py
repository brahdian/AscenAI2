import uuid
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db as _get_db
from app.core.security import get_tenant_db as _get_tenant_db
from app.core.security import get_current_tenant as _get_current_tenant
from app.models.user import User

async def get_db():
    async for db in _get_db():
        yield db

async def get_tenant_db(tenant_id: str = Depends(_get_current_tenant)):
    async for db in _get_db(tenant_id=tenant_id):
        yield db

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> User:
    """Dependency that returns the current authenticated User model."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        # AuthMiddleware should have caught this, but we'll be safe
        raise HTTPException(status_code=401, detail="Authentication required.")
    
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    return user

def require_super_admin(request: Request) -> str:
    """Require super_admin role."""
    role = getattr(request.state, "role", "")
    if role != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required.")
    return getattr(request.state, "user_id", "")

def require_admin(request: Request) -> tuple[str, str]:
    """Require tenant admin/owner or super_admin role."""
    role = getattr(request.state, "role", "")
    if role not in ("super_admin", "owner", "admin"):
        raise HTTPException(status_code=403, detail="Admin access required.")
    user_id = getattr(request.state, "user_id", "")
    tenant_id = getattr(request.state, "tenant_id", "")
    return user_id, tenant_id
