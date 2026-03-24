from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from app.core.config import settings
from app.schemas.voice import STTResponse, TTSRequest
from app.services.stt_service import STTService
from app.services.tts_service import TTSService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/voice")

_stt_service = STTService()
_tts_service = TTSService()


def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


@router.post("/stt", response_model=STTResponse)
async def speech_to_text(
    request: Request,
    audio: UploadFile = File(..., description="Audio file (wav, mp3, webm, ogg)"),
    language: str = Form(default="en"),
    session_id: str = Form(default=""),
):
    """Convert uploaded audio to text."""
    _tenant_id(request)
    audio_bytes = await audio.read()
    if len(audio_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty audio file.")

    try:
        result = await _stt_service.transcribe_audio(
            audio_bytes,
            language=language,
            format=audio.content_type or "audio/wav",
        )
    except Exception as exc:
        logger.error("stt_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"STT failed: {exc}")

    return STTResponse(
        transcript=result.text,
        language=language,
        session_id=session_id or str(uuid.uuid4()),
    )


@router.post("/tts")
async def text_to_speech(
    body: TTSRequest,
    request: Request,
):
    """Convert text to speech audio."""
    _tenant_id(request)
    try:
        audio_bytes = await _tts_service.synthesize(
            text=body.text,
            voice_id=body.voice_id,
            speed=body.speed,
            format=body.format,
        )
    except Exception as exc:
        logger.error("tts_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"TTS failed: {exc}")

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": 'attachment; filename="speech.mp3"',
            "X-Text-Length": str(len(body.text)),
        },
    )
