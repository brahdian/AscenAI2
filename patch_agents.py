import re
from pathlib import Path

file_path = "/Users/visvasis/Home/Jamvant/AscenAI/services/ai-orchestrator/app/api/v1/agents.py"
with open(file_path, "r") as f:
    content = f.read()

header_addition = """
from app.services.pii_service import redact

def _has_variables(text: str | None) -> bool:
    if not text:
        return False
    return bool(re.search(r'\\$\\[vars:\\w+\\]|\\$vars:\\w+', text))

def _delete_old_audio(url: str | None) -> None:
    if not url:
        return
    try:
        from pathlib import Path
        import os
        audio_dir = Path(os.environ.get("GREETING_AUDIO_PATH", "/tmp/voice-greetings"))
        filename = Path(url).name
        filepath = audio_dir / filename
        if filepath.exists():
            filepath.unlink(missing_ok=True)
            import structlog
            structlog.get_logger(__name__).info("deleted_old_audio", filepath=str(filepath))
    except Exception as e:
        import structlog
        structlog.get_logger(__name__).warning("failed_to_delete_old_audio", url=url, error=str(e))

"""

content = content.replace("from app.core.database import get_db", header_addition + "from app.core.database import get_db")

# create_agent greeting
greeting_create_old = """        greeting_text = cfg.get("greeting_message")
        if greeting_text and not cfg.get("voice_greeting_url"):
            url = await _tts_service.generate_greeting(
                text=greeting_text,
                voice_id=voice_id,
                agent_id=str(agent.id),
            )
            if url:
                new_cfg = dict(agent.agent_config)
                new_cfg["voice_greeting_url"] = url
                agent.agent_config = new_cfg
                tts_updated = True
                logger.info("voice_greeting_generated", agent_id=str(agent.id), url=url)"""

greeting_create_new = """        greeting_text = cfg.get("greeting_message")
        if greeting_text and not cfg.get("voice_greeting_url"):
            _validate_system_prompt(greeting_text)
            if not _has_variables(greeting_text):
                redacted_text = redact(greeting_text)
                url = await _tts_service.generate_greeting(
                    text=redacted_text,
                    voice_id=voice_id,
                    agent_id=str(agent.id),
                )
                if url:
                    new_cfg = dict(agent.agent_config)
                    new_cfg["voice_greeting_url"] = url
                    agent.agent_config = new_cfg
                    tts_updated = True
                    logger.info("voice_greeting_generated", agent_id=str(agent.id), url=url)"""
content = content.replace(greeting_create_old, greeting_create_new)

# create_agent ivr
ivr_create_old = """        ivr_text = cfg.get("ivr_language_prompt")
        if ivr_text and not cfg.get("ivr_language_url"):
            url = await _tts_service.generate_ivr_prompt(
                text=ivr_text,
                voice_id=voice_id,
                agent_id=str(agent.id),
            )
            if url:
                new_cfg = dict(agent.agent_config)
                new_cfg["ivr_language_url"] = url
                agent.agent_config = new_cfg
                tts_updated = True
                logger.info("ivr_prompt_generated", agent_id=str(agent.id), url=url)"""

ivr_create_new = """        ivr_text = cfg.get("ivr_language_prompt")
        if ivr_text and not cfg.get("ivr_language_url"):
            if not _has_variables(ivr_text):
                redacted_ivr = redact(ivr_text)
                url = await _tts_service.generate_ivr_prompt(
                    text=redacted_ivr,
                    voice_id=voice_id,
                    agent_id=str(agent.id),
                )
                if url:
                    new_cfg = dict(agent.agent_config)
                    new_cfg["ivr_language_url"] = url
                    agent.agent_config = new_cfg
                    tts_updated = True
                    logger.info("ivr_prompt_generated", agent_id=str(agent.id), url=url)"""
content = content.replace(ivr_create_old, ivr_create_new)

# create_agent opening
opening_create_old = """            if opening_text:
                url = await _tts_service.generate_opening(
                    text=opening_text,
                    voice_id=voice_id,
                    agent_id=str(agent.id),
                )
                if url:
                    new_cfg = dict(agent.agent_config)
                    new_cfg["opening_audio_url"] = url
                    agent.agent_config = new_cfg
                    await db.commit()
                    await db.refresh(agent)
                    logger.info("voice_opening_generated", agent_id=str(agent.id), url=url)"""

opening_create_new = """            if opening_text:
                if not _has_variables(opening_text):
                    redacted_opening = redact(opening_text)
                    url = await _tts_service.generate_opening(
                        text=redacted_opening,
                        voice_id=voice_id,
                        agent_id=str(agent.id),
                    )
                    if url:
                        new_cfg = dict(agent.agent_config)
                        new_cfg["opening_audio_url"] = url
                        agent.agent_config = new_cfg
                        await db.commit()
                        await db.refresh(agent)
                        logger.info("voice_opening_generated", agent_id=str(agent.id), url=url)"""
content = content.replace(opening_create_old, opening_create_new)

