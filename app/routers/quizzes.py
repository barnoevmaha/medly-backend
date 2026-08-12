"""Quizzes and grading."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.lang import get_lang
from app.models.course import Course
from app.models.enums import EventType, RiskLevel
from app.models.quiz import Choice, Question, Quiz, QuizAttempt
from app.models.user import User
from app.security import get_current_user
from app.services import localize
from app.services.audit import log_event
from app.services.gamification import sync_badges, touch_streak
from app.services.scoring import competency_band, grade

router = APIRouter(prefix="/api/quizzes", tags=["quizzes"])


class ChoiceOut(BaseModel):
    id: int
    text: str


class QuestionOut(BaseModel):
    id: int
    order: int
    prompt: str
    kind: str
    points: int
    choices: List[ChoiceOut]


class QuizOut(BaseModel):
    id: int
    course_id: int
    title: str
    description: str
    passing_score: int
    questions: List[QuestionOut]


class SubmitRequest(BaseModel):
    # question id -> selected choice ids
    answers: Dict[int, List[int]]


class QuestionResult(BaseModel):
    question_id: int
    correct: bool
    correct_choice_ids: List[int]
    given_choice_ids: List[int]
    explanation: str


class AttemptOut(BaseModel):
    id: int
    quiz_id: int
    quiz_title: Optional[str] = None
    score: int
    passed: bool
    submitted_at: datetime


class SubmitResponse(BaseModel):
    attempt_id: int
    score: int
    passed: bool
    passing_score: int
    band: str
    points_awarded: int = 0
    total_points: int = 0
    results: List[QuestionResult]


@router.get("/course/{course_slug}", response_model=List[QuizOut])
def quizzes_for_course(
    course_slug: str,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> List[QuizOut]:
    course = session.exec(select(Course).where(Course.slug == course_slug)).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    quizzes = session.exec(select(Quiz).where(Quiz.course_id == course.id)).all()
    return [_quiz_out(session, quiz, lang) for quiz in quizzes]


@router.get("/attempts/me", response_model=List[AttemptOut])
def my_attempts(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> List[AttemptOut]:
    attempts = session.exec(
        select(QuizAttempt)
        .where(QuizAttempt.user_id == user.id)
        .order_by(QuizAttempt.submitted_at.desc())  # type: ignore[union-attr]
    ).all()
    out: List[AttemptOut] = []
    for attempt in attempts:
        quiz = session.get(Quiz, attempt.quiz_id)
        out.append(
            AttemptOut(
                id=attempt.id or 0,
                quiz_id=attempt.quiz_id,
                quiz_title=localize.read(quiz, "title", lang) if quiz else None,
                score=attempt.score,
                passed=attempt.passed,
                submitted_at=attempt.submitted_at,
            )
        )
    return out
@router.get("/{quiz_id}", response_model=QuizOut)
def get_quiz(
    quiz_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> QuizOut:
    quiz = session.get(Quiz, quiz_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return _quiz_out(session, quiz, lang)


def _quiz_out(session: Session, quiz: Quiz, lang: str = "en") -> QuizOut:
    """Serialise a quiz. Correct answers are never included in the payload.

    Every question and choice is translated in one batch before serialising,
    so a quiz costs one translation the first time it is opened in a language
    and nothing on every view after that.
    """
    questions = list(
        session.exec(
            select(Question).where(Question.quiz_id == quiz.id).order_by(Question.order)
        ).all()
    )
    all_choices = {
        question.id or 0: list(
            session.exec(
                select(Choice)
                .where(Choice.question_id == question.id)
                .order_by(Choice.order)
            ).all()
        )
        for question in questions
    }

    refs = localize.fields_for([quiz], ("title", "description"))
    refs += localize.fields_for(questions, ("prompt", "explanation"))
    for choices in all_choices.values():
        refs += localize.fields_for(choices, ("text",))
    localize.ensure_fields(session, refs, lang)

    out_questions: List[QuestionOut] = []
    for question in questions:
        out_questions.append(
            QuestionOut(
                id=question.id or 0,
                order=question.order,
                prompt=localize.read(question, "prompt", lang),
                kind=question.kind,
                points=question.points,
                choices=[
                    ChoiceOut(id=c.id or 0, text=localize.read(c, "text", lang))
                    for c in all_choices[question.id or 0]
                ],
            )
        )
    return QuizOut(
        id=quiz.id or 0,
        course_id=quiz.course_id,
        title=localize.read(quiz, "title", lang),
        description=localize.read(quiz, "description", lang),
        passing_score=quiz.passing_score,
        questions=out_questions,
    )


@router.post("/{quiz_id}/submit", response_model=SubmitResponse)
def submit(
    quiz_id: int,
    payload: SubmitRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> SubmitResponse:
    quiz = session.get(Quiz, quiz_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    questions = session.exec(
        select(Question).where(Question.quiz_id == quiz_id).order_by(Question.order)
    ).all()
    if not questions:
        raise HTTPException(status_code=400, detail="This quiz has no questions")

    choices_by_question: Dict[int, List[Choice]] = {}
    for question in questions:
        if question.id is None:
            continue
        choices_by_question[question.id] = list(
            session.exec(select(Choice).where(Choice.question_id == question.id)).all()
        )

    outcome = grade(questions, choices_by_question, payload.answers)

    # `grade` is the marking logic and stays language-blind: it reads the
    # canonical column. The explanation shown afterwards is presentation, so
    # it is swapped for the reader's language here rather than teaching the
    # scorer about locales. Marks are unaffected either way.
    localize.ensure_fields(
        session, localize.fields_for(list(questions), ("explanation",)), lang
    )
    by_id = {q.id: q for q in questions}
    for result in outcome["results"]:
        question = by_id.get(result["question_id"])
        if question is not None:
            result["explanation"] = localize.read(question, "explanation", lang)

    score = int(outcome["score"])
    passed = score >= quiz.passing_score

    attempt = QuizAttempt(
        user_id=user.id or 0,
        quiz_id=quiz_id,
        score=score,
        passed=passed,
        answers_json=json.dumps({str(k): v for k, v in payload.answers.items()}),
        submitted_at=datetime.utcnow(),
    )
    session.add(attempt)

    # Points for a pass, once per quiz. `previously_passed` is checked before
    # this attempt is committed, so resitting a quiz cannot be farmed.
    previously_passed = session.exec(
        select(QuizAttempt).where(
            QuizAttempt.user_id == user.id,
            QuizAttempt.quiz_id == quiz_id,
            QuizAttempt.passed == True,  # noqa: E712
        )
    ).first()
    quiz_points = 0
    if passed and not previously_passed:
        quiz_points = 100
        user.points = (user.points or 0) + quiz_points

    session.add(user)
    session.commit()
    session.refresh(attempt)
    session.refresh(user)
    touch_streak(session, user)
    sync_badges(session, user)

    log_event(
        session,
        user_id=user.id,
        event_type=EventType.QUIZ_SUBMITTED,
        risk_level=RiskLevel.NONE,
        resource_type="quiz",
        resource_id=quiz_id,
        human_decision=f"score={score}",
        meta={"passed": passed},
    )
    return SubmitResponse(
        attempt_id=attempt.id or 0,
        score=score,
        passed=passed,
        passing_score=quiz.passing_score,
        band=competency_band(score),
        points_awarded=quiz_points,
        total_points=user.points or 0,
        results=[QuestionResult(**r) for r in outcome["results"]],
    )
