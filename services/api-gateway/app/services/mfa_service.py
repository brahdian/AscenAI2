from __future__ import annotations

import base64
import io
import uuid
from datetime import datetime, timezone

import pyotp
import qrcode
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_secret
from app.models.user import MFABackupCode, MFASecret


class MFAService:
    """
    Zenith Pillar 1: Total Identity & Forensic Traceability
    
    Implements Time-based One-Time Password (TOTP) multi-factor authentication.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def generate_secret(self, user_id: uuid.UUID) -> tuple[str, str]:
        """
        Generate new TOTP secret for user.
        
        Returns:
            (secret_base32, provisioning_uri)
        """
        # Delete existing secrets
        existing = await self.db.execute(
            select(MFASecret).where(MFASecret.user_id == user_id)
        )
        for secret in existing.scalars().all():
            await self.db.delete(secret)
        
        # Generate new secret
        secret = pyotp.random_base32()
        provisioning_uri = pyotp.totp.TOTP(secret).provisioning_uri(
            name=settings.APP_NAME,
            issuer_name=settings.ORGANIZATION_NAME
        )
        
        # Store secret encrypted (reversible)
        from app.services.encryption_service import encryption_service
        new_secret = MFASecret(
            user_id=user_id,
            secret=encryption_service.encrypt(secret),
            created_at=datetime.now(timezone.utc),
            verified=False
        )
        self.db.add(new_secret)
        await self.db.commit()
        
        return secret, provisioning_uri
    
    async def generate_qr_code(self, provisioning_uri: str) -> str:
        """Generate base64 encoded QR code for provisioning URI"""
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64 PNG
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        
        return base64.b64encode(buffer.read()).decode('utf-8')
    
    async def verify_code(self, user_id: uuid.UUID, code: str) -> bool:
        """Verify TOTP code for user"""
        secret = await self.db.execute(
            select(MFASecret)
            .where(MFASecret.user_id == user_id)
            .where(MFASecret.verified == True)
            .order_by(MFASecret.created_at.desc())
            .limit(1)
        )
        secret = secret.scalar_one_or_none()
        
        if not secret:
            return False
        
        from app.services.encryption_service import encryption_service
        raw_secret = encryption_service.decrypt(secret.secret)
        totp = pyotp.TOTP(raw_secret)
        return totp.verify(code, valid_window=1)
    
    async def confirm_setup(self, user_id: uuid.UUID, code: str) -> bool:
        """Confirm MFA setup by verifying initial code"""
        secret = await self.db.execute(
            select(MFASecret)
            .where(MFASecret.user_id == user_id)
            .where(MFASecret.verified == False)
            .order_by(MFASecret.created_at.desc())
            .limit(1)
        )
        secret = secret.scalar_one_or_none()
        
        if not secret:
            return False
        
        from app.services.encryption_service import encryption_service
        raw_secret = encryption_service.decrypt(secret.secret)
        totp = pyotp.TOTP(raw_secret)
        if totp.verify(code, valid_window=1):
            secret.verified = True
            secret.verified_at = datetime.now(timezone.utc)
            await self.db.commit()
            return True
        
        return False
    
    async def disable_mfa(self, user_id: uuid.UUID) -> None:
        """Disable MFA for user"""
        secrets = await self.db.execute(
            select(MFASecret).where(MFASecret.user_id == user_id)
        )
        for secret in secrets.scalars().all():
            await self.db.delete(secret)
        
        await self.db.commit()
    
    async def generate_backup_codes(self, user_id: uuid.UUID, count: int = 10) -> list[str]:
        """Generate single-use backup codes for account recovery"""
        import secrets
        
        codes = []
        for _ in range(count):
            code = secrets.token_hex(8).upper()
            codes.append(code)
            
            # Store hashed backup code
            bc = MFABackupCode(
                user_id=user_id,
                code_hash=hash_secret(code),
                created_at=datetime.now(timezone.utc)
            )
            self.db.add(bc)
        
        await self.db.commit()
        return codes
    
    async def verify_backup_code(self, user_id: uuid.UUID, code: str) -> bool:
        """Verify and consume a backup code"""
        code = code.strip().upper()
        
        backup_code = await self.db.execute(
            select(MFABackupCode)
            .where(MFABackupCode.user_id == user_id)
            .where(MFABackupCode.used == False)
        )
        
        for bc in backup_code.scalars().all():
            if bc.code_hash == hash_secret(code):
                bc.used = True
                bc.used_at = datetime.now(timezone.utc)
                await self.db.commit()
                return True
        
        return False