# update_agent greeting
greeting_update_old = """            greeting_text = cfg.get("greeting_message")
            if greeting_text:
                # Resolve variables before generating audio
                result_vars = await db.execute(select(AgentVariable).where(AgentVariable.agent_id == agent.id))
                variables = result_vars.scalars().all()
                resolved_greeting = resolve_agent_variables(greeting_text, agent, variables, clean=True)

                url = await _tts_service.generate_greeting(
                    text=resolved_greeting,
                    voice_id=voice_id,
                    agent_id=str(agent.id),
                )
                if url:
                    new_cfg = dict(agent.agent_config)
                    new_cfg["voice_greeting_url"] = url
                    agent.agent_config = new_cfg
                    tts_updated = True
                    logger.info("voice_greeting_regenerated", agent_id=str(agent.id), url=url)"""

greeting_update_new = """            greeting_text = cfg.get("greeting_message")
            if greeting_text:
                _validate_system_prompt(greeting_text)
                if not _has_variables(greeting_text):
                    # Resolve variables before generating audio
                    result_vars = await db.execute(select(AgentVariable).where(AgentVariable.agent_id == agent.id))
                    variables = result_vars.scalars().all()
                    resolved_greeting = resolve_agent_variables(greeting_text, agent, variables, clean=True)
                    redacted_text = redact(resolved_greeting)
                    
                    old_url = agent.agent_config.get("voice_greeting_url")
                    url = await _tts_service.generate_greeting(
                        text=redacted_text,
                        voice_id=voice_id,
                        agent_id=str(agent.id),
                    )
                    if url:
                        _delete_old_audio(old_url)
                        new_cfg = dict(agent.agent_config)
                        new_cfg["voice_greeting_url"] = url
                        agent.agent_config = new_cfg
                        tts_updated = True
                        logger.info("voice_greeting_regenerated", agent_id=str(agent.id), url=url)
                else:
                    old_url = agent.agent_config.get("voice_greeting_url")
                    if old_url:
                        _delete_old_audio(old_url)
                        new_cfg = dict(agent.agent_config)
                        new_cfg.pop("voice_greeting_url", None)
                        agent.agent_config = new_cfg
                        tts_updated = True
                        logger.info("voice_greeting_cleared", agent_id=str(agent.id))"""
content = content.replace(greeting_update_old, greeting_update_new)

# update_agent ivr
ivr_update_old = """            ivr_text = cfg.get("ivr_language_prompt")
            if ivr_text:
                # Resolve variables before generating IVR audio (though IVR usually doesn't have them)
                result_vars = await db.execute(select(AgentVariable).where(AgentVariable.agent_id == agent.id))
                variables = result_vars.scalars().all()
                resolved_ivr = resolve_agent_variables(ivr_text, agent, variables, clean=True)

                url = await _tts_service.generate_ivr_prompt(
                    text=resolved_ivr,
                    voice_id=voice_id,
                    agent_id=str(agent.id),
                )
                if url:
                    new_cfg = dict(agent.agent_config)
                    new_cfg["ivr_language_url"] = url
                    agent.agent_config = new_cfg
                    tts_updated = True
                    logger.info("ivr_prompt_regenerated", agent_id=str(agent.id), url=url)"""

ivr_update_new = """            ivr_text = cfg.get("ivr_language_prompt")
            if ivr_text:
                if not _has_variables(ivr_text):
                    # Resolve variables before generating IVR audio
                    result_vars = await db.execute(select(AgentVariable).where(AgentVariable.agent_id == agent.id))
                    variables = result_vars.scalars().all()
                    resolved_ivr = resolve_agent_variables(ivr_text, agent, variables, clean=True)
                    redacted_ivr = redact(resolved_ivr)
                    
                    old_url = agent.agent_config.get("ivr_language_url")
                    url = await _tts_service.generate_ivr_prompt(
                        text=redacted_ivr,
                        voice_id=voice_id,
                        agent_id=str(agent.id),
                    )
                    if url:
                        _delete_old_audio(old_url)
                        new_cfg = dict(agent.agent_config)
                        new_cfg["ivr_language_url"] = url
                        agent.agent_config = new_cfg
                        tts_updated = True
                        logger.info("ivr_prompt_regenerated", agent_id=str(agent.id), url=url)
                else:
                    old_url = agent.agent_config.get("ivr_language_url")
                    if old_url:
                        _delete_old_audio(old_url)
                        new_cfg = dict(agent.agent_config)
                        new_cfg.pop("ivr_language_url", None)
                        agent.agent_config = new_cfg
                        tts_updated = True
                        logger.info("ivr_prompt_cleared", agent_id=str(agent.id))"""
content = content.replace(ivr_update_old, ivr_update_new)

# update_agent opening
opening_update_old = """            if opening_text:
                # Resolve variables in mandatory opening
                result_vars = await db.execute(select(AgentVariable).where(AgentVariable.agent_id == agent.id))
                variables = result_vars.scalars().all()
                resolved_opening = resolve_agent_variables(opening_text, agent, variables, clean=True)

                url = await _tts_service.generate_opening(
                    text=resolved_opening,
                    voice_id=voice_id,
                    agent_id=str(agent.id),
                )
                if url:
                    new_cfg = dict(agent.agent_config)
                    new_cfg["opening_audio_url"] = url
                    agent.agent_config = new_cfg
                    tts_updated = True
                    logger.info("voice_opening_regenerated", agent_id=str(agent.id), url=url)"""

