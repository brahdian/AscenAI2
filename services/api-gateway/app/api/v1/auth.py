from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

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


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(request: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new tenant + owner user."""
    return await auth_service.register(request, db)


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate and return JWT tokens."""
    return await auth_service.login(request, db)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Refresh access token using a valid refresh token."""
    return await auth_service.refresh_token(request.refresh_token, db)


@router.post("/forgot-password", status_code=202)
async def forgot_password(http_request: Request, body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """
    Generate a password-reset token stored in Redis (1-hour TTL) and send an email.
    Always returns 202 regardless of whether the email exists — prevents enumeration.
    """
    redis = getattr(http_request.app.state, "redis", None)
    await auth_service.request_password_reset(body.email, db, redis)
    return {"detail": "If that email exists, a reset link has been sent."}


@router.post("/reset-password", status_code=200)
async def reset_password(http_request: Request, body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Reset password using a valid reset token (one-time, 1-hour TTL)."""
    redis = getattr(http_request.app.state, "redis", None)
    await auth_service.reset_password(body.token, body.new_password, db, redis)
    return {"detail": "Password reset successfully."}
