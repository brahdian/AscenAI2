from __future__ import annotations

import time

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_tenant_db
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ResendOTPRequest,
    ResetPasswordRequest,
    SubscribeRequest,
    SubscribeResponse,
    TokenResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.services.auth_service import auth_service

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth")

# ---------------------------------------------------------------------------
# Per-endpoint rate limiting (tighter than the global middleware limit)
# ---------------------------------------------------------------------------

async def _auth_rate_limit(request: Request, action: str, limit: int, window: int) -> None:
    """
    Enforce a per-IP + per-action sliding-window rate limit for sensitive auth
    endpoints.  Raises HTTP 429 when the limit is exceeded.

    :param action:  Unique key for this endpoint (e.g. "login", "otp_verify")
    :param limit:   Max requests allowed per *window* seconds
    :param window:  Window duration in seconds
    """
    redis = getattr(request.app.state, "redis", None)
    if not redis:
        return  # Fail-open if Redis is unavailable (global middleware still applies)

    client_ip = request.client.host if request.client else "unknown"
    bucket = f"auth_rl:{action}:{client_ip}:{int(time.time()) // window}"
    try:
        _lua = """
local c = redis.call('INCR', KEYS[1])
if c == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return c
"""
        count = await redis.eval(_lua, 1, bucket, window * 2)
        if count > limit:
            retry_after = window - (int(time.time()) % window)
            logger.warning(
                "auth_rate_limit_exceeded",
                action=action,
                ip=client_ip,
                count=count,
            )
            raise HTTPException(
                status_code=429,
                detail=f"Too many {action} attempts. Please wait before trying again.",
                headers={"Retry-After": str(retry_after)},
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("auth_rate_limit_redis_error", error=str(exc))

# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

# Removed module-level _IS_SECURE to evaluate it dynamically against current settings


def _set_auth_cookies(response: Response, tokens: TokenResponse, request: Request) -> None:
    """
    Write access_token and refresh_token as HttpOnly cookies.
    """
    # For local lvh.me or localhost DEVELOPMENT (over HTTP), we MUST set secure=False.
    # Otherwise browsers reject the cookie if samesite="none" or if we specify secure=True on http.
    # We use SameSite=Lax for same-registrable-domain (lvh.me) which is safer and works on subdomains.
    
    hostname = request.url.hostname or ""
    is_local = "localhost" in hostname or "lvh.me" in hostname or "127.0.0.1" in hostname or "[::1]" in hostname or "::1" == hostname
    
    # Default to production-grade security
    is_secure = True
    samesite = "lax"
    
    # Dev-friendly settings for local development
    if is_local:
        is_secure = False
        samesite = "lax"
    
    # Determine domain: Omit for localhost if DYNAMIC_COOKIE_DOMAIN is enabled
    # This allows browser to associate cookie with exactly 'localhost' during dev
    domain = settings.COOKIE_DOMAIN
    if settings.DYNAMIC_COOKIE_DOMAIN and ("localhost" in hostname or "127.0.0.1" in hostname or "[::1]" in hostname or "::1" == hostname):
        domain = None
    
    base = dict(
        httponly=True,
        secure=is_secure,
        samesite=samesite,
        domain=domain,
    )
    response.set_cookie(
        key="access_token",
        value=tokens.access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        **base,
    )
    response.set_cookie(
        key="refresh_token",
        value=tokens.refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        path="/api/v1/auth",   # only sent to auth endpoints
        **base,
    )


def _clear_auth_cookies(response: Response) -> None:
    # Clear with explicit domain
    response.delete_cookie("access_token", path="/", domain=settings.COOKIE_DOMAIN)
    response.delete_cookie("refresh_token", path="/api/v1/auth", domain=settings.COOKIE_DOMAIN)
    # Clear without domain (for localhost/host-only cookies)
    response.delete_cookie("access_token", path="/", domain=None)
    response.delete_cookie("refresh_token", path="/api/v1/auth", domain=None)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(
    request: RegisterRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Register a new tenant + owner user and send verification OTP."""
    await _auth_rate_limit(http_request, "register", limit=5, window=3600)  # 5/hr per IP
    redis = getattr(http_request.app.state, "redis", None)
    return await auth_service.register(request, db, redis)


@router.post("/verify-email", response_model=VerifyEmailResponse)
async def verify_email(
    request: VerifyEmailRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Verify email with OTP. Returns payment-required response."""
    await _auth_rate_limit(http_request, "otp_verify", limit=10, window=60)  # 10/min per IP
    redis = getattr(http_request.app.state, "redis", None)
    return await auth_service.verify_email(request.email, request.otp, db, redis)


@router.post("/resend-otp", status_code=202)
async def resend_otp(
    request: ResendOTPRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Resend a new verification OTP."""
    await _auth_rate_limit(http_request, "otp_resend", limit=3, window=60)  # 3/min per IP
    redis = getattr(http_request.app.state, "redis", None)
    await auth_service.resend_otp(request.email, db, redis)
    return {"detail": "New verification code sent."}


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    response: Response,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate and return JWT tokens (+ set HttpOnly cookies)."""
    await _auth_rate_limit(http_request, "login", limit=10, window=60)  # 10/min per IP
    redis = getattr(http_request.app.state, "redis", None)
    from app.services.audit_service import audit_log
    try:
        tokens = await auth_service.login(request, db, redis)
        await audit_log(
            db, "auth.login_success",
            request=http_request,
            actor_email=request.email.lower(),
            category="auth",
            details={"email": request.email.lower()},
        )
        _set_auth_cookies(response, tokens, http_request)
        return tokens
    except Exception:
        await audit_log(
            db, "auth.login_failed",
            request=http_request,
            actor_email=request.email.lower(),
            category="auth",
            status="failure",
            details={"email": request.email.lower()},
        )
        raise


@router.post("/subscribe", response_model=SubscribeResponse)
async def subscribe(
    request: SubscribeRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Checkout session for the given plan."""
    from fastapi import HTTPException
    from sqlalchemy import select

    from app.models.tenant import Tenant
    from app.models.user import User
    from app.services.billing_service import BillingService
    
    # Resolve user by email. Use ordered first() to handle multi-tenant membership
    # without crashing on MultipleResultsFound.
    user_res = await db.execute(
        select(User)
        .where(User.email == request.email.lower())
        .order_by(User.created_at.asc())
    )
    user = user_res.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    tenant_res = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = tenant_res.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    redis = getattr(http_request.app.state, "redis", None)
    billing_service = BillingService(db, redis)
    
    session_data = await billing_service.create_tenant_subscription_session(
        tenant=tenant,
        owner=user,
        plan=request.plan
    )
    return session_data


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    http_request: Request,
    response: Response,
    body: RefreshRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Refresh access token.
    Accepts the refresh token from:
      1. The HttpOnly 'refresh_token' cookie (preferred — browser flow)
      2. The JSON request body (SDK / programmatic flow)
    """
    # Prefer cookie; fall back to body
    token = http_request.cookies.get("refresh_token")
    if not token and body:
        token = body.refresh_token
    if not token:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Refresh token required.")
    
    redis = getattr(http_request.app.state, "redis", None)
    tokens = await auth_service.refresh_token(token, db, redis)
    _set_auth_cookies(response, tokens, http_request)
    return tokens


@router.get("/me")
async def get_me(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Get current user and tenant info (used for cross-subdomain auth sync)."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    import uuid

    from app.models.tenant import Tenant
    from app.models.user import User
    
    user_res = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = user_res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
        
    tenant_res = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = tenant_res.scalar_one_or_none()
    
    return {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
        },
        "tenant_id": str(user.tenant_id),
        "tenant_name": tenant.name if tenant else "Default"
    }


@router.patch("/me", status_code=200)
async def update_me(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Update the current user's profile (full_name)."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    import uuid

    from app.models.user import User

    try:
        body = await request.json()
        user_res = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
        user = user_res.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if "full_name" in body:
            full_name = str(body["full_name"]).strip()
            if not full_name:
                raise HTTPException(status_code=422, detail="full_name cannot be empty")
            user.full_name = full_name

        await db.commit()
        return {"detail": "Profile updated", "full_name": user.full_name}
    except HTTPException:
        raise
    except Exception as e:
        trace_id = structlog.contextvars.get_contextvars().get("trace_id", "unknown")
        logger.error("update_me_internal_error", error=str(e), trace_id=trace_id)
        raise HTTPException(status_code=500, detail=f"Internal server error. Trace ID: {trace_id}")


@router.delete("/me", status_code=204)
async def delete_me(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Delete the current user's account (GDPR right to be forgotten)."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        redis = getattr(request.app.state, "redis", None)
        await auth_service.delete_account(user_id, db, redis)
        
        _clear_auth_cookies(response)
    except HTTPException:
        raise
    except Exception as e:
        trace_id = structlog.contextvars.get_contextvars().get("trace_id", "unknown")
        logger.error("delete_me_internal_error", error=str(e), trace_id=trace_id)
        raise HTTPException(status_code=500, detail=f"Internal server error. Trace ID: {trace_id}")


@router.post("/change-password", status_code=200)
async def change_password(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Change password for the authenticated user."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    import uuid

    from app.models.user import User
    from app.services.audit_service import audit_log

    try:
        body = await request.json()
        current_password = body.get("current_password", "")
        new_password = body.get("new_password", "")

        if not current_password or not new_password:
            raise HTTPException(status_code=422, detail="current_password and new_password are required")
        
        import re
        if len(new_password) < 8 or not re.match(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).+$", new_password):
            raise HTTPException(status_code=422, detail="new_password must be at least 8 characters with at least one uppercase, lowercase, and number")

        user_res = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
        user = user_res.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if not auth_service.verify_password(current_password, user.hashed_password):
            await audit_log(
                db, "auth.password_change_failed",
                request=request,
                actor_user_id=user_id,
                actor_email=user.email,
                category="security",
                status="failure",
                details={"reason": "invalid_current_password"},
            )
            raise HTTPException(status_code=400, detail="Current password is incorrect")

        user.hashed_password = auth_service.hash_password(new_password)
        user.session_version += 1 # Invalidate all current tokens
        await db.commit()
        
        await audit_log(
            db, "auth.password_changed",
            request=request,
            actor_user_id=user_id,
            actor_email=user.email,
            category="security",
            details={"session_version": user.session_version},
        )

        # Invalidate JWT cache to prevent using old tokens on password change
        redis = getattr(request.app.state, "redis", None)
        if redis:
            try:
                pattern = f"auth:jwt:{user.id}:*"
                async for cache_key in redis.scan_iter(match=pattern, count=100):
                    await redis.delete(cache_key)
                logger.info("jwt_cache_invalidated_after_password_change", user_id=str(user.id))
            except Exception as exc:
                logger.warning("jwt_cache_invalidation_failed", error=str(exc))

        return {"detail": "Password changed successfully. All sessions invalidated."}
    except HTTPException:
        raise
    except Exception as e:
        trace_id = structlog.contextvars.get_contextvars().get("trace_id", "unknown")
        logger.error("change_password_internal_error", error=str(e), trace_id=trace_id)
        raise HTTPException(status_code=500, detail=f"Internal server error. Trace ID: {trace_id}")

@router.post("/logout", status_code=204)
async def logout(response: Response):
    """Clear auth cookies (browser logout)."""
    _clear_auth_cookies(response)


@router.post("/forgot-password", status_code=202)
async def forgot_password(
    http_request: Request,
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a password-reset token stored in Redis (1-hour TTL) and send an email.
    Always returns 202 regardless of whether the email exists — prevents enumeration.
    """
    await _auth_rate_limit(http_request, "forgot_password", limit=3, window=3600)  # 3/hr per IP
    
    from app.services.audit_service import audit_log
    await audit_log(
        db, "auth.forgot_password_requested",
        request=http_request,
        category="security",
        details={"email_hash": str(hash(body.email.lower()))},
    )
    
    redis = getattr(http_request.app.state, "redis", None)
    await auth_service.request_password_reset(body.email, db, redis)
    return {"detail": "If that email exists, a reset link has been sent."}


@router.post("/reset-password", status_code=200)
async def reset_password(
    http_request: Request,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reset password using a valid reset token (one-time, 1-hour TTL)."""
    from app.services.audit_service import audit_log
    try:
        redis = getattr(http_request.app.state, "redis", None)
        await auth_service.reset_password(body.token, body.new_password, db, redis)
        
        await audit_log(
            db, "auth.password_reset_success",
            request=http_request,
            category="security",
        )
        
        return {"detail": "Password reset successfully. All sessions invalidated."}
    except HTTPException:
        raise
    except Exception as e:
        trace_id = structlog.contextvars.get_contextvars().get("trace_id", "unknown")
        logger.error("reset_password_internal_error", error=str(e), trace_id=trace_id)
        raise HTTPException(status_code=500, detail=f"Internal server error. Trace ID: {trace_id}")
