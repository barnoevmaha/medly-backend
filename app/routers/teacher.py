"""Teacher workspace: content management, uploads, students and analytics.

Everything here is gated to instructor/admin server-side via
`require_roles` — hiding the links in the UI is not what protects the
routes, this dependency is.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, func, select

from app.config import settings
from app.db import get_session
from app.models.audit import AuditEvent
from app.models.challenge import (
    Challenge,
    ChallengeAnswer,
    ChallengeChoice,
    ChallengeParticipant,
    ChallengeQuestion,
)
from app.models.course import LessonProgress
from app.models.enums import ProgressStatus, Role
from app.models.quiz import QuizAttempt
from app.models.social import Article, Resource, SavedItem
from app.models.user import User
from app.security import get_current_user, require_roles
from app.services import gamification

router = APIRouter(prefix="/api/teacher", tags=["teacher"])

TEACHER = require_roles(Role.INSTRUCTOR, Role.ADMIN)

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
ALLOWED_UPLOAD_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/gif": ".gif",
}

SLUG_SAFE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    slug = SLUG_SAFE.sub("-", text.strip().lower()).strip("-")
    return slug or "item"


def _unique_slug(session: Session, base: str) -> str:
    """`base` if free, else `base-2`, `base-3`, … across the slug-bearing tables."""
    slug = base
    counter = 1
    while (
        session.exec(select(Resource).where(Resource.slug == slug)).first()
        or session.exec(select(Article).where(Article.slug == slug)).first()
        or session.exec(select(Challenge).where(Challenge.slug == slug)).first()
    ):
        counter += 1
        slug = f"{base}-{counter}"
    return slug


def _own_scope(session: Session, user: User, model):
    statement = select(model)
    if user.role != Role.ADMIN:
        statement = statement.where(model.created_by == user.id)
    return statement


# --------------------------------------------------------------------------
# Uploads
# --------------------------------------------------------------------------


@router.post("/upload")
def upload_image(
    file: UploadFile = File(...),
    user: User = Depends(TEACHER),
) -> dict:
    """Accept an image and serve it back from /uploads. Returns the URL path."""
    extension = ALLOWED_UPLOAD_TYPES.get((file.content_type or "").lower())
    if not extension:
        raise HTTPException(
            status_code=422,
            detail="Only PNG, JPEG, WebP, GIF and SVG images can be uploaded",
        )
    os.makedirs(settings.upload_dir, exist_ok=True)
    destination = os.path.join(settings.upload_dir, f"{uuid.uuid4().hex}{extension}")
    size = 0
    with open(destination, "wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                os.remove(destination)
                raise HTTPException(status_code=422, detail="Image must be under 8 MB")
            out.write(chunk)
    return {"url": f"/uploads/{os.path.basename(destination)}"}


# --------------------------------------------------------------------------
# Content — resources (books, PDFs, videos)
# --------------------------------------------------------------------------


class ResourceIn(BaseModel):
    title: str
    kind: str  # book | pdf | video
    author: str = ""
    description: str = ""
    publisher: str = ""
    year: Optional[int] = None
    pages: Optional[int] = None
    level: str = "foundation"  # foundation | clinical | advanced
    topic: str = ""
    language: str = "en"
    cover: str = ""
    url: str = ""
    duration: str = ""
    duration_minutes: Optional[int] = None
    premium: bool = False
    rating: float = 0.0
    published: bool = False


class ContentOut(BaseModel):
    id: int
    type: str  # book | pdf | video | article | challenge
    slug: str
    title: str
    author: str = ""
    kind: str = ""
    topic: str = ""
    difficulty: str = ""
    published: bool
    cover: str = ""
    created_by: Optional[int] = None
    question_count: int = 0


def _resource_out(resource: Resource) -> ContentOut:
    return ContentOut(
        id=resource.id or 0,
        type=resource.kind,
        slug=resource.slug,
        title=resource.title,
        author=resource.author,
        topic=resource.topic,
        published=resource.published,
        cover=resource.cover,
        created_by=resource.created_by,
    )


def _require_owner(user: User, owner_id: Optional[int]) -> None:
    if user.role != Role.ADMIN and owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the author can do this")


@router.post("/resources", response_model=ContentOut, status_code=201)
def create_resource(
    payload: ResourceIn,
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> ContentOut:
    if payload.kind not in ("book", "pdf", "video"):
        raise HTTPException(status_code=422, detail="kind must be book, pdf or video")
    resource = Resource(
        slug=_unique_slug(session, _slugify(payload.title)),
        kind=payload.kind,
        title=payload.title,
        author=payload.author,
        description=payload.description,
        publisher=payload.publisher,
        year=payload.year,
        pages=payload.pages,
        level=payload.level,
        topic=payload.topic,
        language=payload.language,
        cover=payload.cover,
        url=payload.url,
        duration=payload.duration,
        duration_minutes=payload.duration_minutes,
        premium=payload.premium,
        rating=payload.rating,
        published=payload.published,
        created_by=user.id or 0,
    )
    session.add(resource)
    session.commit()
    session.refresh(resource)
    return _resource_out(resource)


@router.patch("/resources/{resource_id}", response_model=ContentOut)
def update_resource(
    resource_id: int,
    payload: ResourceIn,
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> ContentOut:
    resource = session.get(Resource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    _require_owner(user, resource.created_by)
    for field, value in payload.model_dump().items():
        setattr(resource, field, value)
    session.add(resource)
    session.commit()
    session.refresh(resource)
    return _resource_out(resource)


@router.post("/resources/{resource_id}/publish", response_model=ContentOut)
def publish_resource(
    resource_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> ContentOut:
    resource = session.get(Resource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    _require_owner(user, resource.created_by)
    resource.published = True
    session.add(resource)
    session.commit()
    return _resource_out(resource)


@router.post("/resources/{resource_id}/unpublish", response_model=ContentOut)
def unpublish_resource(
    resource_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> ContentOut:
    resource = session.get(Resource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    _require_owner(user, resource.created_by)
    resource.published = False
    session.add(resource)
    session.commit()
    return _resource_out(resource)


@router.delete("/resources/{resource_id}", status_code=204)
def delete_resource(
    resource_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> None:
    resource = session.get(Resource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    if user.role != Role.ADMIN and resource.created_by != user.id:
        raise HTTPException(status_code=403, detail="Only the author can delete this")
    session.delete(resource)
    session.commit()


# --------------------------------------------------------------------------
# Content — articles
# --------------------------------------------------------------------------


class ArticleIn(BaseModel):
    title: str
    excerpt: str = ""
    body_md: str = ""
    author: str = ""
    author_role: str = ""
    read_minutes: int = 5
    tag: str = "Medical News"
    language: str = "en"
    cover: str = ""
    cover_alt: str = ""
    published: bool = False


@router.post("/articles", response_model=ContentOut, status_code=201)
def create_article(
    payload: ArticleIn,
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> ContentOut:
    article = Article(
        slug=_unique_slug(session, _slugify(payload.title)),
        title=payload.title,
        excerpt=payload.excerpt,
        body_md=payload.body_md,
        author=payload.author or user.full_name,
        author_role=payload.author_role or ("Instructor" if user.role == Role.INSTRUCTOR else "Admin"),
        read_minutes=payload.read_minutes,
        tag=payload.tag,
        language=payload.language,
        cover=payload.cover,
        cover_alt=payload.cover_alt,
        published=payload.published,
        created_by=user.id or 0,
    )
    session.add(article)
    session.commit()
    session.refresh(article)
    return ContentOut(
        id=article.id or 0,
        type="article",
        slug=article.slug,
        title=article.title,
        author=article.author,
        topic=article.tag,
        published=article.published,
        cover=article.cover,
        created_by=article.created_by,
    )


@router.patch("/articles/{article_id}", response_model=ContentOut)
def update_article(
    article_id: int,
    payload: ArticleIn,
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> ContentOut:
    article = session.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if user.role != Role.ADMIN and article.created_by != user.id:
        raise HTTPException(status_code=403, detail="Only the author can edit this")
    for field, value in payload.model_dump().items():
        setattr(article, field, value)
    session.add(article)
    session.commit()
    session.refresh(article)
    return ContentOut(
        id=article.id or 0,
        type="article",
        slug=article.slug,
        title=article.title,
        author=article.author,
        topic=article.tag,
        published=article.published,
        cover=article.cover,
        created_by=article.created_by,
    )


@router.post("/articles/{article_id}/publish", response_model=ContentOut)
def publish_article(
    article_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> ContentOut:
    article = session.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if user.role != Role.ADMIN and article.created_by != user.id:
        raise HTTPException(status_code=403, detail="Only the author can publish this")
    article.published = True
    session.add(article)
    session.commit()
    return update_article(article_id, ArticleIn(**article.__dict__), session, user)


@router.post("/articles/{article_id}/unpublish", response_model=ContentOut)
def unpublish_article(
    article_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> ContentOut:
    article = session.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if user.role != Role.ADMIN and article.created_by != user.id:
        raise HTTPException(status_code=403, detail="Only the author can unpublish this")
    article.published = False
    session.add(article)
    session.commit()
    return update_article(article_id, ArticleIn(**article.__dict__), session, user)


@router.delete("/articles/{article_id}", status_code=204)
def delete_article(
    article_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> None:
    article = session.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if user.role != Role.ADMIN and article.created_by != user.id:
        raise HTTPException(status_code=403, detail="Only the author can delete this")
    session.delete(article)
    session.commit()


# --------------------------------------------------------------------------
# Content — challenges (with questions, images and answer keys)
# --------------------------------------------------------------------------


class ChoiceIn(BaseModel):
    text: str
    correct: bool = False


class QuestionIn(BaseModel):
    prompt: str
    kind: str = "mcq"  # mcq | true_false | numerical | short
    explanation: str = ""
    choices: List[ChoiceIn] = []
    answer_value: Optional[float] = None
    answer_text: str = ""
    image_seed: Optional[str] = None
    image_url: Optional[str] = None
    image_alt: str = ""
    image_modality: str = "xray"
    points: int = 20


class ChallengeIn(BaseModel):
    title: str
    topic: str = ""
    description: str = ""
    difficulty: str = "medium"
    duration_minutes: int = 10
    icon: str = "trophy"
    thumbnail: str = ""
    points: Optional[int] = None
    published: bool = False
    questions: List[QuestionIn] = []


def _replace_questions(session: Session, challenge: Challenge, specs: List[QuestionIn]) -> None:
    old = session.exec(
        select(ChallengeQuestion).where(ChallengeQuestion.challenge_id == challenge.id)
    ).all()
    for question in old:
        for choice in session.exec(
            select(ChallengeChoice).where(ChallengeChoice.question_id == question.id)
        ).all():
            session.delete(choice)
        session.delete(question)
    session.flush()

    for index, spec in enumerate(specs):
        question = ChallengeQuestion(
            challenge_id=challenge.id or 0,
            order=index,
            prompt=spec.prompt,
            explanation=spec.explanation,
            points=max(1, spec.points),
            kind=spec.kind,
            answer_value=spec.answer_value,
            answer_text=spec.answer_text,
            image_seed=spec.image_seed,
            image_url=spec.image_url,
            image_alt=spec.image_alt,
            image_modality=spec.image_modality,
        )
        session.add(question)
        session.flush()
        session.refresh(question)
        if spec.kind in ("mcq", "true_false"):
            if not spec.choices:
                raise HTTPException(
                    status_code=422, detail=f"Question {index + 1} needs choices"
                )
            if sum(1 for choice in spec.choices if choice.correct) != 1:
                raise HTTPException(
                    status_code=422,
                    detail=f"Question {index + 1} needs exactly one correct choice",
                )
            for choice_index, choice in enumerate(spec.choices):
                session.add(
                    ChallengeChoice(
                        question_id=question.id or 0,
                        order=choice_index,
                        text=choice.text,
                        is_correct=choice.correct,
                    )
                )
        elif spec.kind == "numerical":
            if spec.answer_value is None:
                raise HTTPException(
                    status_code=422, detail=f"Question {index + 1} needs a numerical answer"
                )
        elif spec.kind == "short":
            if not spec.answer_text.strip():
                raise HTTPException(
                    status_code=422, detail=f"Question {index + 1} needs an expected answer"
                )
    session.commit()


@router.post("/challenges", response_model=ContentOut, status_code=201)
def create_challenge(
    payload: ChallengeIn,
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> ContentOut:
    challenge = Challenge(
        slug=_unique_slug(session, _slugify(payload.title)),
        title=payload.title,
        description=payload.description,
        topic=payload.topic or payload.title,
        icon=payload.icon,
        difficulty=payload.difficulty,
        points=payload.points or 0,
        duration_minutes=payload.duration_minutes,
        thumbnail=payload.thumbnail,
        published=payload.published,
        created_by=user.id or 0,
    )
    session.add(challenge)
    session.commit()
    session.refresh(challenge)
    _replace_questions(session, challenge, payload.questions)
    return ContentOut(
        id=challenge.id or 0,
        type="challenge",
        slug=challenge.slug,
        title=challenge.title,
        topic=challenge.topic,
        difficulty=challenge.difficulty,
        published=challenge.published,
        cover=challenge.thumbnail,
        created_by=challenge.created_by,
        question_count=len(payload.questions),
    )


@router.patch("/challenges/{challenge_id}", response_model=ContentOut)
def update_challenge(
    challenge_id: int,
    payload: ChallengeIn,
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> ContentOut:
    challenge = session.get(Challenge, challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    if user.role != Role.ADMIN and challenge.created_by != user.id:
        raise HTTPException(status_code=403, detail="Only the author can edit this")
    for field in ("title", "description", "topic", "icon", "difficulty", "duration_minutes",
                  "thumbnail", "published"):
        setattr(challenge, field, getattr(payload, field))
    if payload.points:
        challenge.points = payload.points
    session.add(challenge)
    session.commit()
    if payload.questions:
        _replace_questions(session, challenge, payload.questions)
    count = len(
        session.exec(
            select(ChallengeQuestion).where(ChallengeQuestion.challenge_id == challenge.id)
        ).all()
    )
    return ContentOut(
        id=challenge.id or 0,
        type="challenge",
        slug=challenge.slug,
        title=challenge.title,
        topic=challenge.topic,
        difficulty=challenge.difficulty,
        published=challenge.published,
        cover=challenge.thumbnail,
        created_by=challenge.created_by,
        question_count=count,
    )


@router.post("/challenges/{challenge_id}/publish", response_model=ContentOut)
def publish_challenge(
    challenge_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> ContentOut:
    challenge = session.get(Challenge, challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    if user.role != Role.ADMIN and challenge.created_by != user.id:
        raise HTTPException(status_code=403, detail="Only the author can publish this")
    challenge.published = True
    session.add(challenge)
    session.commit()
    count = len(
        session.exec(
            select(ChallengeQuestion).where(ChallengeQuestion.challenge_id == challenge.id)
        ).all()
    )
    return ContentOut(
        id=challenge.id or 0,
        type="challenge",
        slug=challenge.slug,
        title=challenge.title,
        topic=challenge.topic,
        difficulty=challenge.difficulty,
        published=True,
        cover=challenge.thumbnail,
        created_by=challenge.created_by,
        question_count=count,
    )


@router.post("/challenges/{challenge_id}/unpublish", response_model=ContentOut)
def unpublish_challenge(
    challenge_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> ContentOut:
    challenge = session.get(Challenge, challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    if user.role != Role.ADMIN and challenge.created_by != user.id:
        raise HTTPException(status_code=403, detail="Only the author can unpublish this")
    challenge.published = False
    session.add(challenge)
    session.commit()
    return publish_challenge(challenge_id, session=session, user=user)  # type: ignore[return-value]


@router.delete("/challenges/{challenge_id}", status_code=204)
def delete_challenge(
    challenge_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> None:
    challenge = session.get(Challenge, challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    if user.role != Role.ADMIN and challenge.created_by != user.id:
        raise HTTPException(status_code=403, detail="Only the author can delete this")
    _replace_questions(session, challenge, [])
    session.delete(challenge)
    session.commit()


# --------------------------------------------------------------------------
# Content list, summary, students, analytics
# --------------------------------------------------------------------------


@router.get("/content", response_model=List[ContentOut])
def list_content(
    type: Optional[str] = None,
    status: Optional[str] = None,  # published | draft
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> List[ContentOut]:
    out: List[ContentOut] = []

    for resource in session.exec(_own_scope(session, user, Resource)).all():
        if type and type not in ("book", "pdf", "video"):
            continue
        if status and (resource.published is (status == "draft")):
            continue
        out.append(ContentOut(
            id=resource.id or 0, type=resource.kind, slug=resource.slug,
            title=resource.title, author=resource.author, topic=resource.topic,
            published=resource.published, cover=resource.cover, created_by=resource.created_by,
        ))

    for article in session.exec(_own_scope(session, user, Article)).all():
        if type and type != "article":
            continue
        if status and (article.published is (status == "draft")):
            continue
        out.append(ContentOut(
            id=article.id or 0, type="article", slug=article.slug, title=article.title,
            author=article.author, topic=article.tag, published=article.published,
            cover=article.cover, created_by=article.created_by,
        ))

    for challenge in session.exec(_own_scope(session, user, Challenge)).all():
        if type and type != "challenge":
            continue
        if status and (challenge.published is (status == "draft")):
            continue
        count = len(session.exec(
            select(ChallengeQuestion).where(ChallengeQuestion.challenge_id == challenge.id)
        ).all())
        out.append(ContentOut(
            id=challenge.id or 0, type="challenge", slug=challenge.slug,
            title=challenge.title, topic=challenge.topic, difficulty=challenge.difficulty,
            published=challenge.published, cover=challenge.thumbnail,
            created_by=challenge.created_by, question_count=count,
        ))

    out.sort(key=lambda item: (item.title or "").lower())
    return out


@router.get("/summary")
def teacher_summary(
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> dict:
    content = list_content(session=session, user=user)
    by_type: dict = {}
    for item in content:
        by_type.setdefault(item.type, {"published": 0, "draft": 0})[
            "published" if item.published else "draft"
        ] += 1

    student_ids = [
        row.id
        for row in session.exec(
            select(User).where(User.role == Role.STUDENT, User.is_active == True)  # noqa: E712
        ).all()
    ]

    return {
        "content": by_type,
        "total_items": len(content),
        "recent": sorted(content, key=lambda item: item.id, reverse=True)[:5],
        "students": len(student_ids),
        "engagement": {
            "challenge_answers": _count_where(
                session, ChallengeAnswer, ChallengeAnswer.user_id.in_(student_ids)
            ) if student_ids else 0,
            "quiz_attempts": _count_where(
                session, QuizAttempt, QuizAttempt.user_id.in_(student_ids)
            ) if student_ids else 0,
            "saved_items": _count_where(
                session, SavedItem, SavedItem.user_id.in_(student_ids)
            ) if student_ids else 0,
        },
    }


def _count_where(session: Session, model, *where) -> int:
    statement = select(func.count()).select_from(model)
    for clause in where:
        statement = statement.where(clause)
    return int(session.exec(statement).one())


@router.get("/students")
def list_students(
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> List[dict]:
    students = session.exec(
        select(User)
        .where(User.role == Role.STUDENT, User.is_active == True)  # noqa: E712
        .order_by(User.points.desc())  # type: ignore[union-attr]
    ).all()
    out: List[dict] = []
    for student in students:
        user_id = student.id or 0
        lessons = _count_where(
            session, LessonProgress,
            LessonProgress.user_id == user_id,
            LessonProgress.status == ProgressStatus.COMPLETED,
        )
        challenges = int(
            session.exec(
                select(func.count(func.distinct(ChallengeAnswer.challenge_id))).where(
                    ChallengeAnswer.user_id == user_id
                )
            ).one()
        )
        out.append({
            "id": user_id,
            "name": student.full_name,
            "email": student.email,
            "institution": student.institution or "",
            "year_of_study": student.year_of_study,
            "points": student.points or 0,
            "streak_days": gamification.current_streak(student),
            "lessons_completed": lessons,
            "challenges_completed": challenges,
            "last_active_on": student.last_active_on.isoformat() if student.last_active_on else None,
            "avatar_url": student.avatar_url or "",
        })
    return out


@router.get("/analytics")
def teacher_analytics(
    session: Session = Depends(get_session),
    user: User = Depends(TEACHER),
) -> dict:
    total_users = _count_where(session, User, User.is_active == True)  # noqa: E712
    ai_interactions = _count_where(session, AuditEvent)
    blocked = _count_where(session, AuditEvent, AuditEvent.blocked == True)  # noqa: E712
    quiz_attempts = _count_where(session, QuizAttempt)
    challenge_answers = _count_where(session, ChallengeAnswer)
    lessons_completed = _count_where(
        session, LessonProgress, LessonProgress.status == ProgressStatus.COMPLETED
    )
    saves = _count_where(session, SavedItem)

    answers = session.exec(select(ChallengeAnswer)).all()
    titles = {challenge.id: challenge.topic for challenge in session.exec(select(Challenge)).all()}
    by_topic: dict = {}
    for row in answers:
        topic = titles.get(row.challenge_id, "Other")
        by_topic[topic] = by_topic.get(topic, 0) + 1

    since = datetime.utcnow() - timedelta(days=13)
    events = session.exec(
        select(AuditEvent).where(AuditEvent.created_at >= since).order_by(AuditEvent.created_at)
    ).all()
    by_day: dict = {}
    for event in events:
        day = event.created_at.date().isoformat()
        entry = by_day.setdefault(day, {"interactions": 0, "blocked": 0})
        entry["interactions"] += 1
        if event.blocked:
            entry["blocked"] += 1

    return {
        "total_users": total_users,
        "ai_interactions": ai_interactions,
        "blocked_interactions": blocked,
        "quiz_attempts": quiz_attempts,
        "challenge_answers": challenge_answers,
        "lessons_completed": lessons_completed,
        "saves": saves,
        "top_topics": sorted(by_topic.items(), key=lambda pair: pair[1], reverse=True)[:5],
        "by_day": [{"date": day, **stats} for day, stats in sorted(by_day.items())],
    }
