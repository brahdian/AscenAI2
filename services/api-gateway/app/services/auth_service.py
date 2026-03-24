from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.tenant import Tenant, TenantUsage
from app.models.user import APIKey, User
from app.schemas.auth import (
    APIKeyCreatedResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserInfo,
)
from app.services.tenant_service import PLAN_LIMITS

logger = structlog.get_logger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuthService:
    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def register(self, request: RegisterRequest, db: AsyncSession) -> TokenResponse:
        """Create a new tenant + owner user and return JWT tokens."""
        # 1. Check email uniqueness
        existing = await db.execute(select(User).where(User.email == request.email))
        if existing.scalar_one_or_none():
            from fastapi import HTTPException
            raise HTTPException(status_code=409, detail="Email already registered.")

        # 2. Create tenant with default settings
        slug = self._generate_slug(request.business_name)
        # Make slug unique by appending random suffix if needed
        slug = await self._unique_slug(slug, db)

        plan = "starter"
        tenant = Tenant(
            id=uuid.uuid4(),
            name=request.business_name,
            slug=slug,
            business_type=request.business_type,
            business_name=request.business_name,
            email=request.email,
            phone="",
            address={},
            timezone="UTC",
            plan=plan,
            plan_limits=PLAN_LIMITS[plan],
            is_active=True,
            trial_ends_at=_utcnow() + timedelta(days=14),
            metadata_={},
        )
        db.add(tenant)
        await db.flush()  # get tenant.id

        # 2b. Create usage row
        usage = TenantUsage(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            last_reset_at=_utcnow(),
        )
        db.add(usage)

        # 3. Create user (owner role)
        user = User(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            email=request.email,
            hashed_password=self.hash_password(request.password),
            full_name=request.full_name,
            role="owner",
            is_active=True,
            is_email_verified=False,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        # 4. Generate JWT tokens
        tokens = self._build_token_response(user, tenant)

        # 5. Send welcome email (fire-and-forget)
        import asyncio
        asyncio.create_task(self._send_welcome_email(request.email, request.full_name))

        logger.info("user_registered", user_id=str(user.id), tenant_id=str(tenant.id))
        return tokens

    async def login(self, request: LoginRequest, db: AsyncSession) -> TokenResponse:
        """Authenticate user and return JWT tokens."""
        result = await db.execute(select(User).where(User.email == request.email))
        user: User | None = result.scalar_one_or_none()

        from fastapi import HTTPException
        if not user or not self.verify_password(request.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid email or password.")

        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account is deactivated.")

        # Get tenant
        tenant_result = await db.execute(
            select(Tenant).where(Tenant.id == user.tenant_id)
        )
        tenant: Tenant | None = tenant_result.scalar_one_or_none()
        if not tenant or not tenant.is_active:
            raise HTTPException(status_code=403, detail="Tenant account is inactive.")

        # Update last_login_at
        user.last_login_at = _utcnow()
        await db.commit()

        tokens = self._build_token_response(user, tenant)
        logger.info("user_logged_in", user_id=str(user.id), tenant_id=str(tenant.id))
        return tokens

    async def refresh_token(self, refresh_token: str, db: AsyncSession) -> TokenResponse:
        """Validate refresh token and issue a new token pair."""
        from fastapi import HTTPException
        try:
            payload = self.verify_token(refresh_token)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")

        if payload.get("type") != TOKEN_TYPE_REFRESH:
            raise HTTPException(status_code=401, detail="Token is not a refresh token.")

        user_id = payload.get("sub")
        result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
        user: User | None = result.scalar_one_or_none()
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="User not found or inactive.")

        tenant_result = await db.execute(
            select(Tenant).where(Tenant.id == user.tenant_id)
        )
        tenant: Tenant | None = tenant_result.scalar_one_or_none()
        if not tenant or not tenant.is_active:
            raise HTTPException(status_code=403, detail="Tenant account is inactive.")

        return self._build_token_response(user, tenant)

    async def create_api_key(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str,
        scopes: list[str],
        db: AsyncSession,
        expires_at: datetime | None = None,
    ) -> tuple[str, APIKey]:
        """Generate a new API key. Returns (raw_key, APIKey) — raw_key shown once."""
        # Generate: sk_live_<32 random hex chars>
        raw_key = "sk_live_" + secrets.token_hex(32)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:12]  # "sk_live_xxxx"

        api_key = APIKey(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=user_id,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes=scopes,
            rate_limit_per_minute=60,
            expires_at=expires_at,
            is_active=True,
        )
        db.add(api_key)
        await db.commit()
        await db.refresh(api_key)

        logger.info(
            "api_key_created",
            key_prefix=key_prefix,
            tenant_id=str(tenant_id),
            user_id=str(user_id),
        )
        return raw_key, api_key

    async def lookup_api_key(self, raw_key: str, db: AsyncSession) -> APIKey | None:
        """Resolve a raw API key to its DB record (validates hash)."""
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        result = await db.execute(
            select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active.is_(True))
        )
        api_key: APIKey | None = result.scalar_one_or_none()
        if api_key is None:
            return None

        # Check expiry
        if api_key.expires_at and api_key.expires_at < _utcnow():
            return None

        # Update last_used_at (best-effort; don't block if it fails)
        api_key.last_used_at = _utcnow()
        try:
            await db.commit()
        except Exception:
            await db.rollback()

        return api_key

    # ------------------------------------------------------------------
    # JWT helpers
    # ------------------------------------------------------------------

    def create_access_token(self, data: dict) -> str:
        payload = data.copy()
        payload.update(
            {
                "type": TOKEN_TYPE_ACCESS,
                "exp": _utcnow()
                + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
                "iat": _utcnow(),
                "jti": str(uuid.uuid4()),
            }
        )
        return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    def create_refresh_token(self, data: dict) -> str:
        payload = data.copy()
        payload.update(
            {
                "type": TOKEN_TYPE_REFRESH,
                "exp": _utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
                "iat": _utcnow(),
                "jti": str(uuid.uuid4()),
            }
        )
        return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    def verify_token(self, token: str) -> dict:
        """Decode and verify a JWT; raises JWTError on failure."""
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])

    def hash_password(self, password: str) -> str:
        return pwd_context.hash(password)

    def verify_password(self, password: str, hashed: str) -> bool:
        return pwd_context.verify(password, hashed)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_token_response(self, user: User, tenant: Tenant) -> TokenResponse:
        token_data = {
            "sub": str(user.id),
            "tenant_id": str(tenant.id),
            "role": user.role,
            "email": user.email,
        }
        access_token = self.create_access_token(token_data)
        refresh_token = self.create_refresh_token({"sub": str(user.id)})
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            tenant_id=str(tenant.id),
            user=UserInfo(
                id=str(user.id),
                email=user.email,
                full_name=user.full_name,
                role=user.role,
                tenant_id=str(tenant.id),
            ),
        )

    @staticmethod
    def _generate_slug(name: str) -> str:
        import re
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower().strip())
        slug = slug.strip("-")[:60]
        return slug or "tenant"

    @staticmethod
    async def _unique_slug(base_slug: str, db: AsyncSession) -> str:
        slug = base_slug
        for _ in range(10):
            result = await db.execute(select(Tenant).where(Tenant.slug == slug))
            if result.scalar_one_or_none() is None:
                return slug
            slug = f"{base_slug}-{secrets.token_hex(3)}"
        return f"{base_slug}-{secrets.token_hex(6)}"

    @staticmethod
    async def _send_welcome_email(email: str, full_name: str) -> None:
        """Send a welcome email via SMTP (async, best-effort)."""
        if not settings.SMTP_HOST:
            logger.info("smtp_not_configured_skipping_welcome_email", email=email)
            return
        try:
            import aiosmtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            msg = MIMEMultipart("alternative")
            msg["Subject"] = "Welcome to AscenAI!"
            msg["From"] = settings.FROM_EMAIL
            msg["To"] = email

            html_body = f"""
            <html><body>
            <h1>Welcome to AscenAI, {full_name}!</h1>
            <p>Your account has been created. You're on the <strong>Starter</strong> plan
            with a 14-day free trial.</p>
            <p>Get started at <a href="{settings.FRONTEND_URL}">{settings.FRONTEND_URL}</a></p>
            </body></html>
            """
            msg.attach(MIMEText(html_body, "html"))

            await aiosmtplib.send(
                msg,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USER or None,
                password=settings.SMTP_PASSWORD or None,
                start_tls=True,
            )
            logger.info("welcome_email_sent", email=email)
        except Exception as exc:
            logger.warning("welcome_email_failed", email=email, error=str(exc))


# Singleton instance
auth_service = AuthService()
