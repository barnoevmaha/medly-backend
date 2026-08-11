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
from app.lang import get_lang
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
from app.services import gamification, localize

router = APIRouter(prefix="/api/challenges", tags=["challenges"])


class ChoiceOut(BaseModel):
    id: int
    text: str


class QuestionOut(BaseModel):
    id: int
    order: int
    prompt: str
    points: int
    kind: str
    choices: List[ChoiceOut]
    # Optional film for imaging questions. `image_alt` carries the finding in
    # words so the question is answerable without seeing the panel.
    image_seed: Optional[str] = None
    image_url: Optional[str] = None
    image_alt: str = ""
    image_modality: str = "xray"
    # Present only once the question has been answered.
    answered: bool = False
    correct: Optional[bool] = None
    chosen_choice_id: Optional[int] = None
    given_value: Optional[float] = None
    given_text: str = ""
    correct_choice_id: Optional[int] = None
    explanation: Optional[str] = None


class ChallengeOut(BaseModel):
    id: int
    slug: str
    title: str
    description: str
    topic: str
    icon: str
    cover: str
    difficulty: str
    points: int
    question_count: int
    participants: int
    ends_at: Optional[datetime]
    joined: bool
    answered_count: int
    earned_points: int
    completed: bool
    thumbnail: str
    duration_minutes: int


class ChallengeDetailOut(ChallengeOut):
    questions: List[QuestionOut]


class AnswerIn(BaseModel):
    question_id: int
    # mcq / true_false questions answer by choice; numerical and short-answer
    # questions carry their answer instead.
    choice_id: Optional[int] = None
    answer_value: Optional[float] = None
    answer_text: Optional[str] = None


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


def _summary(session: Session, challenge: Challenge, user: User, lang: str) -> ChallengeOut:
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
        title=localize.read(challenge, "title", lang),
        description=localize.read(challenge, "description", lang),
        topic=localize.read(challenge, "topic", lang),
        icon=challenge.icon,
        cover=challenge.cover,
        difficulty=challenge.difficulty,
        points=challenge.points,
        question_count=len(questions),
        participants=_participants(session, challenge),
        ends_at=challenge.ends_at,
        joined=joined is not None,
        answered_count=len(answers),
        earned_points=earned,
        completed=bool(questions) and len(answers) >= len(questions),
        thumbnail=challenge.thumbnail,
        duration_minutes=challenge.duration_minutes,
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
    lang: str = Depends(get_lang),
) -> List[ChallengeOut]:
    challenges = session.exec(
        select(Challenge).where(Challenge.published == True).order_by(Challenge.order)  # noqa: E712
    ).all()
    localize.ensure_fields(session, localize.fields_for(challenges, ("title", "description", "topic")), lang)
    return [_summary(session, challenge, user, lang) for challenge in challenges]


@router.get("/{slug}", response_model=ChallengeDetailOut)
def get_challenge(
    slug: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> ChallengeDetailOut:
    challenge = _get(session, slug)
    localize.ensure_fields(session, [(challenge, "title"), (challenge, "description"), (challenge, "topic")], lang)
    base = _summary(session, challenge, user, lang)
    questions = _questions(session, challenge.id or 0)
    answers = _my_answers(session, user.id or 0, challenge.id or 0)

    # Every question and choice on this challenge, translated together in one
    # batch — a cold cache on a five-question challenge is ~30 short strings,
    # done in parallel rather than one request per field.
    all_choices: dict[int, List[ChallengeChoice]] = {}
    for question in questions:
        all_choices[question.id or 0] = list(
            session.exec(
                select(ChallengeChoice)
                .where(ChallengeChoice.question_id == question.id)
                .order_by(ChallengeChoice.order)
            ).all()
        )
    refs = localize.fields_for(questions, ("prompt", "explanation"))
    for choices in all_choices.values():
        refs += localize.fields_for(choices, ("text",))
    localize.ensure_fields(session, refs, lang)

    out: List[QuestionOut] = []
    for question in questions:
        choices = all_choices[question.id or 0]
        answer = answers.get(question.id or 0)
        correct_choice = next((c for c in choices if c.is_correct), None)
        out.append(
            QuestionOut(
                id=question.id or 0,
                order=question.order,
                prompt=localize.read(question, "prompt", lang),
                points=question.points,
                kind=question.kind,
                choices=[
                    ChoiceOut(id=c.id or 0, text=localize.read(c, "text", lang)) for c in choices
                ],
                image_seed=question.image_seed,
                image_url=question.image_url,
                image_alt=question.image_alt,
                image_modality=question.image_modality,
                answered=answer is not None,
                correct=answer.correct if answer else None,
                chosen_choice_id=answer.choice_id if answer else None,
                given_value=answer.answer_value if answer else None,
                given_text=answer.answer_text or "" if answer else "",
                # The correct answer is only ever sent after the question has
                # been answered — otherwise the response is the answer key.
                correct_choice_id=(correct_choice.id if answer and correct_choice else None),
                explanation=localize.read(question, "explanation", lang) if answer else None,
            )
        )

    return ChallengeDetailOut(**base.model_dump(), questions=out)


@router.post("/{slug}/join", response_model=ChallengeDetailOut)
def join(
    slug: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
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
    return get_challenge(slug, session=session, user=user, lang=lang)


@router.post("/{slug}/answer", response_model=AnswerOut)
def answer(
    slug: str,
    payload: AnswerIn,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> AnswerOut:
    challenge = _get(session, slug)
    question = session.get(ChallengeQuestion, payload.question_id)
    if not question or question.challenge_id != challenge.id:
        raise HTTPException(status_code=404, detail="Question not part of this challenge")

    choices = session.exec(
        select(ChallengeChoice).where(ChallengeChoice.question_id == question.id)
    ).all()
    chosen: Optional[ChallengeChoice] = None
    given_value: Optional[float] = None
    given_text = ""

    if question.kind in ("mcq", "true_false"):
        chosen = next((c for c in choices if c.id == payload.choice_id), None)
        if not chosen:
            raise HTTPException(status_code=422, detail="That choice is not on this question")
    elif question.kind == "numerical":
        if payload.answer_value is None:
            raise HTTPException(status_code=422, detail="A number is required for this question")
        given_value = float(payload.answer_value)
    elif question.kind == "short":
        given_text = (payload.answer_text or "").strip()
        if not given_text:
            raise HTTPException(status_code=422, detail="An answer is required for this question")
    else:
        raise HTTPException(status_code=422, detail=f"Unknown question kind '{question.kind}'")

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
        if chosen is not None:
            correct = bool(chosen.is_correct)
        elif question.kind == "numerical":
            target = question.answer_value
            correct = target is not None and abs(float(target) - given_value) <= max(
                0.05, abs(float(target)) * 0.01
            )
        else:
            expected = (question.answer_text or "").strip().lower()
            given = given_text.lower()
            correct = bool(expected) and (
                given == expected or (len(given) >= 4 and given in expected)
            )
        awarded = question.points if correct else 0
        session.add(
            ChallengeAnswer(
                user_id=user.id or 0,
                challenge_id=challenge.id or 0,
                question_id=question.id or 0,
                choice_id=chosen.id if chosen else None,
                answer_value=given_value,
                answer_text=given_text,
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

    localize.ensure_fields(session, [(question, "explanation")], lang)
    return AnswerOut(
        question_id=question.id or 0,
        correct=correct,
        correct_choice_id=correct_choice.id if correct_choice else 0,
        explanation=localize.read(question, "explanation", lang),
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
