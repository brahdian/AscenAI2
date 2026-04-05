from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
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
    UserInfo,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.services.auth_service import auth_service

router = APIRouter(prefix="/auth")

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
    redis = getattr(http_request.app.state, "redis", None)
    return await auth_service.register(request, db, redis)


@router.post("/verify-email", response_model=VerifyEmailResponse)
async def verify_email(
    request: VerifyEmailRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Verify email with OTP. Returns payment-required response."""
    redis = getattr(http_request.app.state, "redis", None)
    return await auth_service.verify_email(request.email, request.otp, db, redis)


@router.post("/resend-otp", status_code=202)
async def resend_otp(
    request: ResendOTPRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Resend a new verification OTP."""
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
    redis = getattr(http_request.app.state, "redis", None)
    tokens = await auth_service.login(request, db, redis)
    _set_auth_cookies(response, tokens, http_request)
    return tokens


@router.post("/subscribe", response_model=SubscribeResponse)
async def subscribe(
    request: SubscribeRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Checkout session for the given plan."""
    redis = getattr(http_request.app.state, "redis", None)
    return await auth_service.create_subscription(request.email, request.plan, db, redis)


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
    tokens = await auth_service.refresh_token(token, db)
    _set_auth_cookies(response, tokens, http_request)
    return tokens


@router.get("/me")
async def get_me(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get current user and tenant info (used for cross-subdomain auth sync)."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    from app.models.user import User
    from app.models.tenant import Tenant
    import uuid
    
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
    redis = getattr(http_request.app.state, "redis", None)
    await auth_service.reset_password(body.token, body.new_password, db, redis)
    return {"detail": "Password reset successfully."}
