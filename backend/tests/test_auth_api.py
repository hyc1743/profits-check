from __future__ import annotations

from fastapi.testclient import TestClient


def test_business_apis_require_login(anonymous_client: TestClient) -> None:
    assert anonymous_client.get("/api/health").status_code == 200
    assert anonymous_client.get("/api/channels").status_code == 401
    assert anonymous_client.post("/api/snapshots/run").status_code == 401


def test_login_persists_session_and_logout_revokes_it(anonymous_client: TestClient) -> None:
    login_response = anonymous_client.post(
        "/api/auth/login",
        json={"password": "correct horse battery staple"},
    )

    assert login_response.status_code == 200
    assert login_response.json()["authenticated"] is True
    assert "profits_check_session" in login_response.cookies
    assert anonymous_client.get("/api/channels").status_code == 200

    session_response = anonymous_client.get("/api/auth/session")
    assert session_response.status_code == 200
    assert session_response.json()["authenticated"] is True

    logout_response = anonymous_client.post("/api/auth/logout")

    assert logout_response.status_code == 200
    assert anonymous_client.get("/api/channels").status_code == 401


def test_change_password_invalidates_existing_sessions(client: TestClient) -> None:
    change_response = client.put(
        "/api/auth/password",
        json={
            "currentPassword": "correct horse battery staple",
            "newPassword": "new correct horse battery staple",
        },
    )

    assert change_response.status_code == 200
    assert client.get("/api/channels").status_code == 401

    login_response = client.post(
        "/api/auth/login",
        json={"password": "new correct horse battery staple"},
    )

    assert login_response.status_code == 200
    assert client.get("/api/channels").status_code == 200


def test_secure_cookie_flag_is_configurable(anonymous_client: TestClient) -> None:
    response = anonymous_client.post(
        "/api/auth/login",
        json={"password": "correct horse battery staple"},
    )

    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()
    assert "Secure" not in set_cookie
