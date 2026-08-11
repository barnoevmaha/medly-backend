"""Settings-backed endpoints: profile edits, password change, privacy."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.seed import DEMO_PASSWORD


def test_account_details_can_be_updated(client: TestClient, student_headers: dict) -> None:
    response = client.patch(
        "/api/auth/me",
        json={"full_name": "Alex T. Johnson", "institution": "Columbia", "year_of_study": 4},
        headers=student_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["full_name"] == "Alex T. Johnson"
    assert body["year_of_study"] == 4

    # Persisted, not just echoed back.
    again = client.get("/api/auth/me", headers=student_headers).json()
    assert again["full_name"] == "Alex T. Johnson"


def test_settings_cannot_grant_privileges(client: TestClient, student_headers: dict) -> None:
    before = client.get("/api/auth/me", headers=student_headers).json()
    client.patch(
        "/api/auth/me",
        json={"role": "admin", "is_premium": True, "points": 999999},
        headers=student_headers,
    )
    after = client.get("/api/auth/me", headers=student_headers).json()
    assert after["role"] == before["role"]
    assert after["is_premium"] == before["is_premium"]
    assert after["points"] == before["points"]


def test_year_of_study_is_validated(client: TestClient, student_headers: dict) -> None:
    response = client.patch(
        "/api/auth/me", json={"year_of_study": 99}, headers=student_headers
    )
    assert response.status_code == 422


def test_hiding_from_the_leaderboard_works(client: TestClient, premium_headers: dict) -> None:
    me = client.get("/api/auth/me", headers=premium_headers).json()

    client.patch("/api/auth/me", json={"show_on_leaderboard": False}, headers=premium_headers)
    board = client.get("/api/profile/leaderboard", headers=premium_headers).json()
    visible = [row for row in board if row["user_id"] == me["id"] and not row["you"]]
    assert not visible, "a hidden user must not appear as a normal row"

    # Their own rank is still calculated and returned to them.
    profile = client.get("/api/profile", headers=premium_headers).json()
    assert profile["rank"] >= 1

    client.patch("/api/auth/me", json={"show_on_leaderboard": True}, headers=premium_headers)


def test_password_change_requires_the_current_password(
    client: TestClient, instructor_headers: dict
) -> None:
    wrong = client.post(
        "/api/auth/password",
        json={"current_password": "not-the-password", "new_password": "brand-new-secret"},
        headers=instructor_headers,
    )
    assert wrong.status_code == 400

    short = client.post(
        "/api/auth/password",
        json={"current_password": DEMO_PASSWORD, "new_password": "short"},
        headers=instructor_headers,
    )
    assert short.status_code == 400

    changed = client.post(
        "/api/auth/password",
        json={"current_password": DEMO_PASSWORD, "new_password": "brand-new-secret"},
        headers=instructor_headers,
    )
    assert changed.status_code == 204

    # The new password works and the old one does not.
    assert (
        client.post(
            "/api/auth/login",
            data={"username": "instructor@medly.dev", "password": "brand-new-secret"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/auth/login",
            data={"username": "instructor@medly.dev", "password": DEMO_PASSWORD},
        ).status_code
        == 401
    )

    # Put it back so the rest of the suite and the demo accounts still work.
    token = client.post(
        "/api/auth/login",
        data={"username": "instructor@medly.dev", "password": "brand-new-secret"},
    ).json()["access_token"]
    restored = client.post(
        "/api/auth/password",
        json={"current_password": "brand-new-secret", "new_password": DEMO_PASSWORD},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert restored.status_code == 204


def test_assistant_history_can_be_cleared_without_touching_the_audit_log(
    client: TestClient, premium_headers: dict
) -> None:
    client.post(
        "/api/assistant/chat",
        json={"message": "What is automation bias?"},
        headers=premium_headers,
    )
    audit_before = len(client.get("/api/governance/audit", headers=premium_headers).json())

    cleared = client.delete("/api/assistant/history", headers=premium_headers)
    assert cleared.status_code == 204

    audit_after = len(client.get("/api/governance/audit", headers=premium_headers).json())
    assert audit_after >= audit_before, "clearing chat history must not erase the audit trail"
