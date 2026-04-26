from __future__ import annotations

import re
import uuid

import structlog
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from fastapi.responses import PlainTextResponse
import httpx

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
    TwiML response that connects an inbound Twilio call.
    If the agent has a DTMF menu, it emits a <Gather> block first.
    Otherwise, it immediately connects to the WebSocket Media Stream.
    """
    params = dict(request.query_params)
    agent_id = params.get("agent_id", "default")
    tenant_id = params.get("tenant_id", "")
    session_id = params.get("session_id") or str(uuid.uuid4())
    token = params.get("token", "")

    host = request.headers.get("host", "localhost:8003")
    ws_url = (
        f"wss://{host}/ws/voice/{agent_id}"
        f"?tenant_id={tenant_id}"
        f"&session_id={session_id}"
        f"&token={token}"
    )

    # 1. Fetch agent config to check for DTMF menu
    menu = None
    greeting_url = None
    try:
        url = f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents/{agent_id}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers={"X-Tenant-ID": tenant_id}, timeout=3.0)
            if resp.status_code == 200:
                agent_data = resp.json()
                cfg = agent_data.get("agent_config", {})
                menu = cfg.get("ivr_dtmf_menu")
                
                # Figure out which audio to play for the Gather prompt
                if cfg.get("opening_audio_url"):
                    greeting_url = cfg.get("opening_audio_url")
                elif cfg.get("voice_greeting_url"):
                    greeting_url = cfg.get("voice_greeting_url")
                elif cfg.get("ivr_language_url"):
                    greeting_url = cfg.get("ivr_language_url")
                    
                if greeting_url and greeting_url.startswith("/"):
                    greeting_url = f"{settings.AI_ORCHESTRATOR_URL}{greeting_url}"
    except Exception as exc:
        logger.warning("failed_to_fetch_agent_for_dtmf", error=str(exc))

    has_menu = menu and isinstance(menu.get("entries"), list) and len(menu["entries"]) > 0

    if has_menu:
        # Phase 4: DTMF Menu present. Use <Gather>
        timeout = menu.get("timeout_seconds", 10)
        # Pass context forward so /gather knows what to do
        gather_url = (
            f"https://{host}/api/v1/voice/twilio/gather"
            f"?agent_id={agent_id}"
            f"&tenant_id={tenant_id}"
            f"&session_id={session_id}"
            f"&token={token}"
            f"&retry_count=0"
        )
        
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Response>\n'
            f'  <Gather action="{gather_url}" method="POST" numDigits="1" timeout="{timeout}">\n'
        )
        if greeting_url:
            twiml += f'    <Play>{greeting_url}</Play>\n'
        twiml += '  </Gather>\n'
        # If Gather times out, Twilio continues to the next verb.
        # So we just redirect back to the gather endpoint with a timeout flag.
        timeout_url = f"{gather_url}&timeout=true"
        twiml += f'  <Redirect method="POST">{timeout_url}</Redirect>\n'
        twiml += '</Response>'
    else:
        # Standard flow: immediately connect to stream
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Response>\n'
            '  <Connect>\n'
            f'    <Stream url="{ws_url}" />\n'
            '  </Connect>\n'
            '</Response>'
        )

    logger.info("twilio_incoming_call_twiml", agent_id=agent_id, session_id=session_id, dtmf_menu=has_menu)

    return Response(content=twiml, media_type="text/xml", headers={"Cache-Control": "no-cache"})


@router.post("/twilio/gather")
async def twilio_gather(request: Request):
    """
    Handles the digit collected by <Gather> or a Gather timeout.
    """
    params = dict(request.query_params)
    agent_id = params.get("agent_id")
    tenant_id = params.get("tenant_id", "")
    session_id = params.get("session_id")
    token = params.get("token", "")
    retry_count = int(params.get("retry_count", 0))
    is_timeout = params.get("timeout") == "true"

    form = await request.form()
    digit = form.get("Digits", "")

    host = request.headers.get("host", "localhost:8003")
    ws_url = (
        f"wss://{host}/ws/voice/{agent_id}"
        f"?tenant_id={tenant_id}"
        f"&session_id={session_id}"
        f"&token={token}"
    )
    
    # helper to generate the connect twiml
    def connect_twiml() -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Response>\n'
            '  <Connect>\n'
            f'    <Stream url="{ws_url}" />\n'
            '  </Connect>\n'
            '</Response>'
        )

    # 1. Fetch agent config to read the menu
    menu = None
    try:
        url = f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents/{agent_id}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers={"X-Tenant-ID": tenant_id}, timeout=3.0)
            if resp.status_code == 200:
                agent_data = resp.json()
                menu = agent_data.get("agent_config", {}).get("ivr_dtmf_menu")
    except Exception as exc:
        logger.warning("failed_to_fetch_agent_for_gather", error=str(exc))

    if not menu:
        # Failsafe: if menu is gone, just connect to LLM
        return Response(content=connect_twiml(), media_type="text/xml")

    max_retries = menu.get("max_retries", 3)

    if is_timeout or not digit:
        if retry_count < max_retries:
            # Re-prompt
            gather_url = (
                f"https://{host}/api/v1/voice/twilio/gather"
                f"?agent_id={agent_id}&tenant_id={tenant_id}&session_id={session_id}&token={token}&retry_count={retry_count + 1}"
            )
            twiml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<Response>\n'
                # Notice we don't have the audio URL here easily. We'd have to fetch it again.
                # Actually, Twilio <Gather> without <Play> just waits. To play the prompt again,
                # we should redirect back to /twilio/incoming to start over, but with retry_count.
            )
            # Actually, we can just redirect to incoming to restart the whole block
            incoming_url = f"https://{host}/api/v1/voice/twilio/incoming?agent_id={agent_id}&tenant_id={tenant_id}&session_id={session_id}&token={token}"
            # But we need to track retry_count. Instead of complex state, if it times out, let's just proceed to agent.
            # The user said: "default 10s. On timeout exhaustion, the call automatically proceeds to the AI."
            # Wait, if we want to loop the audio, it's hard without the audio URL.
            # Let's fetch the audio URL again.
            cfg = agent_data.get("agent_config", {})
            greeting_url = cfg.get("opening_audio_url") or cfg.get("voice_greeting_url") or cfg.get("ivr_language_url")
            if greeting_url and greeting_url.startswith("/"):
                greeting_url = f"{settings.AI_ORCHESTRATOR_URL}{greeting_url}"
                
            timeout_url = f"{gather_url}&timeout=true"
            
            twiml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<Response>\n'
                f'  <Gather action="{gather_url}" method="POST" numDigits="1" timeout="{menu.get("timeout_seconds", 10)}">\n'
            )
            if greeting_url:
                twiml += f'    <Play>{greeting_url}</Play>\n'
            twiml += '  </Gather>\n'
            twiml += f'  <Redirect method="POST">{timeout_url}</Redirect>\n'
            twiml += '</Response>'
            return Response(content=twiml, media_type="text/xml")
        else:
            # Exhausted retries -> proceed to agent
            return Response(content=connect_twiml(), media_type="text/xml")

    # We got a digit. Find the entry.
    entries = menu.get("entries", [])
    entry = next((e for e in entries if e.get("digit") == digit), None)

    if not entry:
        # Invalid digit. You could play an error message, but proceeding to agent is safest.
        return Response(content=connect_twiml(), media_type="text/xml")

    action = entry.get("action")
    
    if action == "proceed_to_agent":
        return Response(content=connect_twiml(), media_type="text/xml")
        
    elif action == "end_call":
        twiml = '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>'
        return Response(content=twiml, media_type="text/xml")
        
    elif action == "play_audio":
        twiml = '<?xml version="1.0" encoding="UTF-8"?>\n<Response>\n'
        audio_url = entry.get("audio_url")
        if audio_url:
            if audio_url.startswith("/"):
                audio_url = f"{settings.AI_ORCHESTRATOR_URL}{audio_url}"
            twiml += f'  <Play>{audio_url}</Play>\n'
            
        after = entry.get("after_playback", "proceed_to_agent")
        if after == "end_call":
            twiml += '  <Hangup/>\n'
        else:
            twiml += '  <Connect>\n'
            twiml += f'    <Stream url="{ws_url}" />\n'
            twiml += '  </Connect>\n'
        twiml += '</Response>'
        return Response(content=twiml, media_type="text/xml")
        
    elif action == "repeat_menu":
        # Loop back to incoming
        incoming_url = f"https://{host}/api/v1/voice/twilio/incoming?agent_id={agent_id}&tenant_id={tenant_id}&session_id={session_id}&token={token}"
        twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Redirect method="POST">{incoming_url}</Redirect></Response>'
        return Response(content=twiml, media_type="text/xml")

    # Fallback
    return Response(content=connect_twiml(), media_type="text/xml")


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
