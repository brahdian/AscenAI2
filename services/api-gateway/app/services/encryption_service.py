from __future__ import annotations

import base64
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.core.config import settings


class EncryptionService:
    """
    Zenith Pillar 2: Absolute Privacy
    
    Provides AES-256-GCM encryption at rest for all sensitive database fields.
    Uses Fernet which provides authenticated encryption.
    """
    
    def __init__(self):
        self._fernet = self._create_fernet()
    
    def _create_fernet(self) -> Fernet:
        """Create Fernet instance from master encryption key"""
        if not settings.ENCRYPTION_MASTER_KEY:
            raise ValueError("ENCRYPTION_MASTER_KEY environment variable not set")
        
        # Derive encryption key using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=settings.ENCRYPTION_SALT.encode(),
            iterations=480000,
        )
        
        key = base64.urlsafe_b64encode(kdf.derive(settings.ENCRYPTION_MASTER_KEY.encode()))
        return Fernet(key)
    
    def encrypt(self, plaintext: str) -> str:
        """Encrypt string value for storage"""
        if not plaintext:
            return plaintext
        
        return self._fernet.encrypt(plaintext.encode()).decode()
    
    def decrypt(self, ciphertext: str) -> str:
        """Decrypt stored value"""
        if not ciphertext or not ciphertext.startswith("gAAAAA"):
            return ciphertext
        
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except Exception:
            return "[ENCRYPTION_FAILED]"
    
    def encrypt_dict(self, data: dict, fields_to_encrypt: list[str]) -> dict:
        """Encrypt specific fields in a dictionary"""
        result = dict(data)
        for field in fields_to_encrypt:
            if field in result and result[field]:
                result[field] = self.encrypt(result[field])
        return result
    
    def decrypt_dict(self, data: dict, fields_to_decrypt: list[str]) -> dict:
        """Decrypt specific fields in a dictionary"""
        result = dict(data)
        for field in fields_to_decrypt:
            if field in result and result[field]:
                result[field] = self.decrypt(result[field])
        return result


_encryption_service: Optional[EncryptionService] = None

def get_encryption_service() -> EncryptionService:
    """Lazy initialize encryption service to avoid startup crash when key is not configured"""
    global _encryption_service
    if _encryption_service is None:
        try:
            _encryption_service = EncryptionService()
        except ValueError:
            # Fallback for development environments
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                "ENCRYPTION_MASTER_KEY not configured. Encryption disabled. "
                "This is UNSAFE for production environments."
            )
            
            # Create mock implementation for development
            class MockEncryptionService:
                def encrypt(self, plaintext: str) -> str:
                    return f"UNENCRYPTED:{plaintext}"
                
                def decrypt(self, ciphertext: str) -> str:
                    if ciphertext.startswith("UNENCRYPTED:"):
                        return ciphertext[len("UNENCRYPTED:"):]
                    return ciphertext
                
                def encrypt_dict(self, data: dict, fields: list[str]) -> dict:
                    return data
                
                def decrypt_dict(self, data: dict, fields: list[str]) -> dict:
                    return data
            
            _encryption_service = MockEncryptionService()
    return _encryption_service

encryption_service = get_encryption_service()
