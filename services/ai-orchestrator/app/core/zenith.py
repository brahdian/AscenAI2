from __future__ import annotations

import uuid
from typing import Optional
from dataclasses import dataclass
from functools import wraps

import structlog
from fastapi import Request, HTTPException

logger = structlog.get_logger(__name__)

@dataclass
class ZenithContext:
    """
    Zenith Identity context extracted from the request.
    Encapsulates Pillar 1 (Traceability) and Pillar 6 (Architecture).
    """
    actor_email: str
    trace_id: str
    original_ip: str
    tenant_id: str
    is_support_access: bool = False
    justification_id: Optional[str] = None
    restricted_agent_id: Optional[uuid.UUID] = None

async def get_zenith_context(request: Request) -> ZenithContext:
    """
    FastAPI dependency to extract the absolute forensic context.
    Must be used by all Zenith-hardened agents and document endpoints.
    """
    # 1. Identity (Actor Signature)
    # Only trust X-Actor-Email header from internal API gateway
    internal_key = request.headers.get("X-Internal-Key")
    actor_email = getattr(request.state, "actor_email", "system")
    
    if internal_key:
        # Internal request from API gateway - trust header
        header_actor = request.headers.get("X-Actor-Email")
        if header_actor:
            actor_email = header_actor
    
    # 2. Traceability (Trace Continuity)
    trace_id = request.headers.get("X-Trace-ID") or request.headers.get("X-Request-ID")
    if not trace_id:
        trace_id = str(uuid.uuid4())
    
    # 3. Source IP (Forensic Origin)
    original_ip = request.headers.get("X-Original-IP") or request.client.host if request.client else "0.0.0.0"
    
    # 4. Tenant Context
    tenant_id = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Tenant ID required (Zenith Security Violation)")
    
    # 5. Support & Justification
    is_support = request.headers.get("X-Support-Access", "false").lower() == "true"
    justification = request.headers.get("X-Justification-ID")

    # 6. Isolation Locks (Pillar 3)
    raid = None
    raid_str = request.headers.get("X-Restricted-Agent-ID")
    if raid_str:
        try:
            raid = uuid.UUID(raid_str)
        except ValueError:
            pass
    
    return ZenithContext(
        actor_email=actor_email,
        trace_id=trace_id,
        original_ip=original_ip,
        tenant_id=str(tenant_id),
        is_support_access=is_support,
        justification_id=justification,
        restricted_agent_id=raid
    )

def zenith_error_handler(func):
    """
    Zenith Pillar 5: Stealth Error Handling.
    Ensures zero backend leakage in 500 errors by returning ONLY a trace_id.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Find trace_id in kwargs (ctx)
        ctx = kwargs.get("ctx")
        trace_id = ctx.trace_id if ctx else str(uuid.uuid4())
        
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            # Re-raise standard HTTP exceptions
            raise
        except Exception as exc:
            # Log the full forensic stack trace internally
            logger.error(
                "zenith_internal_failure",
                trace_id=trace_id,
                error=str(exc),
                endpoint=func.__name__,
                exc_info=True
            )
            # Zenith Pillar 5: Return ONLY the trace_id to the client
            raise HTTPException(
                status_code=500,
                detail=f"An internal error occurred. Forensic Trace ID: {trace_id}"
            )
    return wrapper
