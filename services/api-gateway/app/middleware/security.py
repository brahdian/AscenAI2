from __future__ import annotations

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings

logger = structlog.get_logger(__name__)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Enforces infrastructure-level security headers for compliance.
    Required by SOC2/HIPAA: Clickjacking, MIME-sniffing, and HSTS.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        
        # 1. Anti-Clickjacking (SOC2 CC6.1)
        response.headers["X-Frame-Options"] = "DENY"
        
        # 2. Prevent MIME-sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # 3. Secure Transport (HSTS) - Only in production (SOC2 CC6.7)
        # Added 'preload' for Enterprise 100% readiness.
        if settings.ENVIRONMENT == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        
        # 4. Referral Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # 5. Content Security Policy (Hardened for Production)
        # Includes connect-src and img-src constraints.
        import secrets
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce
        
        csp_parts = [
            "default-src 'self'",
            "connect-src 'self' *.ascenai.com",
            "img-src 'self' data: *.ascenai.com",
            f"script-src 'self' 'nonce-{nonce}'",
            "style-src 'self' 'unsafe-inline'",  # Safe for React SSR
            "frame-ancestors 'none'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_parts)
        
        # 6. Permissions Policy (Disable dangerous browser features)
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        
        return response
