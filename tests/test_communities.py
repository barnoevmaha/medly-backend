"""Community search scope, the premium gate, and chat."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_search_matches_name_and_description_only(
    client: TestClient, student_headers: dict
) -> None:
    by_name = client.get("/api/communities?q=cardiology", headers=student_headers).json()
    assert any(item["slug"] == "cardiology-club" for item in by_name)

    by_description = client.get("/api/communities?q=ECG", headers=student_headers).json()
    assert any(item["slug"] == "cardiology-club" for item in by_description)

    # "door-to-needle" appears in a seeded chat message in Neurology Network and
    # nowhere in any name or description. Community search must not reach it.
    by_message = client.get("/api/communities?q=door-to-needle", headers=student_headers).json()
    assert by_message == []


def test_non_premium_student_cannot_create_a_community(
    client: TestClient, student_headers: dict
) -> None:
    permissions = client.get("/api/communities/permissions", headers=student_headers).json()
    assert permissions["can_create"] is False

    response = client.post(
        "/api/communities",
        json={"name": "Unauthorised Club", "description": "Should never be created."},
        headers=student_headers,
    )
    assert response.status_code == 403
    assert "Premium" in response.json()["detail"]


def test_premium_student_can_create_a_community(
    client: TestClient, premium_headers: dict
) -> None:
    response = client.post(
        "/api/communities",
        json={
            "name": "Thoracic Imaging Journal Club",
            "description": "Weekly paper discussion on chest imaging and AI-assisted reading.",
            "specialty": "Radiology",
        },
        headers=premium_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["joined"] is True and body["owned"] is True


def test_chat_round_trip(client: TestClient, student_headers: dict) -> None:
    before = client.get("/api/communities/cardiology-club/messages", headers=student_headers)
    assert before.status_code == 200
    count = len(before.json())

    sent = client.post(
        "/api/communities/cardiology-club/messages",
        json={"body": "Reciprocal change in aVL was the giveaway for me too."},
        headers=student_headers,
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["mine"] is True

    after = client.get("/api/communities/cardiology-club/messages", headers=student_headers).json()
    assert len(after) == count + 1

    # Posting implies membership.
    detail = client.get("/api/communities/cardiology-club", headers=student_headers).json()
    assert detail["joined"] is True


def test_my_communities_only_lists_joined_ones(
    client: TestClient, student_headers: dict
) -> None:
    client.post("/api/communities/neurology-network/join", headers=student_headers)
    mine = client.get("/api/communities/mine", headers=student_headers).json()
    assert mine and all(item["joined"] for item in mine)
    assert any(item["slug"] == "neurology-network" for item in mine)
