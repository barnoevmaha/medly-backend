"""Courses, lessons, enrolment and lesson progress."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.lang import get_lang
from app.models.course import Course, Enrollment, Lesson, LessonProgress
from app.models.enums import EventType, LessonKind, ProgressStatus
from app.models.user import User
from app.security import get_current_user
from app.services import localize
from app.services.audit import log_event
from app.services.gamification import touch_streak

router = APIRouter(prefix="/api/courses", tags=["courses"])


class LessonSummary(BaseModel):
    id: int
    order: int
    title: str
    kind: LessonKind
    duration_minutes: int
    key_point: Optional[str] = None
    status: ProgressStatus = ProgressStatus.NOT_STARTED


class LessonDetail(LessonSummary):
    body_md: str
    course_id: int


class CourseSummary(BaseModel):
    id: int
    slug: str
    title: str
    summary: str
    track: str
    level: str
    duration_minutes: int
    icon: str
    lesson_count: int
    enrolled: bool = False
    progress_pct: int = 0


class CourseDetail(CourseSummary):
    lessons: List[LessonSummary]


def _progress_map(session: Session, user_id: int, lesson_ids: List[int]) -> dict:
    if not lesson_ids:
        return {}
    rows = session.exec(
        select(LessonProgress).where(
            LessonProgress.user_id == user_id, LessonProgress.lesson_id.in_(lesson_ids)  # type: ignore[union-attr]
        )
    ).all()
    return {row.lesson_id: row.status for row in rows}


@router.get("/lessons/{lesson_id}", response_model=LessonDetail)
def get_lesson(
    lesson_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> LessonDetail:
    lesson = session.get(Lesson, lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")

    localize.ensure_fields(
        session, localize.fields_for([lesson], ("title", "body_md", "key_point")), lang
    )

    progress = session.exec(
        select(LessonProgress).where(
            LessonProgress.user_id == user.id, LessonProgress.lesson_id == lesson_id
        )
    ).first()
    if not progress:
        progress = LessonProgress(
            user_id=user.id or 0, lesson_id=lesson_id, status=ProgressStatus.IN_PROGRESS
        )
        session.add(progress)
        session.commit()
        session.refresh(progress)

    return LessonDetail(
        id=lesson.id or 0,
        course_id=lesson.course_id,
        order=lesson.order,
        title=localize.read(lesson, "title", lang),
        kind=lesson.kind,
        duration_minutes=lesson.duration_minutes,
        key_point=localize.read(lesson, "key_point", lang) or None,
        body_md=localize.read(lesson, "body_md", lang),
        status=progress.status,
    )


@router.post("/lessons/{lesson_id}/complete", response_model=LessonSummary)
def complete_lesson(
    lesson_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> LessonSummary:
    lesson = session.get(Lesson, lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")

    progress = session.exec(
        select(LessonProgress).where(
            LessonProgress.user_id == user.id, LessonProgress.lesson_id == lesson_id
        )
    ).first()
    if not progress:
        progress = LessonProgress(user_id=user.id or 0, lesson_id=lesson_id)
        session.add(progress)

    progress.status = ProgressStatus.COMPLETED
    progress.completed_at = datetime.utcnow()
    session.add(progress)
    session.commit()

    touch_streak(session, user)

    log_event(
        session,
        user_id=user.id,
        event_type=EventType.LESSON_COMPLETED,
        resource_type="lesson",
        resource_id=lesson_id,
    )

    return LessonSummary(
        id=lesson.id or 0,
        order=lesson.order,
        title=localize.read(lesson, "title", lang),
        kind=lesson.kind,
        duration_minutes=lesson.duration_minutes,
        key_point=localize.read(lesson, "key_point", lang) or None,
        status=ProgressStatus.COMPLETED,
    )
@router.get("", response_model=List[CourseSummary])
def list_courses(
    track: Optional[str] = None,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> List[CourseSummary]:
    statement = select(Course).where(Course.published == True)  # noqa: E712
    if track:
        statement = statement.where(Course.track == track)
    courses = list(session.exec(statement.order_by(Course.order)).all())
    localize.ensure_fields(session, localize.fields_for(courses, ("title", "summary")), lang)

    enrolled_ids = {
        e.course_id for e in session.exec(select(Enrollment).where(Enrollment.user_id == user.id)).all()
    }

    out: List[CourseSummary] = []
    for course in courses:
        lessons = session.exec(select(Lesson).where(Lesson.course_id == course.id)).all()
        lesson_ids = [lesson.id for lesson in lessons if lesson.id is not None]
        statuses = _progress_map(session, user.id or 0, lesson_ids)
        done = sum(1 for lid in lesson_ids if statuses.get(lid) == ProgressStatus.COMPLETED)
        out.append(
            CourseSummary(
                id=course.id or 0,
                slug=course.slug,
                title=localize.read(course, "title", lang),
                summary=localize.read(course, "summary", lang),
                track=course.track,
                level=course.level,
                duration_minutes=course.duration_minutes,
                icon=course.icon,
                lesson_count=len(lesson_ids),
                enrolled=course.id in enrolled_ids,
                progress_pct=round(done / len(lesson_ids) * 100) if lesson_ids else 0,
            )
        )
    return out


@router.get("/{slug}", response_model=CourseDetail)
def get_course(
    slug: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> CourseDetail:
    course = session.exec(select(Course).where(Course.slug == slug)).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    lessons = list(
        session.exec(
            select(Lesson).where(Lesson.course_id == course.id).order_by(Lesson.order)
        ).all()
    )
    # Card-level text for the whole syllabus in one batch. Lesson bodies are
    # left to get_lesson: translating every body to render a contents list
    # would be the expensive half of the course for text nobody has opened.
    refs = localize.fields_for([course], ("title", "summary"))
    refs += localize.fields_for(lessons, ("title", "key_point"))
    localize.ensure_fields(session, refs, lang)
    lesson_ids = [lesson.id for lesson in lessons if lesson.id is not None]
    statuses = _progress_map(session, user.id or 0, lesson_ids)
    done = sum(1 for lid in lesson_ids if statuses.get(lid) == ProgressStatus.COMPLETED)

    enrolled = session.exec(
        select(Enrollment).where(Enrollment.user_id == user.id, Enrollment.course_id == course.id)
    ).first()

    return CourseDetail(
        id=course.id or 0,
        slug=course.slug,
        title=localize.read(course, "title", lang),
        summary=localize.read(course, "summary", lang),
        track=course.track,
        level=course.level,
        duration_minutes=course.duration_minutes,
        icon=course.icon,
        lesson_count=len(lesson_ids),
        enrolled=enrolled is not None,
        progress_pct=round(done / len(lesson_ids) * 100) if lesson_ids else 0,
        lessons=[
            LessonSummary(
                id=lesson.id or 0,
                order=lesson.order,
                title=localize.read(lesson, "title", lang),
                kind=lesson.kind,
                duration_minutes=lesson.duration_minutes,
                key_point=localize.read(lesson, "key_point", lang) or None,
                status=statuses.get(lesson.id or 0, ProgressStatus.NOT_STARTED),
            )
            for lesson in lessons
        ],
    )


@router.post("/{slug}/enroll", response_model=CourseSummary)
def enroll(
    slug: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> CourseSummary:
    course = session.exec(select(Course).where(Course.slug == slug)).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    existing = session.exec(
        select(Enrollment).where(Enrollment.user_id == user.id, Enrollment.course_id == course.id)
    ).first()
    if not existing:
        session.add(Enrollment(user_id=user.id or 0, course_id=course.id or 0))
        session.commit()

    lessons = session.exec(select(Lesson).where(Lesson.course_id == course.id)).all()
    return CourseSummary(
        id=course.id or 0,
        slug=course.slug,
        title=localize.read(course, "title", lang),
        summary=localize.read(course, "summary", lang),
        track=course.track,
        level=course.level,
        duration_minutes=course.duration_minutes,
        icon=course.icon,
        lesson_count=len(lessons),
        enrolled=True,
        progress_pct=0,
    )


