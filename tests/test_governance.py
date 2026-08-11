from __future__ import annotations

from fastapi.testclient import TestClient


def test_standard_is_published(client: TestClient) -> None:
    body = client.get("/api/governance/standard").json()
    assert len(body["rules"]) >= 6
    assert all("enforced_by" in rule for rule in body["rules"])


def test_assistant_activity_is_audited(client: TestClient, student_headers: dict) -> None:
    before = len(client.get("/api/governance/audit", headers=student_headers).json())
    client.post(
        "/api/assistant/chat",
        json={"message": "What is dataset shift?"},
        headers=student_headers,
    )
    after = client.get("/api/governance/audit", headers=student_headers).json()
    assert len(after) > before


def test_blocked_requests_are_audited(client: TestClient, student_headers: dict) -> None:
    client.post(
        "/api/assistant/chat",
        json={"message": "Should I prescribe antibiotics for my patient?"},
        headers=student_headers,
    )
    blocked = client.get(
        "/api/governance/audit?only_blocked=true", headers=student_headers
    ).json()
    assert blocked
    assert all(event["blocked"] for event in blocked)


def test_student_only_sees_own_events(client: TestClient, student_headers: dict) -> None:
    me = client.get("/api/auth/me", headers=student_headers).json()
    events = client.get("/api/governance/audit?limit=200", headers=student_headers).json()
    assert all(e["user_id"] == me["id"] for e in events)


def test_instructor_sees_everyone(client: TestClient, instructor_headers: dict, student_headers: dict) -> None:
    client.post(
        "/api/assistant/chat", json={"message": "What is calibration?"}, headers=student_headers
    )
    events = client.get("/api/governance/audit?limit=200", headers=instructor_headers).json()
    assert len({e["user_id"] for e in events}) > 1


def test_summary_shape(client: TestClient, instructor_headers: dict) -> None:
    body = client.get("/api/governance/summary", headers=instructor_headers).json()
    for key in (
        "total_ai_interactions",
        "override_rate",
        "block_rate",
        "disclaimer_coverage",
        "confidence_threshold",
    ):
        assert key in body
    assert 0.0 <= body["override_rate"] <= 1.0
    # Rule 3 means coverage must be total.
    assert body["disclaimer_coverage"] == 1.0


def test_timeseries_is_contiguous(client: TestClient, instructor_headers: dict) -> None:
    points = client.get("/api/governance/timeseries?days=7", headers=instructor_headers).json()
    assert len(points) == 8
    assert points == sorted(points, key=lambda p: p["date"])


def test_students_cannot_clear_reviews(client: TestClient, student_headers: dict) -> None:
    events = client.get("/api/governance/audit", headers=student_headers).json()
    assert events
    response = client.post(
        f"/api/governance/audit/{events[0]['id']}/review", headers=student_headers
    )
    assert response.status_code == 403
