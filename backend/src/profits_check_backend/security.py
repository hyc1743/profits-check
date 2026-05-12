from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from sqlalchemy import delete
from sqlalchemy.orm import Session

from profits_check_backend.config import AppSettings
from profits_check_backend.models import AppSetting, AuthSession


def mask_secret(value: str) -> str:
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


@dataclass(slots=True)
class SecretCipher:
    fernet: Fernet

    @classmethod
    def from_settings(cls, settings: AppSettings) -> SecretCipher:
        try:
            decoded = base64.urlsafe_b64decode(settings.app_encryption_key.encode())
        except (binascii.Error, ValueError) as exc:
            raise ValueError("APP_ENCRYPTION_KEY must be a valid Fernet key") from exc
        if len(decoded) != 32:
            raise ValueError("APP_ENCRYPTION_KEY must decode to 32 bytes")
        return cls(fernet=Fernet(settings.app_encryption_key.encode()))

    def encrypt(self, value: str) -> str:
        return self.fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return self.fernet.decrypt(value.encode()).decode()


PASSWORD_SETTING_KEY = "adminPasswordHash"
SESSION_COOKIE_NAME = "profits_check_session"
PBKDF2_ITERATIONS = 390_000


def utc_now() -> datetime:
    return datetime.now(UTC)


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_password(password: str, *, salt: bytes | None = None) -> dict[str, str | int]:
    password_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        password_salt,
        PBKDF2_ITERATIONS,
    )
    return {
        "algorithm": "pbkdf2_sha256",
        "iterations": PBKDF2_ITERATIONS,
        "salt": base64.urlsafe_b64encode(password_salt).decode(),
        "hash": base64.urlsafe_b64encode(digest).decode(),
    }


def verify_password(password: str, payload: dict[str, object]) -> bool:
    if payload.get("algorithm") != "pbkdf2_sha256":
        return False
    try:
        salt = base64.urlsafe_b64decode(str(payload["salt"]).encode())
        expected = base64.urlsafe_b64decode(str(payload["hash"]).encode())
        iterations = int(str(payload["iterations"]))
    except (KeyError, ValueError, binascii.Error):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def ensure_admin_password(session: Session, settings: AppSettings) -> None:
    if session.get(AppSetting, PASSWORD_SETTING_KEY) is not None:
        return
    if not settings.bootstrap_password:
        raise RuntimeError("PROFITS_CHECK_BOOTSTRAP_PASSWORD is required for first startup")
    import json

    session.add(
        AppSetting(
            key=PASSWORD_SETTING_KEY,
            value_json=json.dumps(hash_password(settings.bootstrap_password)),
        )
    )
    session.commit()


def create_session(session: Session, *, ttl_days: int) -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(32)
    auth_session = AuthSession(
        token_hash=hash_token(token),
        expires_at=utc_now() + timedelta(days=ttl_days),
    )
    session.add(auth_session)
    session.commit()
    session.refresh(auth_session)
    return token, auth_session


def get_valid_session(session: Session, token: str | None) -> AuthSession | None:
    if not token:
        return None
    auth_session = session.get(AuthSession, hash_token(token))
    if auth_session is None:
        return None
    expires_at = auth_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= utc_now():
        session.delete(auth_session)
        session.commit()
        return None
    return auth_session


def revoke_session(session: Session, token: str | None) -> None:
    if not token:
        return
    auth_session = session.get(AuthSession, hash_token(token))
    if auth_session is not None:
        session.delete(auth_session)
        session.commit()


def revoke_all_sessions(session: Session) -> None:
    session.execute(delete(AuthSession))
    session.commit()
