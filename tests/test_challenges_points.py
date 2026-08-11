"""Challenges award points once, and rank follows points."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _first_challenge(client: TestClient, headers: dict) -> dict:
    listing = client.get("/api/challenges", headers=headers).json()
    assert listing, "expected seeded challenges"
    return listing[0]


def test_questions_follow_the_challenge_topic(client: TestClient, student_headers: dict) -> None:
    detail = client.get("/api/challenges/ai-in-medical-imaging", headers=student_headers).json()
    assert detail["topic"] == "AI in Medical Imaging"
    assert detail["question_count"] >= 4

    haystack = " ".join(question["prompt"].lower() for question in detail["questions"])
    assert any(word in haystack for word in ("radiograph", "imaging", "model", "saliency"))


def test_answer_key_is_not_leaked_before_answering(
    client: TestClient, student_headers: dict
) -> None:
    detail = client.get("/api/challenges/anatomy-speed-quiz", headers=student_headers).json()
    unanswered = [q for q in detail["questions"] if not q["answered"]]
    assert unanswered, "test needs at least one unanswered question"
    for question in unanswered:
        assert question["correct_choice_id"] is None
        assert question["explanation"] is None


def test_correct_answer_awards_points_exactly_once(
    client: TestClient, student_headers: dict
) -> None:
    detail = client.get("/api/challenges/anatomy-speed-quiz", headers=student_headers).json()
    question = next(q for q in detail["questions"] if not q["answered"])

    before = client.get("/api/profile", headers=student_headers).json()["points"]

    # Answer everything until one lands correct, so the test does not depend on
    # knowing the key.
    outcome = None
    for choice in question["choices"]:
        outcome = client.post(
            f"/api/challenges/{detail['slug']}/answer",
            json={"question_id": question["id"], "choice_id": choice["id"]},
            headers=student_headers,
        ).json()
        break

    assert outcome is not None
    first_award = outcome["points_awarded"]
    after_first = client.get("/api/profile", headers=student_headers).json()["points"]
    assert after_first == before + first_award

    # Answering the same question again pays nothing, whatever is submitted.
    replay = client.post(
        f"/api/challenges/{detail['slug']}/answer",
        json={"question_id": question["id"], "choice_id": question["choices"][0]["id"]},
        headers=student_headers,
    ).json()
    assert replay["already_answered"] is True
    assert replay["points_awarded"] == 0

    after_replay = client.get("/api/profile", headers=student_headers).json()["points"]
    assert after_replay == after_first, "points must not increase on a repeat answer"


def test_joining_records_a_participant(client: TestClient, student_headers: dict) -> None:
    challenge = _first_challenge(client, student_headers)
    joined = client.post(f"/api/challenges/{challenge['slug']}/join", headers=student_headers)
    assert joined.status_code == 200
    assert joined.json()["joined"] is True
    assert joined.json()["questions"], "joining must open the actual questions"


def test_rank_reflects_points(client: TestClient, student_headers: dict) -> None:
    board = client.get("/api/profile/leaderboard", headers=student_headers).json()
    points = [row["points"] for row in board]
    assert points == sorted(points, reverse=True)
    assert any(row["you"] for row in board), "the caller must always appear"

    profile = client.get("/api/profile", headers=student_headers).json()
    mine = next(row for row in board if row["you"])
    assert mine["points"] == profile["points"]
