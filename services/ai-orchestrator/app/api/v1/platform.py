from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.database import get_db
from shared.orchestration.settings_service import SettingsService
import json
import uuid

router = APIRouter(tags=["platform"])


def _restricted_agent_id(request: Request) -> uuid.UUID | None:
    """Extract optional agent restriction passed by the API Gateway proxy."""
    raid = request.headers.get("X-Restricted-Agent-ID")
    if raid:
        try:
            return uuid.UUID(raid)
        except ValueError:
            return None
    return None

@router.get("/language-config")
async def get_language_config(db: AsyncSession = Depends(get_db)):
    """Fetch global language configuration and localized strings."""
    config = await SettingsService.get_setting(db, "global_language_config")
    if not config:
        raise HTTPException(status_code=404, detail="Language configuration not found.")
    return config


@router.get("/response-limits")
async def get_response_limits(db: AsyncSession = Depends(get_db)):
    """Fetch platform-wide response conciseness limits."""
    limits = await SettingsService.get_setting(db, "global_response_limits", default={})
    return {
        "voice_max_words": limits.get("voice_max_words", 50),
        "chat_max_words": limits.get("chat_max_words", 50),
    }


@router.put("/response-limits")
async def update_response_limits(body: dict, request: Request, db: AsyncSession = Depends(get_db)):
    """Update platform-wide response conciseness limits (admin only)."""
    if _restricted_agent_id(request):
        raise HTTPException(status_code=403, detail="Restricted keys cannot modify platform settings.")
    voice_max = int(body.get("voice_max_words", 50))
    chat_max = int(body.get("chat_max_words", 50))
    limits = {"voice_max_words": voice_max, "chat_max_words": chat_max}
    await db.execute(
        text(
            "INSERT INTO platform_settings (key, value) VALUES ('global_response_limits', :value) "
            "ON CONFLICT (key) DO UPDATE SET value = :value"
        ),
        {"value": json.dumps(limits)},
    )
    await db.commit()
    await SettingsService.invalidate_cache("global_response_limits")
    return limits

@router.get("/voice-protocols")
async def get_voice_protocols(db: AsyncSession = Depends(get_db)):
    """Fetch global predefined voice protocols."""
    protocols = await SettingsService.get_setting(db, "global_voice_protocols", default=[])
    if not protocols:
        # Provide the hardcoded defaults if missing in DB
        protocols = [
            {
                "id": "direct_action",
                "label": "1. ⚡ Direct & Action-Oriented",
                "template": "- Be extremely concise and to the point.\n- Ask direct questions.\n- Prioritize speed of service over small talk.\n- Never use filler words (e.g. 'um', 'ah', 'got it')."
            },
            {
                "id": "supportive_knowledge",
                "label": "2. 🤝 Supportive & Knowledge-Driven",
                "template": "- Speak with a warm, empathetic tone.\n- Focus on listening and acknowledging the caller's concerns.\n- Ensure they understand the process before moving on.\n- Be patient with long pauses or disorganized speech."
            },
            {
                "id": "handoff_routing",
                "label": "3. 🔀 Handoff & Routing",
                "template": "- Keep interactions strictly limited to qualifying questions.\n- Immediately evaluate if human handoff is needed.\n- Avoid answering complex contextual questions; instead route to a specialist."
            }
        ]
    return protocols

@router.put("/voice-protocols")
async def update_voice_protocols(body: list, request: Request, db: AsyncSession = Depends(get_db)):
    """Update global predefined voice protocols (admin only)."""
    if _restricted_agent_id(request):
        raise HTTPException(status_code=403, detail="Restricted keys cannot modify platform settings.")
    await db.execute(
        text(
            "INSERT INTO platform_settings (key, value) VALUES ('global_voice_protocols', :value) "
            "ON CONFLICT (key) DO UPDATE SET value = :value"
        ),
        {"value": json.dumps(body)},
    )
    await db.commit()
    await SettingsService.invalidate_cache("global_voice_protocols")
    return body
