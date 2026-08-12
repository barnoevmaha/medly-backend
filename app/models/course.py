"""Curriculum: courses, lessons, enrolments and lesson progress."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.models.enums import LessonKind, ProgressStatus


class Course(SQLModel, table=True):
    __tablename__ = "courses"

    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    title: str
    summary: str
    track: str = Field(default="ai-foundations", index=True)
    level: str = Field(default="beginner")
    duration_minutes: int = Field(default=60)
    # Lucide icon name rendered on the course card. Icons, not emoji, so the
    # curriculum reads as a syllabus rather than a chat message.
    icon: str = Field(default="brain")
    order: int = Field(default=0)
    published: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Filled on first view in that language by localize.ensure_fields.
    title_ru: str = Field(default="")
    title_uz: str = Field(default="")
    summary_ru: str = Field(default="")
    summary_uz: str = Field(default="")


class Lesson(SQLModel, table=True):
    __tablename__ = "lessons"

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    order: int = Field(default=0)
    title: str
    kind: LessonKind = Field(default=LessonKind.READING)
    duration_minutes: int = Field(default=10)
    body_md: str = Field(default="")
    # Key takeaway rendered as a highlighted callout in the UI.
    key_point: Optional[str] = None

    title_ru: str = Field(default="")
    title_uz: str = Field(default="")
    body_md_ru: str = Field(default="")
    body_md_uz: str = Field(default="")
    key_point_ru: str = Field(default="")
    key_point_uz: str = Field(default="")


class Enrollment(SQLModel, table=True):
    __tablename__ = "enrollments"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class LessonProgress(SQLModel, table=True):
    __tablename__ = "lesson_progress"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    lesson_id: int = Field(foreign_key="lessons.id", index=True)
    status: ProgressStatus = Field(default=ProgressStatus.NOT_STARTED)
    completed_at: Optional[datetime] = None
