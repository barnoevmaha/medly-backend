"""Challenges: topical question sets that award points once per question."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Challenge(SQLModel, table=True):
    __tablename__ = "challenges"

    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    title: str
    description: str = Field(default="")
    # Free-text topic, e.g. "AI in Medical Imaging" — the questions follow it.
    topic: str = Field(default="", index=True)
    # Machine-translated on first read in that language and cached here from
    # then on — see app/services/translate.py and app/services/localize.py.
    title_ru: str = Field(default="")
    title_uz: str = Field(default="")
    description_ru: str = Field(default="")
    description_uz: str = Field(default="")
    topic_ru: str = Field(default="")
    topic_uz: str = Field(default="")
    icon: str = Field(default="trophy")
    cover: str = Field(default="")
    difficulty: str = Field(default="medium")  # easy | medium | hard
    points: int = Field(default=200)
    ends_at: Optional[datetime] = None
    base_participants: int = Field(default=0)
    order: int = Field(default=0)
    published: bool = Field(default=True)
    created_by: Optional[int] = None
    # Visual identity: a thumbnail path served by the frontend, and a rough
    # "time" the card can advertise. Kept optional so older rows stay valid.
    thumbnail: str = Field(default="")
    duration_minutes: int = Field(default=10)


class ChallengeQuestion(SQLModel, table=True):
    __tablename__ = "challenge_questions"

    id: Optional[int] = Field(default=None, primary_key=True)
    challenge_id: int = Field(foreign_key="challenges.id", index=True)
    order: int = Field(default=0)
    prompt: str
    explanation: str = Field(default="")
    # Machine-translated on demand and cached — see app/services/localize.py.
    prompt_ru: str = Field(default="")
    prompt_uz: str = Field(default="")
    explanation_ru: str = Field(default="")
    explanation_uz: str = Field(default="")
    points: int = Field(default=20)
    # mcq | true_false | numerical | short
    kind: str = Field(default="mcq")

    # Optional image. `image_seed` renders the same deterministic synthetic
    # panel the imaging workbench uses, so an imaging question can actually show
    # a film instead of describing one. `image_alt` is required whenever a seed
    # is set — a question you cannot answer with a screen reader is a broken
    # question, not an accessible one. `image_url` is an uploaded image
    # (teacher-created questions); it wins over the seed when both are set.
    image_seed: Optional[str] = None
    image_url: Optional[str] = None
    image_alt: str = Field(default="")
    image_modality: str = Field(default="xray")

    # Correct answers for the non-choice kinds. numerical stores the exact
    # number; short stores the expected text (compared case-insensitively).
    answer_value: Optional[float] = None
    answer_text: str = Field(default="")


class ChallengeChoice(SQLModel, table=True):
    __tablename__ = "challenge_choices"

    id: Optional[int] = Field(default=None, primary_key=True)
    question_id: int = Field(foreign_key="challenge_questions.id", index=True)
    order: int = Field(default=0)
    text: str
    text_ru: str = Field(default="")
    text_uz: str = Field(default="")
    is_correct: bool = Field(default=False)


class ChallengeParticipant(SQLModel, table=True):
    __tablename__ = "challenge_participants"

    id: Optional[int] = Field(default=None, primary_key=True)
    challenge_id: int = Field(foreign_key="challenges.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    joined_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    score: int = Field(default=0)


class ChallengeAnswer(SQLModel, table=True):
    """One row per (user, question).

    This row is what stops a refresh from farming points: the answer endpoint
    returns the stored result instead of scoring again when it already exists.
    For choice-based questions `choice_id` holds the pick; numerical and short
    answers are stored in `answer_value` / `answer_text` instead.
    """

    __tablename__ = "challenge_answers"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    challenge_id: int = Field(foreign_key="challenges.id", index=True)
    question_id: int = Field(foreign_key="challenge_questions.id", index=True)
    choice_id: Optional[int] = Field(default=None, foreign_key="challenge_choices.id")
    answer_value: Optional[float] = None
    answer_text: str = Field(default="")
    correct: bool = Field(default=False)
    points_awarded: int = Field(default=0)
    answered_at: datetime = Field(default_factory=datetime.utcnow)
