"""Settings-backed endpoints: profile edits, password change, privacy."""
from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from app.routers.auth import AVATAR_MAX_CHARS
from app.seed import DEMO_PASSWORD

# 1x1 images, base64 of the real bytes. Literals rather than generated with
# Pillow, which is not a dependency and should not become one for a test.
PNG_1PX = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR42mPgaukBAAG2ARtz"
    "sg7aAAAAAElFTkSuQmCC"
)
WEBP_1PX = "UklGRjQAAABXRUJQVlA4ICgAAACQAQCdASoBAAEAAoBCJaACdLoAA5gA/us2/xbFIeh//ME/l18uuS4A"

PNG_AVATAR = f"data:image/png;base64,{PNG_1PX}"
WEBP_AVATAR = f"data:image/webp;base64,{WEBP_1PX}"


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


def test_avatar_is_stored_and_can_be_cleared(client: TestClient, student_headers: dict) -> None:
    set_it = client.patch(
        "/api/auth/me", json={"avatar_url": PNG_AVATAR}, headers=student_headers
    )
    assert set_it.status_code == 200, set_it.text
    assert set_it.json()["avatar_url"] == PNG_AVATAR

    # Persisted, not just echoed back — the sidebar reads it from here.
    assert client.get("/api/auth/me", headers=student_headers).json()["avatar_url"] == PNG_AVATAR

    # WebP is accepted too, not only the format the uploader happens to emit.
    swapped = client.patch(
        "/api/auth/me", json={"avatar_url": WEBP_AVATAR}, headers=student_headers
    )
    assert swapped.status_code == 200, swapped.text
    assert swapped.json()["avatar_url"] == WEBP_AVATAR

    # "Remove photo" is an empty string, not a separate endpoint.
    cleared = client.patch("/api/auth/me", json={"avatar_url": ""}, headers=student_headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["avatar_url"] == ""
    assert client.get("/api/auth/me", headers=student_headers).json()["avatar_url"] == ""


def test_avatar_must_be_an_uploaded_image(client: TestClient, student_headers: dict) -> None:
    """Anything that is not a png/jpeg/webp data URL is refused.

    The field is rendered in an <img src> for every viewer of a leaderboard or
    a chat room, so a remote URL, a script URL and an SVG are all rejected —
    SVG in particular is a document format with script and fetch capability
    and has no business being an avatar.
    """
    for value in (
        "https://example.com/pic.png",
        "javascript:alert(1)",
        "/avatar.jpg",
        "data:image/svg+xml;base64," + base64.b64encode(b"<svg onload='x()'/>").decode(),
        "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
        "data:text/html;base64,PGgxPmhpPC9oMT4=",
        f"data:image/png,{PNG_1PX}",  # data URL, but not declared base64
        "data:image/png;base64,!!!not-base64!!!",
    ):
        response = client.patch(
            "/api/auth/me", json={"avatar_url": value}, headers=student_headers
        )
        assert response.status_code == 422, f"{value[:40]!r} was accepted: {response.text}"


def test_avatar_bytes_must_match_the_declared_type(
    client: TestClient, student_headers: dict
) -> None:
    """PNG bytes labelled as a JPEG are a lie, whichever direction it goes."""
    response = client.patch(
        "/api/auth/me",
        json={"avatar_url": f"data:image/jpeg;base64,{PNG_1PX}"},
        headers=student_headers,
    )
    assert response.status_code == 422, response.text


def test_avatar_over_the_character_cap_is_rejected(
    client: TestClient, student_headers: dict
) -> None:
    """The cap is on the stored string, and it is a real ceiling.

    The frontend resizes to 512px at quality 0.85 before uploading, which puts
    a photograph near 80,000 characters and the pathological worst case near
    265,000 — so a payload past 400,000 did not come from that path.
    """
    oversized = "data:image/png;base64," + "A" * (AVATAR_MAX_CHARS + 1)
    assert len(oversized) > AVATAR_MAX_CHARS

    response = client.patch(
        "/api/auth/me", json={"avatar_url": oversized}, headers=student_headers
    )
    assert response.status_code == 422, response.text


def test_a_rejected_avatar_leaves_the_old_one_alone(
    client: TestClient, student_headers: dict
) -> None:
    """A failed upload must not blank the picture the user already had."""
    client.patch("/api/auth/me", json={"avatar_url": PNG_AVATAR}, headers=student_headers)

    rejected = client.patch(
        "/api/auth/me",
        json={"avatar_url": "data:image/svg+xml;base64,PHN2Zy8+"},
        headers=student_headers,
    )
    assert rejected.status_code == 422

    assert client.get("/api/auth/me", headers=student_headers).json()["avatar_url"] == PNG_AVATAR
    client.patch("/api/auth/me", json={"avatar_url": ""}, headers=student_headers)


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