opening_update_new = """            if opening_text:
                if not _has_variables(opening_text):
                    # Resolve variables in mandatory opening
                    result_vars = await db.execute(select(AgentVariable).where(AgentVariable.agent_id == agent.id))
                    variables = result_vars.scalars().all()
                    resolved_opening = resolve_agent_variables(opening_text, agent, variables, clean=True)
                    redacted_opening = redact(resolved_opening)
                    
                    old_url = agent.agent_config.get("opening_audio_url")
                    url = await _tts_service.generate_opening(
                        text=redacted_opening,
                        voice_id=voice_id,
                        agent_id=str(agent.id),
                    )
                    if url:
                        _delete_old_audio(old_url)
                        new_cfg = dict(agent.agent_config)
                        new_cfg["opening_audio_url"] = url
                        agent.agent_config = new_cfg
                        tts_updated = True
                        logger.info("voice_opening_regenerated", agent_id=str(agent.id), url=url)
                else:
                    old_url = agent.agent_config.get("opening_audio_url")
                    if old_url:
                        _delete_old_audio(old_url)
                        new_cfg = dict(agent.agent_config)
                        new_cfg.pop("opening_audio_url", None)
                        agent.agent_config = new_cfg
                        tts_updated = True
                        logger.info("voice_opening_cleared", agent_id=str(agent.id))"""
content = content.replace(opening_update_old, opening_update_new)

# generate greeting manual
manual_greeting_old = """    # Resolve variables for audio
    result_vars = await db.execute(select(AgentVariable).where(AgentVariable.agent_id == agent.id))
    variables = result_vars.scalars().all()
    resolved_text = resolve_agent_variables(greeting_text, agent, variables, clean=True)

    url = await _tts_service.generate_greeting(
        text=resolved_text,
        voice_id=voice_id,
        agent_id=str(agent.id),
    )
    if not url:
        raise HTTPException(status_code=500, detail="TTS generation failed.")

    new_cfg = dict(agent.agent_config)
    new_cfg["voice_greeting_url"] = url"""

manual_greeting_new = """    _validate_system_prompt(greeting_text)
    
    if _has_variables(greeting_text):
        raise HTTPException(status_code=400, detail="Cannot manually generate audio for a greeting with session variables.")

    # Resolve variables for audio
    result_vars = await db.execute(select(AgentVariable).where(AgentVariable.agent_id == agent.id))
    variables = result_vars.scalars().all()
    resolved_text = resolve_agent_variables(greeting_text, agent, variables, clean=True)
    redacted_text = redact(resolved_text)

    old_url = agent.agent_config.get("voice_greeting_url")
    url = await _tts_service.generate_greeting(
        text=redacted_text,
        voice_id=voice_id,
        agent_id=str(agent.id),
    )
    if not url:
        raise HTTPException(status_code=500, detail="TTS generation failed.")
        
    _delete_old_audio(old_url)

    new_cfg = dict(agent.agent_config)
    new_cfg["voice_greeting_url"] = url"""
content = content.replace(manual_greeting_old, manual_greeting_new)

# generate ivr manual
manual_ivr_old = """    # Resolve variables for audio
    result_vars = await db.execute(select(AgentVariable).where(AgentVariable.agent_id == agent.id))
    variables = result_vars.scalars().all()
    resolved_text = resolve_agent_variables(ivr_text, agent, variables, clean=True)

    url = await _tts_service.generate_ivr_prompt(
        text=resolved_text,
        voice_id=voice_id,
        agent_id=str(agent.id),
    )
    if not url:
        raise HTTPException(status_code=500, detail="TTS generation failed.")

    new_cfg = dict(agent.agent_config)
    new_cfg["ivr_language_url"] = url"""

manual_ivr_new = """    if _has_variables(ivr_text):
        raise HTTPException(status_code=400, detail="Cannot manually generate audio for an IVR prompt with session variables.")

    # Resolve variables for audio
    result_vars = await db.execute(select(AgentVariable).where(AgentVariable.agent_id == agent.id))
    variables = result_vars.scalars().all()
    resolved_text = resolve_agent_variables(ivr_text, agent, variables, clean=True)
    redacted_text = redact(resolved_text)

    old_url = agent.agent_config.get("ivr_language_url")
    url = await _tts_service.generate_ivr_prompt(
        text=redacted_text,
        voice_id=voice_id,
        agent_id=str(agent.id),
    )
    if not url:
        raise HTTPException(status_code=500, detail="TTS generation failed.")
        
    _delete_old_audio(old_url)

    new_cfg = dict(agent.agent_config)
    new_cfg["ivr_language_url"] = url"""
content = content.replace(manual_ivr_old, manual_ivr_new)

with open(file_path, "w") as f:
    f.write(content)
print("done")
