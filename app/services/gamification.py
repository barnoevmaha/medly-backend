"""Points, rank and badges — all derived from rows that actually exist.

Nothing here invents a number. Points come from challenge answers, quizzes and
lesson completions; rank is a position in the users table ordered by points;
badges are awarded from counts of real activity.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from sqlmodel import Session, func, select

from app.models.analysis import AnalysisJob
from app.models.badge import UserBadge
from app.models.community import CommunityMember
from app.models.course import LessonProgress
from app.models.enums import ProgressStatus
from app.models.social import ArticleComment, SavedItem
from app.models.user import User

# Order matters: this is the order badges render in.
BADGES: List[Dict[str, str]] = [
    {"key": "first_lesson", "icon": "sprout", "label": "First Steps",
     "hint": "Complete your first lesson"},
    {"key": "quiz_champion", "icon": "target", "label": "Quiz Champion",
     "hint": "Earn 300 points from challenges"},
    {"key": "point_hunter", "icon": "trophy", "label": "Point Hunter",
     "hint": "Reach 1,000 total points"},
    {"key": "bookworm", "icon": "library", "label": "Bookworm",
     "hint": "Save 5 items from the library"},
    {"key": "contributor", "icon": "message-square", "label": "Contributor",
     "hint": "Leave 3 comments"},
    {"key": "connector", "icon": "users", "label": "Connector",
     "hint": "Join 3 communities"},
    {"key": "scholar", "icon": "graduation-cap", "label": "Scholar",
     "hint": "Complete 8 lessons"},
    {"key": "second_reader", "icon": "scan-eye", "label": "Second Reader",
     "hint": "Commit a decision on 3 imaging cases"},
    {"key": "consistent", "icon": "flame", "label": "Consistent",
     "hint": "Study on 7 different days in a row"},
]

BADGE_BY_KEY = {badge["key"]: badge for badge in BADGES}


def _count(session: Session, model, *where) -> int:
    statement = select(func.count()).select_from(model)
    for clause in where:
        statement = statement.where(clause)
    return int(session.exec(statement).one())


def touch_streak(session: Session, user: User) -> int:
    """Record that the user studied today and return the current streak.

    Called from the places that represent actual study — answering a challenge
    question, completing a lesson, submitting a quiz. Deliberately *not* called
    on page loads: a streak that increments for opening the app measures
    nothing and rewards nothing.
    """
    today = datetime.utcnow().date()
    last = user.last_active_on

    if last == today:
        return user.streak_days or 0
    if last is not None and (today - last).days == 1:
        user.streak_days = (user.streak_days or 0) + 1
    else:
        # First activity, or a missed day: the streak restarts at today.
        user.streak_days = 1

    user.last_active_on = today
    user.longest_streak = max(user.longest_streak or 0, user.streak_days)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user.streak_days


def current_streak(user: User) -> int:
    """The streak as it stands today, without writing anything.

    A stored streak goes stale the moment a day passes without activity, so a
    read has to check the date rather than trust the counter.
    """
    if not user.last_active_on:
        return 0
    gap = (datetime.utcnow().date() - user.last_active_on).days
    return user.streak_days or 0 if gap <= 1 else 0


def award_points(session: Session, user: User, amount: int) -> int:
    """Add points and return the new total. Never goes negative."""
    if amount <= 0:
        return user.points
    user.points = max(0, (user.points or 0) + amount)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user.points


def earned_keys(session: Session, user: User) -> List[str]:
    """Which badges the user qualifies for right now."""
    user_id = user.id or 0
    lessons_done = _count(
        session,
        LessonProgress,
        LessonProgress.user_id == user_id,
        LessonProgress.status == ProgressStatus.COMPLETED,
    )
    saved = _count(session, SavedItem, SavedItem.user_id == user_id)
    comments = _count(session, ArticleComment, ArticleComment.user_id == user_id)
    communities = _count(session, CommunityMember, CommunityMember.user_id == user_id)
    decisions = _count(
        session,
        AnalysisJob,
        AnalysisJob.user_id == user_id,
        AnalysisJob.final_decision.is_not(None),  # type: ignore[union-attr]
    )

    from app.models.challenge import ChallengeAnswer

    challenge_points = int(
        session.exec(
            select(func.coalesce(func.sum(ChallengeAnswer.points_awarded), 0)).where(
                ChallengeAnswer.user_id == user_id
            )
        ).one()
    )

    tests = {
        "first_lesson": lessons_done >= 1,
        "quiz_champion": challenge_points >= 300,
        "consistent": (user.longest_streak or 0) >= 7,
        "point_hunter": (user.points or 0) >= 1000,
        "bookworm": saved >= 5,
        "contributor": comments >= 3,
        "connector": communities >= 3,
        "scholar": lessons_done >= 8,
        "second_reader": decisions >= 3,
    }
    return [key for key, passed in tests.items() if passed]


def sync_badges(session: Session, user: User) -> List[str]:
    """Persist any newly earned badge and return every badge the user holds."""
    held = {
        row.badge_key
        for row in session.exec(
            select(UserBadge).where(UserBadge.user_id == user.id)
        ).all()
    }
    for key in earned_keys(session, user):
        if key not in held:
            session.add(UserBadge(user_id=user.id or 0, badge_key=key,
                                  earned_at=datetime.utcnow()))
            held.add(key)
    session.commit()
    return [badge["key"] for badge in BADGES if badge["key"] in held]


def rank_of(session: Session, user: User) -> int:
    """1-based position by points. Ties resolve by earliest account."""
    ahead = int(
        session.exec(
            select(func.count()).select_from(User).where(
                User.is_active == True,  # noqa: E712
                User.points > (user.points or 0),
            )
        ).one()
    )
    return ahead + 1


def leaderboard(session: Session, limit: int = 25) -> List[User]:
    """The public board.

    Users who opted out in Settings are omitted here. `rank_of` deliberately
    still counts them, so opting out hides your name from other people without
    quietly inflating everyone else's position.
    """
    return list(
        session.exec(
            select(User)
            .where(
                User.is_active == True,  # noqa: E712
                User.show_on_leaderboard == True,  # noqa: E712
            )
            .order_by(User.points.desc(), User.created_at.asc())  # type: ignore[union-attr]
            .limit(limit)
        ).all()
    )


def total_users(session: Session) -> int:
    return _count(session, User, User.is_active == True)  # noqa: E712


def find_user(session: Session, user_id: Optional[int]) -> Optional[User]:
    if user_id is None:
        return None
    return session.get(User, user_id)
