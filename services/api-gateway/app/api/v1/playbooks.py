from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.playbook_validator import validate_playbook_safety

router = APIRouter(prefix="/playbooks")


class ValidateSafetyRequest(BaseModel):
    text: str = Field(..., description="Playbook content to validate")


@router.post("/validate-safety")
async def validate_playbook_safety_endpoint(body: ValidateSafetyRequest) -> dict:
    result = validate_playbook_safety(body.text)
    return result