from __future__ import annotations

import base64
from dataclasses import dataclass

from cryptography.fernet import Fernet

from profits_check_backend.config import AppSettings


def mask_secret(value: str) -> str:
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


@dataclass(slots=True)
class SecretCipher:
    fernet: Fernet

    @classmethod
    def from_settings(cls, settings: AppSettings) -> SecretCipher:
        raw = settings.app_encryption_key.encode()
        key = raw if len(raw) == 44 else base64.urlsafe_b64encode(raw.ljust(32, b"0")[:32])
        return cls(fernet=Fernet(key))

    def encrypt(self, value: str) -> str:
        return self.fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return self.fernet.decrypt(value.encode()).decode()
