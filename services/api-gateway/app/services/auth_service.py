from __future__ import annotations

import asyncio
import hashlib
import json
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
    RegisterResponse,
    SubscribeResponse,
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
        existing_user_res = await db.execute(select(User).where(User.email == normalized_email))
        user = existing_user_res.scalar_one_or_none()

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
                # Update their info in case they chose a different plan/business name on retry
                user.hashed_password = self.hash_password(request.password)
                user.full_name = request.full_name
                tenant.name = request.business_name
                tenant.business_name = request.business_name
                tenant.business_type = request.business_type
                limits = await get_all_plan_limits(db)
                tenant.plan = request.plan if request.plan in limits else "voice_growth"
                tenant.plan_limits = await get_plan_limits(tenant.plan, db)
                await db.commit()

                payment_url = None
                try:
                    sub_resp = await self.create_subscription(normalized_email, tenant.plan, db, redis)
                    payment_url = sub_resp.payment_url
                except Exception as exc:
                    logger.error("failed_to_generate_recovery_payment_link", email=normalized_email, error=str(exc))

                logger.info("registration_recovery_verified_unpaid", user_id=str(user.id), email=normalized_email)
                
                return RegisterResponse(
                    message="Email already verified. Complete payment to activate your account." if payment_url else "Email already verified.",
                    email=normalized_email,
                    requires_verification=False,
                    requires_payment=True,
                    payment_url=payment_url,
                )
            # Re-use existing tenant/user for unverified accounts
            # Update data to reflect latest registration attempt
            user.hashed_password = self.hash_password(request.password)
            user.full_name = request.full_name
            user.created_at = _utcnow() # Reset for cleanup task

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
                phone="",
                address={},
                timezone="UTC",
                plan=plan,
                plan_limits=await get_plan_limits(plan, db),
                is_active=False,
                metadata_={},
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
            )
            db.add(user)

        await db.commit()
        await db.refresh(user)
        await db.refresh(tenant)

        # 3b. Create Stripe customer
        stripe_customer_id = await _create_stripe_customer(tenant, user)
        if stripe_customer_id:
            tenant.stripe_customer_id = stripe_customer_id
            await db.commit()

        # 4. Generate OTP
        otp = self._generate_otp()
        if redis:
            await redis.setex(f"otp:{normalized_email}", 600, otp) # 10 minute TTL

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
        return RegisterResponse(email=normalized_email, requires_payment=True)

    async def verify_email(self, email: str, otp: str, db: AsyncSession, redis=None) -> VerifyEmailResponse:
        """Validate OTP and verify user email. Returns payment-required response."""
        from fastapi import HTTPException
        normalized_email = email.lower()
        
        if not redis:
            raise HTTPException(status_code=500, detail="Redis unavailable for verification.")
        
        stored_otp = await redis.get(f"otp:{normalized_email}")

        # Mark user as verified
        result = await db.execute(select(User).where(User.email == normalized_email))
        user = result.scalar_one_or_none()

        # Validate OTP *after* the DB lookup so both branches take the same
        # code path and are not distinguishable by response time.
        # Return the same generic error whether the email is unknown or the
        # OTP is wrong — prevents email enumeration via error messages.
        if not user or not stored_otp or stored_otp != otp:
            raise HTTPException(status_code=400, detail="Invalid or expired verification code.")
        
        user.is_email_verified = True
        
        # Get tenant and activate it (allows login)
        tenant_result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        tenant = tenant_result.scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found.")
        
        tenant.is_active = True
        await db.commit()
        await redis.delete(f"otp:{normalized_email}")
        
        logger.info("email_verified", user_id=str(user.id))

        # Automatically create checkout session if not already paid
        payment_url = None
        # Check if the tenant has a valid subscription
        if tenant.subscription_status != "active":
            try:
                sub_resp = await self.create_subscription(normalized_email, tenant.plan, db, redis)
                payment_url = sub_resp.payment_url
                # Cleanup pending activation as we are moving to payment
                if redis:
                    await redis.delete(f"pending_activation:{normalized_email}")
            except Exception as exc:
                logger.error("failed_to_generate_payment_link", email=normalized_email, error=str(exc))

        return VerifyEmailResponse(
            message="Email verified. Complete payment to activate your account." if payment_url else "Email verified.",
            email=normalized_email,
            tenant_id=str(tenant.id),
            requires_payment=not tenant.is_active,
            payment_url=payment_url,
        )

    async def create_subscription(self, email: str, plan: str, db: AsyncSession, redis=None) -> SubscribeResponse:
        """Create Stripe Checkout session for the given plan."""
        from fastapi import HTTPException
        normalized_email = email.lower()

        result = await db.execute(select(User).where(User.email == normalized_email))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")

        tenant_result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        tenant = tenant_result.scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        if tenant.is_active:
            raise HTTPException(status_code=400, detail="Account is already active.")

        limits = await get_all_plan_limits(db)
        if plan not in limits:
            raise HTTPException(status_code=400, detail=f"Unknown plan: {plan}")

        if not settings.STRIPE_SECRET_KEY:
            raise HTTPException(status_code=500, detail="Stripe is not configured.")

        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY

        price_id = await _get_stripe_price_id_for_plan(plan)

        success_url = f"{settings.FRONTEND_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{settings.FRONTEND_URL}/payment/cancel"

        checkout_session = stripe.checkout.Session.create(
            customer=tenant.stripe_customer_id,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "tenant_id": str(tenant.id),
                "user_id": str(user.id),
                "email": normalized_email,
                "plan": plan,
            },
        )

        if redis:
            await redis.setex(
                f"stripe_session:{checkout_session.id}",
                1800,
                json.dumps({"tenant_id": str(tenant.id), "email": normalized_email, "plan": plan}),
            )

        logger.info("stripe_checkout_created", session_id=checkout_session.id, email=normalized_email)
        return SubscribeResponse(
            payment_url=checkout_session.url,
            session_id=checkout_session.id,
            plan=plan,
        )

    async def resend_otp(self, email: str, db: AsyncSession, redis=None) -> None:
        """Generate and resend a new OTP."""
        from fastapi import HTTPException
        normalized_email = email.lower()
        
        if not redis:
            return
            
        # Check if user exists and is not verified
        result = await db.execute(select(User).where(User.email == normalized_email))
        user = result.scalar_one_or_none()
        
        if user and user.is_email_verified:
            raise HTTPException(status_code=400, detail="Email is already verified. Please log in.")
        if not user:
            return # Silent success to prevent email enumeration
            
        otp = self._generate_otp()
        await redis.setex(f"otp:{normalized_email}", 600, otp)
        asyncio.create_task(self._send_otp_email(user.email, user.full_name, otp))
        logger.info("otp_resent", email=normalized_email)

    async def login(self, request: LoginRequest, db: AsyncSession, redis=None) -> TokenResponse:
        """Authenticate user and return JWT tokens."""
        result = await db.execute(select(User).where(User.email == request.email.lower()))
        user: User | None = result.scalar_one_or_none()

        from fastapi import HTTPException
        # Always run verify_password even when user is None to prevent timing-based
        # user enumeration (constant-time response regardless of whether email exists).
        candidate_hash = user.hashed_password if user else _DUMMY_HASH
        password_ok = self.verify_password(request.password, candidate_hash)
        if not user or not password_ok:
            raise HTTPException(status_code=401, detail="Invalid email or password.")

        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account is deactivated.")

        if not user.is_email_verified:
            raise HTTPException(
                status_code=403, 
                detail="Email not verified. Please verify your email to log in.",
                headers={"X-Action": "verify_email"}
            )

        # Get tenant
        tenant_result = await db.execute(
            select(Tenant).where(Tenant.id == user.tenant_id)
        )
        tenant: Tenant | None = tenant_result.scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=403, detail="Tenant account not found.")

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

    async def request_password_reset(
        self, email: str, db: AsyncSession, redis=None
    ) -> None:
        """
        Generate a one-time password-reset token, store it in Redis (1-hour TTL),
        and send a reset email. Always succeeds silently to prevent email enumeration.
        Rate-limited to 3 requests per email per hour to prevent abuse.
        """
        import hashlib
        from fastapi import HTTPException as _HTTPException

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
        result = await db.execute(select(User).where(User.email == normalized_email))
        user: User | None = result.scalar_one_or_none()
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

        user.hashed_password = self.hash_password(new_password)
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

    async def cleanup_pending_accounts(self, db: AsyncSession, redis=None) -> int:
        """
        Remove inactive tenants/users that were created but never completed payment.
        
        A pending account is eligible for cleanup if:
        - tenant.is_active is False
        - tenant.created_at is older than 30 minutes
        - No Stripe checkout session is still active in Redis for this tenant
        
        Returns the number of cleaned-up accounts.
        """
        from sqlalchemy import text, delete
        
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


