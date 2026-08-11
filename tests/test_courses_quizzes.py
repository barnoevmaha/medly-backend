from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_courses(client: TestClient, student_headers: dict) -> None:
    courses = client.get("/api/courses", headers=student_headers).json()
    assert len(courses) >= 3
    assert all("icon" in course for course in courses)


def test_course_detail_and_lessons(client: TestClient, student_headers: dict) -> None:
    course = client.get(
        "/api/courses/ai-in-medicine-foundations", headers=student_headers
    ).json()
    assert course["lessons"]
    lesson_id = course["lessons"][0]["id"]

    lesson = client.get(f"/api/courses/lessons/{lesson_id}", headers=student_headers).json()
    assert lesson["body_md"]

    done = client.post(
        f"/api/courses/lessons/{lesson_id}/complete", headers=student_headers
    ).json()
    assert done["status"] == "completed"


def test_quiz_never_leaks_answers(client: TestClient, student_headers: dict) -> None:
    quizzes = client.get(
        "/api/quizzes/course/ai-safety-and-ethics", headers=student_headers
    ).json()
    assert quizzes
    payload = str(quizzes)
    assert "is_correct" not in payload


def test_failing_quiz_is_reported_honestly(client: TestClient, student_headers: dict) -> None:
    quizzes = client.get(
        "/api/quizzes/course/ai-safety-and-ethics", headers=student_headers
    ).json()
    quiz = quizzes[0]
    # Answer every question with the first choice — deliberately wrong in most cases.
    answers = {str(q["id"]): [q["choices"][0]["id"]] for q in quiz["questions"]}
    result = client.post(
        f"/api/quizzes/{quiz['id']}/submit", json={"answers": answers}, headers=student_headers
    ).json()
    assert result["score"] < 100
    assert "results" in result and len(result["results"]) == len(quiz["questions"])


def test_multi_select_requires_exact_match(client: TestClient, student_headers: dict) -> None:
    """Selecting every option must not score points."""
    quizzes = client.get(
        "/api/quizzes/course/ai-safety-and-ethics", headers=student_headers
    ).json()
    quiz = quizzes[0]
    multi = [q for q in quiz["questions"] if q["kind"] == "multi"]
    assert multi, "expected at least one multi-select question"

    answers = {str(q["id"]): [c["id"] for c in q["choices"]] for q in multi}
    result = client.post(
        f"/api/quizzes/{quiz['id']}/submit", json={"answers": answers}, headers=student_headers
    ).json()
    for entry in result["results"]:
        if entry["question_id"] in [q["id"] for q in multi]:
            assert entry["correct"] is False


def test_my_attempts(client: TestClient, student_headers: dict) -> None:
    assert isinstance(client.get("/api/quizzes/attempts/me", headers=student_headers).json(), list)
