"""Challenges: join, answer, score.

Two rules the endpoints exist to enforce:

  * Joining opens a real question set, it does not just flip a button.
  * A question pays out once. The answer row is the receipt; re-answering it
    replays the stored result and awards nothing, so refreshing cannot farm
    points.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, func, select

from app.db import get_session
from app.models.badge import UserBadge
from app.models.challenge import (
    Challenge,
    ChallengeAnswer,
    ChallengeChoice,
    ChallengeParticipant,
    ChallengeQuestion,
)
from app.models.user import User
from app.security import get_current_user
from app.services import gamification

router = APIRouter(prefix="/api/challenges", tags=["challenges"])


class ChoiceOut(BaseModel):
    id: int
    text: str


class QuestionOut(BaseModel):
    id: int
    order: int
    prompt: str
    points: int
    choices: List[ChoiceOut]
    # Optional film for imaging questions. `image_alt` carries the finding in
    # words so the question is answerable without seeing the panel.
    image_seed: Optional[str] = None
    image_alt: str = ""
    image_modality: str = "xray"
    # Present only once the question has been answered.
    answered: bool = False
    correct: Optional[bool] = None
    chosen_choice_id: Optional[int] = None
    correct_choice_id: Optional[int] = None
    explanation: Optional[str] = None


class ChallengeOut(BaseModel):
    id: int
    slug: str
    title: str
    description: str
    topic: str
    icon: str
    difficulty: str
    points: int
    question_count: int
    participants: int
    ends_at: Optional[datetime]
    joined: bool
    answered_count: int
    earned_points: int
    completed: bool


class ChallengeDetailOut(ChallengeOut):
    questions: List[QuestionOut]


class AnswerIn(BaseModel):
    question_id: int
    choice_id: int


class AnswerOut(BaseModel):
    question_id: int
    correct: bool
    correct_choice_id: int
    explanation: str
    points_awarded: int
    already_answered: bool
    earned_points: int
    answered_count: int
    question_count: int
    completed: bool
    total_points: int
    rank: int
    # Badge labels, ready to show as-is.
    new_badges: List[str] = []


def _questions(session: Session, challenge_id: int) -> List[ChallengeQuestion]:
    return list(
        session.exec(
            select(ChallengeQuestion)
            .where(ChallengeQuestion.challenge_id == challenge_id)
            .order_by(ChallengeQuestion.order)
        ).all()
    )


def _my_answers(session: Session, user_id: int, challenge_id: int) -> dict:
    rows = session.exec(
        select(ChallengeAnswer).where(
            ChallengeAnswer.user_id == user_id,
            ChallengeAnswer.challenge_id == challenge_id,
        )
    ).all()
    return {row.question_id: row for row in rows}


def _participants(session: Session, challenge: Challenge) -> int:
    real = int(
        session.exec(
            select(func.count()).select_from(ChallengeParticipant).where(
                ChallengeParticipant.challenge_id == challenge.id
            )
        ).one()
    )
    return challenge.base_participants + real


def _summary(session: Session, challenge: Challenge, user: User) -> ChallengeOut:
    questions = _questions(session, challenge.id or 0)
    answers = _my_answers(session, user.id or 0, challenge.id or 0)
    joined = session.exec(
        select(ChallengeParticipant).where(
            ChallengeParticipant.challenge_id == challenge.id,
            ChallengeParticipant.user_id == user.id,
        )
    ).first()
    earned = sum(row.points_awarded for row in answers.values())
    return ChallengeOut(
        id=challenge.id or 0,
        slug=challenge.slug,
        title=challenge.title,
        description=challenge.description,
        topic=challenge.topic,
        icon=challenge.icon,
        difficulty=challenge.difficulty,
        points=challenge.points,
        question_count=len(questions),
        participants=_participants(session, challenge),
        ends_at=challenge.ends_at,
        joined=joined is not None,
        answered_count=len(answers),
        earned_points=earned,
        completed=bool(questions) and len(answers) >= len(questions),
    )


def _get(session: Session, slug: str) -> Challenge:
    challenge = session.exec(select(Challenge).where(Challenge.slug == slug)).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    return challenge


@router.get("", response_model=List[ChallengeOut])
def list_challenges(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> List[ChallengeOut]:
    challenges = session.exec(
        select(Challenge).where(Challenge.published == True).order_by(Challenge.order)  # noqa: E712
    ).all()
    return [_summary(session, challenge, user) for challenge in challenges]


@router.get("/{slug}", response_model=ChallengeDetailOut)
def get_challenge(
    slug: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ChallengeDetailOut:
    challenge = _get(session, slug)
    base = _summary(session, challenge, user)
    questions = _questions(session, challenge.id or 0)
    answers = _my_answers(session, user.id or 0, challenge.id or 0)

    out: List[QuestionOut] = []
    for question in questions:
        choices = session.exec(
            select(ChallengeChoice)
            .where(ChallengeChoice.question_id == question.id)
            .order_by(ChallengeChoice.order)
        ).all()
        answer = answers.get(question.id or 0)
        correct_choice = next((c for c in choices if c.is_correct), None)
        out.append(
            QuestionOut(
                id=question.id or 0,
                order=question.order,
                prompt=question.prompt,
                points=question.points,
                choices=[ChoiceOut(id=c.id or 0, text=c.text) for c in choices],
                image_seed=question.image_seed,
                image_alt=question.image_alt,
                image_modality=question.image_modality,
                answered=answer is not None,
                correct=answer.correct if answer else None,
                chosen_choice_id=answer.choice_id if answer else None,
                # The correct answer is only ever sent after the question has
                # been answered — otherwise the response is the answer key.
                correct_choice_id=(correct_choice.id if answer and correct_choice else None),
                explanation=question.explanation if answer else None,
            )
        )

    return ChallengeDetailOut(**base.model_dump(), questions=out)


@router.post("/{slug}/join", response_model=ChallengeDetailOut)
def join(
    slug: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ChallengeDetailOut:
    challenge = _get(session, slug)
    existing = session.exec(
        select(ChallengeParticipant).where(
            ChallengeParticipant.challenge_id == challenge.id,
            ChallengeParticipant.user_id == user.id,
        )
    ).first()
    if not existing:
        session.add(
            ChallengeParticipant(challenge_id=challenge.id or 0, user_id=user.id or 0)
        )
        session.commit()
    return get_challenge(slug, session=session, user=user)


@router.post("/{slug}/answer", response_model=AnswerOut)
def answer(
    slug: str,
    payload: AnswerIn,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AnswerOut:
    challenge = _get(session, slug)
    question = session.get(ChallengeQuestion, payload.question_id)
    if not question or question.challenge_id != challenge.id:
        raise HTTPException(status_code=404, detail="Question not part of this challenge")

    choices = session.exec(
        select(ChallengeChoice).where(ChallengeChoice.question_id == question.id)
    ).all()
    chosen = next((c for c in choices if c.id == payload.choice_id), None)
    if not chosen:
        raise HTTPException(status_code=422, detail="That choice is not on this question")
    correct_choice = next((c for c in choices if c.is_correct), None)

    existing = session.exec(
        select(ChallengeAnswer).where(
            ChallengeAnswer.user_id == user.id,
            ChallengeAnswer.question_id == question.id,
        )
    ).first()

    already = existing is not None
    if existing:
        # Replay, do not re-score. This is the anti-refresh rule.
        correct = existing.correct
        awarded = 0
    else:
        correct = bool(chosen.is_correct)
        awarded = question.points if correct else 0
        session.add(
            ChallengeAnswer(
                user_id=user.id or 0,
                challenge_id=challenge.id or 0,
                question_id=question.id or 0,
                choice_id=chosen.id or 0,
                correct=correct,
                points_awarded=awarded,
            )
        )
        # Answering counts as joining, so a deep link cannot desync the two.
        participant = session.exec(
            select(ChallengeParticipant).where(
                ChallengeParticipant.challenge_id == challenge.id,
                ChallengeParticipant.user_id == user.id,
            )
        ).first()
        if not participant:
            participant = ChallengeParticipant(
                challenge_id=challenge.id or 0, user_id=user.id or 0
            )
            session.add(participant)
        session.commit()

        gamification.touch_streak(session, user)
        if awarded:
            gamification.award_points(session, user, awarded)

    answers = _my_answers(session, user.id or 0, challenge.id or 0)
    questions = _questions(session, challenge.id or 0)
    completed = len(answers) >= len(questions) and bool(questions)

    if completed:
        participant = session.exec(
            select(ChallengeParticipant).where(
                ChallengeParticipant.challenge_id == challenge.id,
                ChallengeParticipant.user_id == user.id,
            )
        ).first()
        if participant and not participant.completed_at:
            participant.completed_at = datetime.utcnow()
            participant.score = sum(row.points_awarded for row in answers.values())
            session.add(participant)
            session.commit()

    before = {
        row.badge_key
        for row in session.exec(select(UserBadge).where(UserBadge.user_id == user.id)).all()
    }
    held = gamification.sync_badges(session, user)
    # Human-readable, because this goes straight into a toast.
    new_badges = [
        gamification.BADGE_BY_KEY[key]["label"]
        for key in held
        if key not in before and key in gamification.BADGE_BY_KEY
    ]

    return AnswerOut(
        question_id=question.id or 0,
        correct=correct,
        correct_choice_id=correct_choice.id if correct_choice else 0,
        explanation=question.explanation,
        points_awarded=awarded,
        already_answered=already,
        earned_points=sum(row.points_awarded for row in answers.values()),
        answered_count=len(answers),
        question_count=len(questions),
        completed=completed,
        total_points=user.points,
        rank=gamification.rank_of(session, user),
        new_badges=new_badges,
    )
