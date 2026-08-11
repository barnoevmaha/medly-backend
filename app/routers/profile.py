"""Profile: rank, points, badges, activity and the leaderboard."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, func, select

from app.models.badge import UserBadge
from app.models.challenge import Challenge, ChallengeAnswer
from app.models.community import CommunityMember
from app.models.course import Lesson, LessonProgress
from app.models.enums import ProgressStatus, Role
from app.models.quiz import Quiz, QuizAttempt
from app.models.social import Article, ArticleComment, SavedItem
from app.models.user import User
from app.db import get_session
from app.security import get_current_user
from app.services import gamification

router = APIRouter(prefix="/api/profile", tags=["profile"])


class BadgeOut(BaseModel):
    key: str
    icon: str
    label: str
    hint: str
    earned: bool
    earned_at: Optional[datetime] = None


class ActivityOut(BaseModel):
    text: str
    detail: str
    points: Optional[int] = None
    at: datetime


class LeaderboardRow(BaseModel):
    rank: int
    user_id: int
    name: str
    institution: str
    points: int
    avatar_url: str
    you: bool


class ProfileOut(BaseModel):
    id: int
    name: str
    handle: str
    email: str
    role: Role
    institution: str
    year_of_study: Optional[int]
    avatar_url: str
    is_premium: bool
    points: int
    streak_days: int
    longest_streak: int
    rank: int
    total_users: int
    badge_count: int
    community_count: int
    saved_count: int
    lessons_completed: int
    challenges_completed: int
    comments: int
    joined_at: datetime


def _count(session: Session, model, *where) -> int:
    statement = select(func.count()).select_from(model)
    for clause in where:
        statement = statement.where(clause)
    return int(session.exec(statement).one())


@router.get("", response_model=ProfileOut)
def get_profile(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProfileOut:
    gamification.sync_badges(session, user)
    user_id = user.id or 0

    completed_challenges = int(
        session.exec(
            select(func.count(func.distinct(ChallengeAnswer.challenge_id))).where(
                ChallengeAnswer.user_id == user_id
            )
        ).one()
    )

    handle = "@" + user.email.split("@")[0].replace(".", "")
    return ProfileOut(
        id=user_id,
        name=user.full_name,
        handle=handle,
        email=user.email,
        role=user.role,
        institution=user.institution or "",
        year_of_study=user.year_of_study,
        avatar_url=user.avatar_url or "",
        is_premium=bool(user.is_premium),
        points=user.points or 0,
        streak_days=gamification.current_streak(user),
        longest_streak=user.longest_streak or 0,
        rank=gamification.rank_of(session, user),
        total_users=gamification.total_users(session),
        badge_count=_count(session, UserBadge, UserBadge.user_id == user_id),
        community_count=_count(session, CommunityMember, CommunityMember.user_id == user_id),
        saved_count=_count(session, SavedItem, SavedItem.user_id == user_id),
        lessons_completed=_count(
            session,
            LessonProgress,
            LessonProgress.user_id == user_id,
            LessonProgress.status == ProgressStatus.COMPLETED,
        ),
        challenges_completed=completed_challenges,
        comments=_count(session, ArticleComment, ArticleComment.user_id == user_id),
        joined_at=user.created_at,
    )


@router.get("/badges", response_model=List[BadgeOut])
def badges(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> List[BadgeOut]:
    gamification.sync_badges(session, user)
    earned = {
        row.badge_key: row.earned_at
        for row in session.exec(
            select(UserBadge).where(UserBadge.user_id == user.id)
        ).all()
    }
    return [
        BadgeOut(
            key=badge["key"],
            icon=badge["icon"],
            label=badge["label"],
            hint=badge["hint"],
            earned=badge["key"] in earned,
            earned_at=earned.get(badge["key"]),
        )
        for badge in gamification.BADGES
    ]


@router.get("/leaderboard", response_model=List[LeaderboardRow])
def leaderboard(
    limit: int = 25,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> List[LeaderboardRow]:
    """Ordered by real points. If the caller is off the end, they are appended."""
    people = gamification.leaderboard(session, limit=limit)
    rows = [
        LeaderboardRow(
            rank=index + 1,
            user_id=person.id or 0,
            name=person.full_name,
            institution=person.institution or "",
            points=person.points or 0,
            avatar_url=person.avatar_url or "",
            you=person.id == user.id,
        )
        for index, person in enumerate(people)
    ]
    if not any(row.you for row in rows):
        rows.append(
            LeaderboardRow(
                rank=gamification.rank_of(session, user),
                user_id=user.id or 0,
                name=user.full_name,
                institution=user.institution or "",
                points=user.points or 0,
                avatar_url=user.avatar_url or "",
                you=True,
            )
        )
    return rows


@router.get("/activity", response_model=List[ActivityOut])
def activity(
    limit: int = 12,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> List[ActivityOut]:
    """Recent activity, assembled from rows that actually exist."""
    user_id = user.id or 0
    items: List[ActivityOut] = []

    answers = session.exec(
        select(ChallengeAnswer)
        .where(ChallengeAnswer.user_id == user_id)
        .order_by(ChallengeAnswer.answered_at.desc())  # type: ignore[union-attr]
        .limit(limit)
    ).all()
    challenge_titles = {
        challenge.id: challenge.title
        for challenge in session.exec(select(Challenge)).all()
    }
    for row in answers:
        items.append(
            ActivityOut(
                text=f"Answered a question in {challenge_titles.get(row.challenge_id, 'a challenge')}",
                detail="Correct" if row.correct else "Incorrect",
                points=row.points_awarded or None,
                at=row.answered_at,
            )
        )

    attempts = session.exec(
        select(QuizAttempt)
        .where(QuizAttempt.user_id == user_id)
        .order_by(QuizAttempt.submitted_at.desc())  # type: ignore[union-attr]
        .limit(limit)
    ).all()
    quiz_titles = {quiz.id: quiz.title for quiz in session.exec(select(Quiz)).all()}
    for row in attempts:
        items.append(
            ActivityOut(
                text=quiz_titles.get(row.quiz_id, "Quiz"),
                detail=f"Scored {row.score}% — {'passed' if row.passed else 'not passed'}",
                points=None,
                at=row.submitted_at,
            )
        )

    progress = session.exec(
        select(LessonProgress)
        .where(
            LessonProgress.user_id == user_id,
            LessonProgress.status == ProgressStatus.COMPLETED,
        )
        .order_by(LessonProgress.completed_at.desc())  # type: ignore[union-attr]
        .limit(limit)
    ).all()
    lesson_titles = {lesson.id: lesson.title for lesson in session.exec(select(Lesson)).all()}
    for row in progress:
        items.append(
            ActivityOut(
                text=f"Completed lesson: {lesson_titles.get(row.lesson_id, 'Lesson')}",
                detail="AI Training",
                points=None,
                at=row.completed_at or datetime.utcnow(),
            )
        )

    comments = session.exec(
        select(ArticleComment)
        .where(ArticleComment.user_id == user_id)
        .order_by(ArticleComment.created_at.desc())  # type: ignore[union-attr]
        .limit(limit)
    ).all()
    article_titles = {
        article.id: article.title for article in session.exec(select(Article)).all()
    }
    for row in comments:
        items.append(
            ActivityOut(
                text=f"Commented on {article_titles.get(row.article_id, 'an article')}",
                detail="Feed",
                points=None,
                at=row.created_at,
            )
        )

    items.sort(key=lambda item: item.at, reverse=True)
    return items[:limit]


@router.post("/premium", response_model=ProfileOut)
def activate_premium(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProfileOut:
    """Demo checkout. No payment provider is wired up, and none is pretended.

    The flag it sets is the same one the community-creation check reads, so the
    upgrade genuinely changes what the account can do.
    """
    user.is_premium = True
    session.add(user)
    session.commit()
    session.refresh(user)
    return get_profile(session=session, user=user)


@router.delete("/premium", response_model=ProfileOut)
def cancel_premium(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProfileOut:
    user.is_premium = False
    session.add(user)
    session.commit()
    session.refresh(user)
    return get_profile(session=session, user=user)
