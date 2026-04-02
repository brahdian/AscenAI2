from __future__ import annotations

import re
import uuid

import structlog
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

from app.core.config import settings
from app.schemas.voice import STTResponse, TTSRequest
from app.services.stt_service import STTService
from app.services.tts_service import TTSService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/voice")

_stt_service = STTService()
_tts_service = TTSService()

# Sentence boundary pattern for splitting streamed text into TTS-able chunks
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|(?<=\n)")


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


@router.post("/tts/stream")
async def text_to_speech_stream(
    body: TTSRequest,
    request: Request,
):
    """Stream TTS audio sentence-by-sentence for low-latency playback.

    Splits input text on sentence boundaries and streams each sentence's
    audio as it's synthesized. The client can begin playing audio before
    the full response is ready.

    Response format: each chunk is raw MP3 audio bytes. Sentences are
    separated by a small silence marker so the client can distinguish
    sentence boundaries for smooth concatenation.
    """
    _tenant_id(request)
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text is empty.")

    sentences = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]
    if not sentences:
        sentences = [text]

    logger.info(
        "tts_stream_request",
        sentences=len(sentences),
        total_chars=len(text),
        voice_id=body.voice_id,
    )

    async def _audio_generator():
        for i, sentence in enumerate(sentences):
            try:
                audio_iter = _tts_service.synthesize_stream(
                    text=sentence,
                    voice_id=body.voice_id or "alloy",
                )
                async for chunk in audio_iter:
                    if chunk:
                        yield chunk
            except Exception as exc:
                logger.warning(
                    "tts_stream_sentence_error",
                    sentence_idx=i,
                    error=str(exc),
                )
                # Continue to next sentence rather than aborting the stream

    return StreamingResponse(
        _audio_generator(),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache",
            "X-TTS-Sentences": str(len(sentences)),
            "Access-Control-Expose-Headers": "X-TTS-Sentences",
        },
    )
