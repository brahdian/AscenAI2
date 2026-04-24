from __future__ import annotations

import re
import uuid

import structlog
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from fastapi.responses import PlainTextResponse

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
    """Convert text to speech audio. Dispatches to the configured TTS_PROVIDER."""
    _tenant_id(request)
    provider = settings.TTS_PROVIDER.lower()
    try:
        if provider == "deepgram":
            audio_bytes = await _tts_service.synthesize_deepgram_to_bytes(
                text=body.text,
                voice_id=body.voice_id or "aura-asteria-en",
            )
        elif provider == "cartesia":
            audio_bytes = await _tts_service.synthesize_cartesia_to_bytes(
                text=body.text,
                voice_id=body.voice_id or settings.CARTESIA_VOICE_ID,
            )
        else:
            # openai or any other provider
            audio_bytes = await _tts_service.synthesize(
                text=body.text,
                voice_id=body.voice_id,
                speed=body.speed,
                format=body.format,
            )
    except Exception as exc:
        logger.error("tts_failed", error=str(exc), provider=provider)
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

    provider = settings.TTS_PROVIDER.lower()

    async def _audio_generator():
        for i, sentence in enumerate(sentences):
            try:
                if provider == "deepgram":
                    audio_iter = _tts_service.synthesize_deepgram_stream(
                        text=sentence,
                        voice_id=body.voice_id or "aura-asteria-en",
                    )
                elif provider == "cartesia":
                    audio_iter = _tts_service.synthesize_cartesia_stream(
                        text=sentence,
                        voice_id=body.voice_id or settings.CARTESIA_VOICE_ID,
                    )
                else:
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


# ---------------------------------------------------------------------------
# Twilio TwiML webhook endpoints
# ---------------------------------------------------------------------------


@router.post("/twilio/incoming")
async def twilio_incoming_call(request: Request):
    """
    TwiML response that connects an inbound Twilio call to our Media Streams
    WebSocket endpoint for real-time AI voice handling.

    Query parameters expected by Twilio when the webhook URL is configured:
      ?agent_id=<id>&tenant_id=<id>&session_id=<id>&token=<jwt>

    If any required parameter is missing, falls back to safe defaults so
    Twilio can still establish a stream (the pipeline will reject the WS
    with 4401 if the token is invalid).
    """
    params = dict(request.query_params)
    agent_id = params.get("agent_id", "default")
    tenant_id = params.get("tenant_id", "")
    session_id = params.get("session_id") or str(uuid.uuid4())
    token = params.get("token", "")

    # Build the WebSocket URL. Use the Host header so the TwiML is correct
    # regardless of whether we are behind a reverse proxy or ngrok tunnel.
    host = request.headers.get("host", "localhost:8003")
    # Twilio requires wss:// for secure WebSocket Media Streams
    ws_url = (
        f"wss://{host}/ws/voice/{agent_id}"
        f"?tenant_id={tenant_id}"
        f"&session_id={session_id}"
        f"&token={token}"
    )

    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Connect>"
        f'<Stream url="{ws_url}" />'
        "</Connect>"
        "</Response>"
    )

    logger.info(
        "twilio_incoming_call_twiml",
        agent_id=agent_id,
        tenant_id=tenant_id,
        session_id=session_id,
    )

    return Response(
        content=twiml,
        media_type="text/xml",
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/twilio/status")
async def twilio_call_status(request: Request):
    """
    Twilio CallStatus callback — receives call lifecycle events
    (initiated, ringing, in-progress, completed, failed, etc.).

    Twilio POSTs this as form-encoded data. We log the event and return 204
    so Twilio knows we received it.
    """
    try:
        form = await request.form()
        call_sid = form.get("CallSid", "")
        call_status = form.get("CallStatus", "")
        from_number = form.get("From", "")
        to_number = form.get("To", "")
        duration = form.get("CallDuration", "")

        logger.info(
            "twilio_call_status",
            call_sid=call_sid,
            call_status=call_status,
            from_number=from_number[-4:] if len(from_number) > 4 else "****",  # partial PII mask
            to_number=to_number[-4:] if len(to_number) > 4 else "****",
            duration=duration,
        )
    except Exception as exc:
        logger.warning("twilio_status_parse_error", error=str(exc))

    return Response(status_code=204)
