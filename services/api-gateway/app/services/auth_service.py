from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.invite import UserInvite
from app.models.tenant import Tenant, TenantUsage
from app.models.user import APIKey, User
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserInfo,
    VerifyEmailResponse,
)
from app.services.email_service import send_email
from app.services.tenant_service import get_all_plan_limits, get_plan_limits

logger = structlog.get_logger(__name__)

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# Pre-computed valid argon2 dummy hash used during login to prevent timing-based
# user enumeration. Must be a real argon2 hash so verify_password runs in
# constant time even when the user email does not exist.
_DUMMY_HASH: str = pwd_context.hash("__ascenai_dummy_password_do_not_use__")

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuthService:
    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def register(self, request: RegisterRequest, db: AsyncSession, redis=None) -> RegisterResponse:
        """Create a new tenant + owner user and return JWT tokens."""
        # Normalize email to lowercase for consistent storage and lookup
        normalized_email = request.email.lower()

        # 1. Handle idempotency for unverified users
        result = await db.execute(
            select(User)
            .where(User.email == normalized_email)
            .order_by(User.created_at.desc())
        )
        user = result.scalars().first()

        if user:
            from fastapi import HTTPException
            
            tenant_res = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
            tenant = tenant_res.scalar_one_or_none()
            if not tenant:
                raise HTTPException(status_code=500, detail="Account inconsistency: user exists without tenant.")
            if user.is_email_verified:
                if tenant.is_active:
                    raise HTTPException(status_code=409, detail="Email already registered and active.")
                
                # ONBOARDING RECOVERY: User verified email but didn't pay.
                user.hashed_password = self.hash_password(request.password)
                user.full_name = request.full_name
                tenant.name = request.business_name
                tenant.business_name = request.business_name
                tenant.business_type = request.business_type
                limits = await get_all_plan_limits(db)
                tenant.plan = request.plan if request.plan in limits else "voice_growth"
                tenant.plan_limits = await get_plan_limits(tenant.plan, db)
                await db.commit()

                logger.info("registration_recovery", user_id=str(user.id), email=normalized_email)
                
                return RegisterResponse(
                    message="Email already verified. Please log in.",
                    email=normalized_email,
                    requires_verification=False,
                )
            
            user.hashed_password = self.hash_password(request.password)
            user.full_name = request.full_name
            user.created_at = _utcnow()

            tenant.name = request.business_name
            tenant.business_name = request.business_name
            tenant.business_type = request.business_type
            limits = await get_all_plan_limits(db)
            tenant.plan = request.plan if request.plan in limits else "voice_growth"
            tenant.plan_limits = await get_plan_limits(tenant.plan, db)
            tenant.created_at = _utcnow()

            logger.info("registration_retry_unverified_account", user_id=str(user.id), email=normalized_email)
        else:
            # 2. Create new tenant
            slug = await self._unique_slug(self._generate_slug(request.business_name), db)
            limits = await get_all_plan_limits(db)
            plan = request.plan if request.plan in limits else "voice_growth"
            tenant = Tenant(
                id=uuid.uuid4(),
                name=request.business_name,
                slug=slug,
                business_type=request.business_type,
                business_name=request.business_name,
                email=normalized_email,
                timezone="UTC",
                plan=plan,
                plan_limits=await get_plan_limits(plan, db),
                is_active=False,
            )
            db.add(tenant)
            await db.flush()

            # 2b. Create usage row
            usage = TenantUsage(id=uuid.uuid4(), tenant_id=tenant.id, last_reset_at=_utcnow())
            db.add(usage)

            # 3. Create user (owner role)
            user = User(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                email=normalized_email,
                hashed_password=self.hash_password(request.password),
                full_name=request.full_name,
                role="owner",
                is_active=True,
                is_email_verified=False,
                session_version=0, # Initial version
            )
            db.add(user)

        await db.commit()
        await db.refresh(user)
        await db.refresh(tenant)

        # NOTE: Stripe customer is now created lazily during subscription/provisioning
        # to avoid record bloat for unverified/spam registrations.

        # 4. Generate OTP
        otp = self._generate_otp()
        if redis:
            await redis.setex(f"otp:{normalized_email}", 1800, otp)

        # 5. Store pending activation in Redis (30-min TTL)
        if redis:
            await redis.setex(
                f"pending_activation:{normalized_email}",
                1800,
                json.dumps({"tenant_id": str(tenant.id), "user_id": str(user.id), "plan": tenant.plan}),
            )

        # 6. Send OTP email (fire-and-forget)
        asyncio.create_task(self._send_otp_email(request.email, request.full_name, otp))

        logger.info("user_registered_pending_verification", user_id=str(user.id), tenant_id=str(tenant.id))
        return RegisterResponse(email=normalized_email)

    async def verify_email(self, email: str, otp: str, db: AsyncSession, redis=None) -> VerifyEmailResponse:
        """Validate OTP and verify user email."""
        from fastapi import HTTPException
        normalized_email = email.lower()
        
        if not redis:
            raise HTTPException(status_code=500, detail="Redis unavailable for verification.")
        
        stored_otp = await redis.get(f"otp:{normalized_email}")

        result = await db.execute(select(User).where(User.email == normalized_email))
        users = result.scalars().all()

        if not users or not stored_otp or stored_otp != otp:
            raise HTTPException(status_code=400, detail="Invalid or expired verification code.")
        
        for user in users:
            user.is_email_verified = True
            
            # Get tenant and activate it for the user
            tenant_result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
            tenant = tenant_result.scalar_one_or_none()
            if tenant:
                tenant.is_active = True
                
        await db.commit()
        await redis.delete(f"otp:{normalized_email}")
        
        # We pick the latest user identity to return for login context
        user = users[0]
        
        logger.info("email_verified_globally", email=normalized_email)

        if redis:
            await redis.delete(f"pending_activation:{normalized_email}")

        return VerifyEmailResponse(
            message="Email verified successfully. You can now log in.",
            email=normalized_email,
            tenant_id=str(tenant.id),
        )

    async def resend_otp(self, email: str, db: AsyncSession, redis=None) -> None:
        """Generate and resend a new OTP."""
        from fastapi import HTTPException
        normalized_email = email.lower()
        
        if not redis:
            return
            
        # Check if user exists and is not verified
        result = await db.execute(
            select(User).where(User.email == normalized_email).order_by(User.last_login_at.desc().nulls_last(), User.created_at.desc())
        )
        user = result.scalars().first()
        
        if user and user.is_email_verified:
            raise HTTPException(status_code=400, detail="Email is already verified. Please log in.")
        if not user:
            return # Silent success to prevent email enumeration
            
        otp = self._generate_otp()
        await redis.setex(f"otp:{normalized_email}", 1800, otp)
        asyncio.create_task(self._send_otp_email(user.email, user.full_name, otp))
        logger.info("otp_resent", email=normalized_email)

    async def login(self, request: LoginRequest, db: AsyncSession, redis=None) -> TokenResponse:
        """Authenticate user and return JWT tokens.
        Includes Account Lockout protection (5 fails = 15m block).
        """
        from fastapi import HTTPException
        normalized_email = request.email.lower()
        
        # 1. Check Account Lockout (pre-emptive)
        if redis:
            lockout_key = f"auth:lockout:{normalized_email}"
            is_locked = await redis.get(lockout_key)
            if is_locked:
                logger.warning("login_attempt_on_locked_account", email=normalized_email)
                raise HTTPException(
                    status_code=403, 
                    detail="Account is temporarily locked due to multiple failed login attempts. Please try again in 15 minutes."
                )

        result = await db.execute(
            select(User)
            .where(User.email == normalized_email)
            .order_by(User.last_login_at.desc().nulls_last(), User.created_at.desc())
        )
        user: User | None = result.scalars().first()

        # Always run verify_password even when user is None to prevent timing-based
        # user enumeration (constant-time response regardless of whether email exists).
        candidate_hash = user.hashed_password if user else _DUMMY_HASH
        password_ok = self.verify_password(request.password, candidate_hash)
        
        if not user or not password_ok:
            # 2. Record Failure for Lockout
            if redis:
                fail_key = f"auth:fails:{normalized_email}"
                fails = await redis.incr(fail_key)
                if fails == 1:
                    await redis.expire(fail_key, 600) # 10m window to hit limit
                if fails >= 5:
                    await redis.setex(f"auth:lockout:{normalized_email}", 900, "1") # 15m lockout
                    await redis.delete(fail_key)
                    logger.warning("account_locked_out", email=normalized_email)
            
            from app.services.audit_service import audit_log
            await audit_log(
                db=db,
                action="auth.login_failed",
                actor_user_id=str(user.id) if user else None,
                category="security",
                status="failure",
                details={"email": normalized_email, "reason": "invalid_credentials"}
            )
            raise HTTPException(status_code=401, detail="Invalid email or password.")

        # 3. Success — Clear lockout counters
        if redis:
            await redis.delete(f"auth:fails:{normalized_email}")

        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account is deactivated.")

        if not user.is_email_verified:
            raise HTTPException(
                status_code=403, 
                detail="Email not verified. Please verify your email to log in.",
                headers={"X-Action": "verify_email"}
            )

        # Get tenant
        tenant_result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        tenant: Tenant | None = tenant_result.scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=403, detail="Tenant account not found.")

        # Update last_login_at
        user.last_login_at = _utcnow()
        await db.commit()

        tokens = self._build_token_response(user, tenant)
        
        from app.services.audit_service import audit_log
        await audit_log(
            db=db,
            action="auth.login_success",
            tenant_id=str(tenant.id),
            actor_user_id=str(user.id),
            category="security",
            status="success"
        )
        
        logger.info("user_logged_in", user_id=str(user.id), tenant_id=str(tenant.id))
        return tokens

    async def refresh_token(self, refresh_token: str, db: AsyncSession, redis=None) -> TokenResponse:
        """Validate refresh token and issue a NEW token pair (Refresh Token Rotation)."""
        from fastapi import HTTPException
        try:
            payload = self.verify_token(refresh_token)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")

        if payload.get("type") != TOKEN_TYPE_REFRESH:
            raise HTTPException(status_code=401, detail="Token is not a refresh token.")

        # --- Refresh Token Rotation Guard ---
        # Detect if this refresh token has already been reused (standard OAuth2 hardening)
        jti = payload.get("jti")
        if jti and redis:
            is_blacklisted = await redis.get(f"auth:refresh_token:used:{jti}")
            if is_blacklisted:
                # REUSE DETECTED: This token was already used to refresh.
                # Significant security risk. Invalidate all sessions for this user.
                user_id = payload.get("sub")
                logger.warning("refresh_token_reuse_detected", user_id=user_id, jti=jti)
                if user_id:
                    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
                    user = result.scalar_one_or_none()
                    if user:
                        user.session_version += 1
                        await db.commit()
                        # Wipe cache
                        async for key in redis.scan_iter(match=f"auth:jwt:{user.id}:*", count=100):
                            await redis.delete(key)
                raise HTTPException(status_code=401, detail="Token already used. Security invalidation triggered.")

            # Mark this token as used for the duration of its remaining lifetime
            exp = payload.get("exp")
            if exp:
                ttl = max(1, int(exp - _utcnow().timestamp()))
                await redis.setex(f"auth:refresh_token:used:{jti}", ttl, "1")

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

        # Build response issues a NEW refresh token (rotation)
        return self._build_token_response(user, tenant)

    async def request_password_reset(
        self, email: str, db: AsyncSession, redis=None
    ) -> None:
        """
        Generate a one-time password-reset token, store it in Redis (1-hour TTL),
        and send a reset email. Always succeeds silently to prevent email enumeration.
        Rate-limited to 3 requests per email per hour to prevent abuse.
        """
        import hashlib


        # Rate-limit: max 3 reset requests per email per hour
        if redis:
            rate_key = f"pwd_reset_rate:{email.lower()}"
            try:
                count = await redis.incr(rate_key)
                if count == 1:
                    await redis.expire(rate_key, 3600)
                if count > 3:
                    # Return silently to avoid revealing the limit exists (prevents timing attacks)
                    logger.warning("password_reset_rate_limited", email_hash=hashlib.sha256(email.encode()).hexdigest()[:8])
                    return
            except Exception:
                pass  # Redis failure — allow through to avoid availability regression

        # Normalize email before DB lookup
        normalized_email = email.lower()
        result = await db.execute(
            select(User).where(User.email == normalized_email).order_by(User.last_login_at.desc().nulls_last(), User.created_at.desc())
        )
        user: User | None = result.scalars().first()
        if not user or not user.is_active:
            return  # Silent success — don't reveal whether the email exists

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

        if redis:
            # Store hash → user_id with 1-hour TTL; use hash so raw token isn't in Redis
            await redis.setex(f"pwd_reset:{token_hash}", 3600, str(user.id))

        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={raw_token}"
        asyncio.create_task(self._send_reset_email(email, user.full_name, reset_url))
        logger.info("password_reset_requested", user_id=str(user.id))

    async def reset_password(
        self, raw_token: str, new_password: str, db: AsyncSession, redis=None
    ) -> None:
        """
        Validate the reset token, update the user's password, and invalidate the token.
        Raises HTTPException if token is invalid or expired.
        """
        import hashlib

        from fastapi import HTTPException

        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        user_id_str: str | None = None

        if redis:
            user_id_str = await redis.get(f"pwd_reset:{token_hash}")

        if not user_id_str:
            raise HTTPException(status_code=400, detail="Invalid or expired reset token.")

        result = await db.execute(select(User).where(User.id == uuid.UUID(user_id_str)))
        user: User | None = result.scalar_one_or_none()
        if not user or not user.is_active:
            raise HTTPException(status_code=400, detail="Invalid or expired reset token.")

        # Zenith Pillar 7: If the user belongs to multiple tenants, reset the password for ALL of their accounts
        all_users_res = await db.execute(select(User).where(User.email == user.email))
        all_users = all_users_res.scalars().all()

        for u in all_users:
            u.hashed_password = self.hash_password(new_password)
            u.session_version += 1
            
        await db.commit()

        # Invalidate the reset token immediately (one-time use)
        if redis:
            await redis.delete(f"pwd_reset:{token_hash}")

        # Invalidate all active JWT auth-cache entries for this user so any
        # stolen tokens are rejected at next use (within the cache TTL window).
        if redis:
            try:
                pattern = f"auth:jwt:{user.id}:*"
                async for cache_key in redis.scan_iter(match=pattern, count=100):
                    await redis.delete(cache_key)
                logger.info("jwt_cache_invalidated_after_password_reset", user_id=str(user.id))
            except Exception as exc:
                logger.warning("jwt_cache_invalidation_failed", error=str(exc))

        logger.info("password_reset_completed", user_id=str(user.id))

    async def create_api_key(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str,
        scopes: list[str],
        db: AsyncSession,
        expires_at: datetime | None = None,
        agent_id: uuid.UUID | None = None,
        allowed_origins: list[str] | None = None,
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
            agent_id=agent_id,
            allowed_origins=allowed_origins,
            is_active=True,
        )
        db.add(api_key)
        await db.commit()
        await db.refresh(api_key)

        from app.services.audit_service import audit_log
        await audit_log(
            db=db,
            action="api_key.created",
            tenant_id=str(tenant_id),
            actor_user_id=str(user_id),
            category="security",
            resource_type="api_key",
            resource_id=str(api_key.id),
            status="success",
            details={
                "name": name,
                "key_prefix": key_prefix,
                "scopes": scopes,
                "agent_id": str(agent_id) if agent_id else None,
            },
        )

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

    async def invalidate_api_key_cache(self, key_hash: str, redis=None) -> None:
        """Instant revocation: remove cached API key from Redis."""
        if not redis:
            return
        try:
            cache_key = f"auth:api_key:{key_hash}"
            await redis.delete(cache_key)
            logger.info("api_key_cache_invalidated", key_hash=key_hash[:8] + "...")
        except Exception as exc:
            logger.warning("api_key_cache_invalidation_failed", error=str(exc))

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

    async def create_invite(
        self,
        tenant_id: str,
        email: str,
        role: str,
        invited_by: str,
        db: AsyncSession,
    ) -> UserInvite:
        """Create a secure invitation token and send an email."""
        from fastapi import HTTPException
        
        # Check if user already exists in THIS tenant
        normalized_email = email.lower()
        existing = await db.execute(
            select(User).where(
                User.tenant_id == uuid.UUID(tenant_id),
                User.email == normalized_email
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="User already in team.")

        # Generate secure token
        token = secrets.token_urlsafe(32)
        
        invite = UserInvite(
            id=uuid.uuid4(),
            tenant_id=uuid.UUID(tenant_id),
            email=normalized_email,
            role=role,
            token=token,
            invited_by=uuid.UUID(invited_by),
            expires_at=_utcnow() + timedelta(days=7),
        )
        db.add(invite)
        await db.commit()
        await db.refresh(invite)

        # Send email
        tenant_res = await db.execute(select(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
        tenant = tenant_res.scalar_one_or_none()
        
        invite_url = f"{settings.FRONTEND_URL}/accept-invite?token={token}"
        asyncio.create_task(self._send_invite_email(email, tenant.name if tenant else "a team", invite_url))
        
        logger.info("invite_created", tenant_id=tenant_id, email=normalized_email)
        return invite

    async def accept_invite(
        self,
        token: str,
        full_name: str,
        password: str,
        db: AsyncSession,
    ) -> User:
        """Verify token, create user, and mark invite as accepted."""
        from fastapi import HTTPException
        
        result = await db.execute(
            select(UserInvite).where(
                UserInvite.token == token,
                UserInvite.accepted_at == None,
                UserInvite.expires_at > _utcnow()
            )
        )
        invite = result.scalar_one_or_none()
        if not invite:
            raise HTTPException(status_code=400, detail="Invalid or expired invitation.")

        # Create the user
        user = User(
            id=uuid.uuid4(),
            tenant_id=invite.tenant_id,
            email=invite.email,
            hashed_password=self.hash_password(password),
            full_name=full_name,
            role=invite.role,
            is_active=True,
            is_email_verified=True, # Trust the invitation link
        )
        db.add(user)
        
        invite.accepted_at = _utcnow()
        
        await db.commit()
        await db.refresh(user)
        
        logger.info("invite_accepted", user_id=str(user.id), tenant_id=str(invite.tenant_id))
        return user

    @staticmethod
    async def _send_invite_email(email: str, tenant_name: str, invite_url: str) -> None:
        """Send an invitation email."""
        html_body = f"""
        <html><body>
        <h2>You've been invited!</h2>
        <p>You have been invited to join <strong>{tenant_name}</strong> on AscenAI.</p>
        <p>Click the link below to set up your account and join the team:</p>
        <p><a href="{invite_url}" style="background-color: #4f46e5; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Accept Invitation</a></p>
        <p>If you don't have an account yet, you'll be asked to set a password.</p>
        <p>This invitation expires in 7 days.</p>
        </body></html>
        """
        await send_email(email, f"Invitation to join {tenant_name} on AscenAI", html_body)

    async def delete_account(self, user_id_str: str, db: AsyncSession, redis=None) -> None:
        """
        Delete the user's account and associated tenant data to satisfy GDPR right to be forgotten.
        If the user is an owner, this wipes the tenant completely.
        """
        from fastapi import HTTPException
        from sqlalchemy import delete
        
        result = await db.execute(select(User).where(User.id == uuid.UUID(user_id_str)))
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")

        tenant_id = user.tenant_id
        
        if user.role == "owner":
            logger.info("gdpr_deletion_owner", user_id=user_id_str, tenant_id=str(tenant_id))
            await db.execute(delete(TenantUsage).where(TenantUsage.tenant_id == tenant_id))
            await db.execute(delete(APIKey).where(APIKey.tenant_id == tenant_id))
            await db.execute(delete(User).where(User.id == user.id))
            await db.execute(delete(Tenant).where(Tenant.id == tenant_id))
        else:
            logger.info("gdpr_deletion_member", user_id=user_id_str, tenant_id=str(tenant_id))
            await db.execute(delete(User).where(User.id == user.id))
            
        await db.commit()
        
        if redis:
            try:
                pattern = f"auth:jwt:{user.id}:*"
                async for cache_key in redis.scan_iter(match=pattern, count=100):
                    await redis.delete(cache_key)
            except Exception as exc:
                logger.warning("jwt_cache_invalidation_failed", error=str(exc))

    async def cleanup_pending_accounts(self, db: AsyncSession, redis=None) -> int:
        """
        Remove inactive tenants/users that were created but never completed payment.
        
        A pending account is eligible for cleanup if:
        - tenant.is_active is False
        - tenant.created_at is older than 30 minutes
        - No Stripe checkout session is still active in Redis for this tenant
        
        Returns the number of cleaned-up accounts.
        """
        from sqlalchemy import delete
        
        cutoff = _utcnow() - timedelta(minutes=30)
        
        # Find all inactive tenants older than 30 minutes
        result = await db.execute(
            select(Tenant).where(
                Tenant.is_active.is_(False),
                Tenant.created_at <= cutoff,
            )
        )
        pending_tenants = result.scalars().all()
        
        cleaned = 0
        for tenant in pending_tenants:
            # Check if there's still an active Stripe session for this tenant
            if redis:
                # Look for any stripe_session:* keys that reference this tenant
                try:
                    keys = await redis.keys("stripe_session:*")
                    has_active_session = False
                    for key in keys:
                        raw = await redis.get(key)
                        if raw:
                            session_data = json.loads(raw)
                            if session_data.get("tenant_id") == str(tenant.id):
                                has_active_session = True
                                break
                    
                    if has_active_session:
                        continue  # Skip — still has active payment session
                except Exception as exc:
                    logger.warning("cleanup_redis_check_failed", tenant_id=str(tenant.id), error=str(exc))
            
            # Look up the user for this tenant
            user_result = await db.execute(select(User).where(User.tenant_id == tenant.id))
            user = user_result.scalar_one_or_none()
            
            # Delete usage record
            await db.execute(delete(TenantUsage).where(TenantUsage.tenant_id == tenant.id))
            
            # Delete user if exists
            if user:
                await db.execute(delete(User).where(User.id == user.id))
            
            # Delete tenant (cascade will handle related records)
            await db.execute(delete(Tenant).where(Tenant.id == tenant.id))
            
            # Clean up Redis keys
            if redis:
                await redis.delete(f"pending_activation:{tenant.email}")
                await redis.delete(f"otp:{tenant.email}")
            
            cleaned += 1
            logger.info("pending_account_cleaned", tenant_id=str(tenant.id), email=tenant.email)
        
        if cleaned > 0:
            await db.commit()
            logger.info("cleanup_completed", cleaned_count=cleaned)
        
        return cleaned

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_otp() -> str:
        """Generate a cryptographically strong 6-digit numeric OTP."""
        return "".join([str(secrets.randbelow(10)) for _ in range(6)])

    @staticmethod
    async def _send_otp_email(email: str, full_name: str, otp: str) -> None:
        """Send a verification OTP email (async, best-effort)."""
        html_body = f"""
        <html><body>
        <div style="font-family: sans-serif; max-width: 500px; margin: 0 auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
            <h2 style="color: #4f46e5;">Verify your email</h2>
            <p>Hi {full_name},</p>
            <p>Please enter the following 6-digit code to complete your registration:</p>
            <div style="font-size: 32px; font-weight: bold; letter-spacing: 5px; padding: 20px 0; color: #1f2937; text-align: center;">
                {otp}
            </div>
            <p style="color: #6b7280; font-size: 14px;">This code will expire in 10 minutes. If you did not sign up for AscenAI, please ignore this email.</p>
            <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="font-size: 12px; color: #9ca3af;">&copy; 2026 AscenAI. All rights reserved.</p>
        </div>
        </body></html>
        """
        subject = f"{otp} is your AscenAI verification code"
        await send_email(email, subject, html_body)

    def _build_token_response(self, user: User, tenant: Tenant) -> TokenResponse:
        token_data = {
            "sub": str(user.id),
            "tenant_id": str(tenant.id),
            "role": user.role,
            "email": user.email,
            "version": user.session_version,
            "mfa": getattr(user, "mfa_enabled", False),
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
                mfa_enabled=getattr(user, "mfa_enabled", False),
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
    async def _send_reset_email(email: str, full_name: str, reset_url: str) -> None:
        """Send a password-reset email (async, best-effort)."""
        html_body = f"""
        <html><body>
        <p>Hi {full_name},</p>
        <p>Click the link below to reset your password. This link expires in 1 hour.</p>
        <p><a href="{reset_url}">Reset Password</a></p>
        <p>If you did not request a password reset, ignore this email.</p>
        </body></html>
        """
        await send_email(email, "Reset your AscenAI password", html_body)

    @staticmethod
    async def _send_welcome_email(email: str, full_name: str) -> None:
        """Send a welcome email (async, best-effort)."""
        html_body = f"""
        <html><body>
        <h1>Welcome to AscenAI, {full_name}!</h1>
        <p>Your account has been created. You're on the <strong>Professional</strong> plan.</p>
        <p>Get started at <a href="{settings.FRONTEND_URL}">{settings.FRONTEND_URL}</a></p>
        </body></html>
        """
        await send_email(email, "Welcome to AscenAI!", html_body)


# Singleton instance
auth_service = AuthService()
