from __future__ import annotations

import base64

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from profits_check_backend.config import AppSettings
from profits_check_backend.providers.http import PROVIDER_HTTP_LIMITS, PROVIDER_HTTP_TIMEOUT
from profits_check_backend.providers.registry import build_provider
from profits_check_backend.security import SecretCipher


def test_encryption_key_must_be_valid_fernet_key() -> None:
    with pytest.raises(ValueError, match="APP_ENCRYPTION_KEY"):
        SecretCipher.from_settings(AppSettings(app_encryption_key="not-a-fernet-key"))

    cipher = SecretCipher.from_settings(
        AppSettings(app_encryption_key=Fernet.generate_key().decode())
    )

    encrypted = cipher.encrypt("secret")
    assert cipher.decrypt(encrypted) == "secret"


def test_public_config_rejects_secret_fields(client: TestClient) -> None:
    response = client.post(
        "/api/channels",
        json={
            "provider": "binance",
            "kind": "cex",
            "name": "Leaky Binance",
            "publicConfig": {"apiSecret": "must-not-be-public"},
            "secretConfig": {"apiKey": "key", "apiSecret": "secret"},
        },
    )

    assert response.status_code == 422


def test_channel_payload_requires_provider(client: TestClient) -> None:
    response = client.post(
        "/api/channels",
        json={
            "kind": "cex",
            "name": "Missing Provider",
            "publicConfig": {},
            "secretConfig": {},
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("provider", "public_config"),
    [
        ("binance", {"baseUrl": "http://127.0.0.1:8080"}),
        ("onchain", {"baseUrl": "http://169.254.169.254"}),
        ("aster", {"rpcUrl": "http://10.0.0.1:8545"}),
    ],
)
def test_custom_provider_urls_are_rejected_by_default(
    client: TestClient,
    provider: str,
    public_config: dict[str, str],
) -> None:
    response = client.post(
        "/api/channels",
        json={
            "provider": provider,
            "kind": "cex",
            "name": "Unsafe URL",
            "publicConfig": public_config,
            "secretConfig": {},
        },
    )

    assert response.status_code == 422


def test_cookie_secure_flag_can_be_enabled(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(
        "APP_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"0123456789ABCDEF0123456789ABCDEF").decode()
    )
    monkeypatch.setenv("PROFITS_CHECK_BOOTSTRAP_PASSWORD", "correct horse battery staple")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'secure-cookie.db'}")
    monkeypatch.setenv("PROFITS_CHECK_COOKIE_SECURE", "true")

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        response = test_client.post(
            "/api/auth/login",
            json={"password": "correct horse battery staple"},
        )

    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


def test_registry_rejects_provider_url_override_by_default() -> None:
    with pytest.raises(ValueError, match="Custom provider URLs are disabled"):
        build_provider(
            provider_type="binance",
            channel_name="Binance",
            config={"baseUrl": "https://attacker.example"},
            secrets={"apiKey": "key", "apiSecret": "secret"},
        )


def test_provider_http_client_has_bounded_timeout_and_connections() -> None:
    assert PROVIDER_HTTP_TIMEOUT.connect == 5
    assert PROVIDER_HTTP_TIMEOUT.read == 15
    assert PROVIDER_HTTP_LIMITS.max_connections == 10
    assert PROVIDER_HTTP_LIMITS.max_keepalive_connections == 5
