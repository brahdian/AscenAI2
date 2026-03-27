from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserInfo,
)
from app.services.auth_service import auth_service

router = APIRouter(prefix="/auth")

# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

_IS_SECURE = settings.ENVIRONMENT != "development"


def _set_auth_cookies(response: Response, tokens: TokenResponse) -> None:
    """
    Write access_token and refresh_token as HttpOnly cookies.
    Both are HttpOnly (inaccessible to JS), Secure in non-dev environments,
    and SameSite=Lax to support normal navigation while blocking CSRF.
    The refresh_token path is scoped to /api/v1/auth so it is only sent
    to the refresh / logout endpoints — not every API call.
    """
    base = dict(httponly=True, secure=_IS_SECURE, samesite="lax")
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
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/v1/auth")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    request: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Register a new tenant + owner user and return JWT tokens (+ set cookies)."""
    tokens = await auth_service.register(request, db)
    _set_auth_cookies(response, tokens)
    return tokens


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate and return JWT tokens (+ set HttpOnly cookies)."""
    tokens = await auth_service.login(request, db)
    _set_auth_cookies(response, tokens)
    return tokens


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
    _set_auth_cookies(response, tokens)
    return tokens


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
