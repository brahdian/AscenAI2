from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.services.settings_service import SettingsService

router = APIRouter(tags=["platform"])

@router.get("/language-config")
async def get_language_config(db: AsyncSession = Depends(get_db)):
    """Fetch global language configuration and localized strings."""
    config = await SettingsService.get_setting(db, "global_language_config")
    if not config:
        raise HTTPException(status_code=404, detail="Language configuration not found.")
    return config
