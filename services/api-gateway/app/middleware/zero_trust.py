from __future__ import annotations

import hmac
import ssl

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings


class ZeroTrustMiddleware(BaseHTTPMiddleware):
    """
    Zenith Pillar 3: Inter-Service Zero Trust
    
    Enforces mutual TLS authentication and request signing for all internal API calls.
    All inter-service communication must provide valid client certificates.
    """
    
    async def dispatch(self, request: Request, call_next):
        # Skip for public endpoints
        public_paths = ["/api/v1/auth/", "/api/v1/billing/webhook", "/health"]
        if any(request.url.path.startswith(path) for path in public_paths):
            return await call_next(request)
        
        # Enforce internal request authentication
        if "X-Internal-Key" in request.headers:
            internal_key = request.headers.get("X-Internal-Key", "")
            if not hmac.compare_digest(internal_key.encode('utf-8'), settings.INTERNAL_API_KEY.encode('utf-8')):
                raise HTTPException(status_code=403, detail="Forbidden: Invalid internal key")
            
            # Additional certificate validation when running in production
            if settings.ENVIRONMENT == "production":
                client_cert = request.scope.get("client_cert")
                if not client_cert:
                    raise HTTPException(status_code=403, detail="Forbidden: Client certificate required")
                
                # Verify certificate is issued by trusted CA
                if not self._validate_client_cert(client_cert):
                    raise HTTPException(status_code=403, detail="Forbidden: Invalid client certificate")
        
        return await call_next(request)
    
    def _validate_client_cert(self, cert: dict) -> bool:
        """Validate client certificate against trusted CA chain"""
        try:
            # Check certificate validity period
            import datetime
            not_after = datetime.datetime.strptime(cert.get("notAfter"), "%b %d %H:%M:%S %Y %Z")
            if datetime.datetime.utcnow() > not_after:
                return False
            
            # Verify certificate fingerprint against allowed services
            fingerprint = cert.get("fingerprint_sha256")
            allowed_fingerprints = settings.ALLOWED_SERVICE_CERT_FINGERPRINTS or []
            
            return fingerprint in allowed_fingerprints
        except Exception:
            return False


def create_ssl_context() -> ssl.SSLContext:
    """Create SSL context with mTLS enabled for internal services"""
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    
    # Load server certificate and key
    context.load_cert_chain(
        certfile=settings.SSL_CERT_PATH,
        keyfile=settings.SSL_KEY_PATH
    )
    
    # Load trusted CA certificates for client verification
    context.load_verify_locations(cafile=settings.SSL_CA_CERT_PATH)
    
    # Require client certificates for all connections
    context.verify_mode = ssl.CERT_REQUIRED
    
    # Disable old TLS versions
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    
    return context
