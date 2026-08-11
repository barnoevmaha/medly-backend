from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"


def test_register_and_login(client: TestClient) -> None:
    payload = {
        "email": "newstudent@medly.dev",
        "password": "supersecret",
        "full_name": "New Student",
        "institution": "Test Med School",
    }
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "newstudent@medly.dev"
    assert me.json()["points"] == 0
    assert me.json()["is_premium"] is False


def test_duplicate_email_rejected(client: TestClient) -> None:
    payload = {"email": "student@medly.dev", "password": "supersecret", "full_name": "Dup"}
    assert client.post("/api/auth/register", json=payload).status_code == 400


def test_short_password_rejected(client: TestClient) -> None:
    payload = {"email": "short@medly.dev", "password": "abc", "full_name": "Short"}
    assert client.post("/api/auth/register", json=payload).status_code == 400


def test_bad_credentials(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login", data={"username": "student@medly.dev", "password": "wrong"}
    )
    assert response.status_code == 401


def test_protected_route_requires_token(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401