async def _create_stripe_customer(tenant: Tenant, user: User) -> str | None:
    """Create a Stripe customer and return the customer ID, or None if Stripe is not configured."""
    if not settings.STRIPE_SECRET_KEY:
        return None
    
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    
    try:
        customer = stripe.Customer.create(
            email=user.email,
            name=tenant.name,
            metadata={"tenant_id": str(tenant.id)},
        )
        return customer.id
    except Exception as e:
        logger.warning("stripe_customer_creation_failed", error=str(e))
        return None


# Singleton instance
auth_service = AuthService()


async def _get_stripe_price_id_for_plan(plan: str) -> str:
    """Look up or create a Stripe Price ID for the given plan."""
    from app.core.config import settings

    # 1. First, try reading from environment variables
    if plan == "text_growth" and settings.STRIPE_TEXT_GROWTH_PRICE_ID:
        return settings.STRIPE_TEXT_GROWTH_PRICE_ID
    if plan == "voice_growth" and settings.STRIPE_VOICE_GROWTH_PRICE_ID:
        return settings.STRIPE_VOICE_GROWTH_PRICE_ID
    if plan == "voice_business" and settings.STRIPE_VOICE_BUSINESS_PRICE_ID:
        return settings.STRIPE_VOICE_BUSINESS_PRICE_ID

    # 2. Fallback to lookup_key search if env var is missing
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY

    price_lookup_key = f"ascenai_{plan}"

    try:
        prices = stripe.Price.list(lookup_keys=[price_lookup_key], limit=1)
        if prices.data:
            return prices.data[0].id
    except Exception as e:
        logger.warning("stripe_price_lookup_failed", plan=plan, error=str(e))
    try:
        # 3. If lookup fails, dynamically create the Product and Price
        logger.info("stripe_price_not_found_creating", plan=plan)
        
        product_name = f"AscenAI {plan.replace('_', ' ').title()}"
        product = stripe.Product.create(name=product_name)
        
        # Default amounts based on plan heuristics (in cents)
        amount = 9900  # $99 defaults
        if "business" in plan:
            amount = 29900 # $299

        price = stripe.Price.create(
            unit_amount=amount,
            currency="usd",
            recurring={"interval": "month"},
            product=product.id,
            lookup_key=price_lookup_key,
        )
        return price.id
    except Exception as e2:
        logger.error("stripe_dynamic_creation_failed", plan=plan, error=str(e2))
        raise Exception(f"No Stripe price configured for plan '{plan}' and auto-creation failed: {str(e2)}")
