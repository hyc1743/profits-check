from __future__ import annotations

from pathlib import Path

from profits_check_backend.config import AppSettings
from profits_check_backend.db import build_session_factory, init_database
from profits_check_backend.security import SecretCipher


def test_settings_load_from_environment() -> None:
    settings = AppSettings()

    assert settings.database_url.endswith(".db")
    assert settings.scheduler_enabled is True


def test_secret_cipher_round_trip() -> None:
    cipher = SecretCipher.from_settings(AppSettings())

    encrypted = cipher.encrypt("binance-secret")

    assert encrypted != "binance-secret"
    assert cipher.decrypt(encrypted) == "binance-secret"


def test_sqlite_parent_directory_is_created_for_missing_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PROFITS_CHECK_DATABASE_URL", raising=False)
    target_dir = tmp_path / "missing" / "nested"
    settings = AppSettings(
        database_url=f"sqlite:///{target_dir / 'app.db'}",
    )

    session_factory = build_session_factory(settings)
    init_database(session_factory)

    assert target_dir.exists()
    assert (target_dir / "app.db").exists()
