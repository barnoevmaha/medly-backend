"""Streaks are computed from days a student actually studied."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import engine
from app.models.user import User
from app.services.gamification import current_streak, touch_streak


def _user(email: str) -> User:
    with Session(engine) as session:
        return session.exec(select(User).where(User.email == email)).one()


def test_first_activity_starts_a_streak_of_one() -> None:
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == "admin@medly.dev")).one()
        user.streak_days = 0
        user.longest_streak = 0
        user.last_active_on = None
        session.add(user)
        session.commit()

        assert touch_streak(session, user) == 1
        # Twice on the same day is still one day.
        assert touch_streak(session, user) == 1


def test_consecutive_days_extend_it_and_a_gap_resets_it() -> None:
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == "admin@medly.dev")).one()

        user.streak_days = 4
        user.longest_streak = 4
        user.last_active_on = date.today() - timedelta(days=1)
        session.add(user)
        session.commit()
        assert touch_streak(session, user) == 5

        user.streak_days = 9
        user.longest_streak = 9
        user.last_active_on = date.today() - timedelta(days=3)
        session.add(user)
        session.commit()
        assert touch_streak(session, user) == 1
        # The best run is remembered even after the current one breaks.
        assert user.longest_streak == 9


def test_a_stale_streak_reads_as_zero() -> None:
    """A stored counter goes stale the moment a day is missed."""
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == "admin@medly.dev")).one()
        user.streak_days = 6
        user.last_active_on = date.today() - timedelta(days=4)
        session.add(user)
        session.commit()

    assert current_streak(_user("admin@medly.dev")) == 0


def test_answering_a_challenge_question_records_activity(
    client: TestClient, student_headers: dict
) -> None:
    detail = client.get("/api/challenges/pharmacology-master", headers=student_headers).json()
    question = next((q for q in detail["questions"] if not q["answered"]), None)
    if question is None:  # pragma: no cover — depends on test ordering
        return
    client.post(
        f"/api/challenges/{detail['slug']}/answer",
        json={"question_id": question["id"], "choice_id": question["choices"][0]["id"]},
        headers=student_headers,
    )
    profile = client.get("/api/profile", headers=student_headers).json()
    assert profile["streak_days"] >= 1
