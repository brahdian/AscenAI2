from fastapi import APIRouter, Depends, HTTPException, Body
from typing import List, Any
import uuid

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.services.crm_service import crm_service
from app.core.config import settings

router = APIRouter(prefix="/crm", tags=["crm"])

@router.get("/workspaces")
async def list_crm_workspaces(
    current_user: User = Depends(get_current_user)
) -> List[Any]:
    """List all CRM workspaces (companies) for the current tenant."""
    return await crm_service.list_workspaces(current_user.tenant_id)

@router.post("/workspaces")
async def create_crm_workspace(
    company_name: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user)
) -> Any:
    """Create a new CRM workspace for a company."""
    # Note: In a real app, we might check permissions or billing here.
    return await crm_service.create_crm_workspace(
        tenant_id=current_user.tenant_id,
        company_name=company_name,
        owner_email=current_user.email,
        owner_full_name=f"{current_user.first_name} {current_user.last_name}"
    )

@router.post("/workspaces/{mapping_id}/users")
async def add_crm_user(
    mapping_id: uuid.UUID,
    email: str = Body(..., embed=True),
    full_name: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user)
) -> Any:
    """Provision a new user in a specific CRM workspace."""
    success = await crm_service.provision_user(mapping_id, email, full_name)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to provision user. Check slot limits.")
    return {"status": "success"}

@router.get("/sso-link")
async def get_crm_sso_link(
    subdomain: str,
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Generate a seamless login link for Twenty CRM.
    Injects a session into Twenty's Redis and returns a redirect with a cookie.
    """
    try:
        session_id = await crm_service.generate_sso_session(current_user.email)
        
        # We return the URL and the session ID for the frontend to set the cookie
        # Or we could return a Response object that sets the cookie.
        # But since the Dashboard is on app.lvh.me and Twenty is on *.lvh.me,
        # we can set a wildcard cookie.
        
        url = f"http://{subdomain}.lvh.me:3001"
        
        # We use a trick: Redirect to a bridge page or just return the data.
        # For "Best in Industry" feel, we'll return a direct login URL that Twenty 
        # doesn't natively have, or just let the frontend set the cookie.
        
        return {
            "url": url,
            "session_id": session_id,
            "cookie_domain": ".lvh.me",
            "cookie_name": "twenty.sid"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
