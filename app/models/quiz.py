"""Assessment: quizzes, questions, choices and attempts."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Quiz(SQLModel, table=True):
    __tablename__ = "quizzes"

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    title: str
    description: str = Field(default="")
    passing_score: int = Field(default=80)

    # Filled on first view in that language by localize.ensure_fields.
    title_ru: str = Field(default="")
    title_uz: str = Field(default="")
    description_ru: str = Field(default="")
    description_uz: str = Field(default="")


class Question(SQLModel, table=True):
    __tablename__ = "questions"

    id: Optional[int] = Field(default=None, primary_key=True)
    quiz_id: int = Field(foreign_key="quizzes.id", index=True)
    order: int = Field(default=0)
    prompt: str
    # "single" = one correct choice, "multi" = several.
    kind: str = Field(default="single")
    explanation: str = Field(default="")
    points: int = Field(default=1)

    prompt_ru: str = Field(default="")
    prompt_uz: str = Field(default="")
    explanation_ru: str = Field(default="")
    explanation_uz: str = Field(default="")


class Choice(SQLModel, table=True):
    __tablename__ = "choices"

    id: Optional[int] = Field(default=None, primary_key=True)
    question_id: int = Field(foreign_key="questions.id", index=True)
    order: int = Field(default=0)
    text: str
    is_correct: bool = Field(default=False)

    text_ru: str = Field(default="")
    text_uz: str = Field(default="")


class QuizAttempt(SQLModel, table=True):
    __tablename__ = "quiz_attempts"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    quiz_id: int = Field(foreign_key="quizzes.id", index=True)
    score: int = Field(default=0)
    passed: bool = Field(default=False)
    # JSON: {"question_id": [choice_id, ...]}
    answers_json: str = Field(default="{}")
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
