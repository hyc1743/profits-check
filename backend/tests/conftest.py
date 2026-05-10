from __future__ import annotations

import base64
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def backend_env(tmp_path: Path) -> Iterator[None]:
    os.environ["APP_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(b"0123456789ABCDEF0123456789ABCDEF").decode()
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'test.db'}"
    yield
    os.environ.pop("APP_ENCRYPTION_KEY", None)
    os.environ.pop("DATABASE_URL", None)


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
