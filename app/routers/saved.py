"""Library resources and the Saved collection.

Saved replaces the old read-only Library/PDFs idea: one collection, four
content types, server-side so it survives a refresh and a new device.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, func, or_, select

from app.db import get_session
from app.lang import get_lang
from app.models.social import Article, BookProgress, Resource, SavedItem
from app.models.user import User
from app.security import get_current_user
from app.services import gamification, localize

router = APIRouter(prefix="/api", tags=["saved"])

ITEM_TYPES = {"article", "book", "pdf", "video"}


class ResourceOut(BaseModel):
    id: int
    slug: str
    kind: str
    title: str
    author: str
    description: str
    rating: float
    downloads: str
    duration: str
    premium: bool
    url: str
    video_url: str
    orientation: str
    pdf_url: str
    cover_hue: int
    cover: str
    publisher: str
    year: Optional[int]
    pages: Optional[int]
    level: str
    topic: str
    language: str
    duration_minutes: Optional[int]
    saved: bool


class SavedOut(BaseModel):
    id: int
    item_type: str
    item_key: str
    title: str
    subtitle: str
    description: str
    href: str
    meta: str
    premium: bool = False
    cover_hue: int = 210
    cover: str = ""
    cover_alt: str = ""
    saved_at: datetime


class SaveIn(BaseModel):
    item_type: str
    item_key: str


def _saved_keys(session: Session, user_id: int, item_type: str) -> set:
    rows = session.exec(
        select(SavedItem).where(
            SavedItem.user_id == user_id, SavedItem.item_type == item_type
        )
    ).all()
    return {row.item_key for row in rows}


@router.get("/resources", response_model=List[ResourceOut])
def list_resources(
    q: Optional[str] = None,
    kind: Optional[str] = None,
    level: Optional[str] = None,
    topic: Optional[str] = None,
    language: Optional[str] = None,
    year: Optional[int] = None,
    min_duration: Optional[int] = None,
    max_duration: Optional[int] = None,
    sort: Optional[str] = "title",
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> List[ResourceOut]:
    """The library catalogue.

    Every filter here maps to a column that is actually populated. There is no
    filter for anything the data cannot answer.
    """
    statement = select(Resource).where(Resource.published == True)  # noqa: E712
    if kind:
        statement = statement.where(Resource.kind == kind)
    if level:
        statement = statement.where(Resource.level == level)
    if topic:
        statement = statement.where(Resource.topic == topic)
    if language:
        statement = statement.where(Resource.language == language)
    if year:
        statement = statement.where(Resource.year == year)
    if min_duration is not None:
        statement = statement.where(Resource.duration_minutes >= min_duration)
    if max_duration is not None:
        statement = statement.where(Resource.duration_minutes <= max_duration)
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        statement = statement.where(
            or_(
                func.lower(Resource.title).like(needle),
                func.lower(Resource.author).like(needle),
                func.lower(Resource.description).like(needle),
                func.lower(Resource.publisher).like(needle),
                func.lower(Resource.topic).like(needle),
            )
        )

    order = {
        "title": (Resource.title, False),
        "rating": (Resource.rating, True),
        "year": (Resource.year, True),
        "duration": (Resource.duration_minutes, False),
    }.get(sort or "title", (Resource.title, False))
    column, newest_first = order
    resources = session.exec(statement.order_by(column.desc() if newest_first else column)).all()

    saved: set = set()
    for item_type in ("book", "pdf", "video"):
        saved |= {f"{item_type}:{key}" for key in _saved_keys(session, user.id or 0, item_type)}

    localize.ensure_fields(session, localize.fields_for(resources, ("description",)), lang)
    return [
        ResourceOut(
            id=resource.id or 0,
            slug=resource.slug,
            kind=resource.kind,
            title=resource.title,
            author=resource.author,
            description=localize.read(resource, "description", lang),
            rating=resource.rating,
            downloads=resource.downloads,
            duration=resource.duration,
            premium=resource.premium,
            url=resource.url,
            video_url=resource.video_url,
            orientation=resource.orientation,
            pdf_url=resource.pdf_url,
            cover_hue=resource.cover_hue,
            cover=resource.cover,
            publisher=resource.publisher,
            year=resource.year,
            pages=resource.pages,
            level=resource.level,
            topic=resource.topic,
            language=resource.language,
            duration_minutes=resource.duration_minutes,
            saved=f"{resource.kind}:{resource.slug}" in saved,
        )
        for resource in resources
    ]


@router.get("/books/{slug}/progress")
def book_progress(
    slug: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    """Reading progress for one book. Unknown books are treated as 0%."""
    resource = session.exec(select(Resource).where(Resource.slug == slug)).first()
    if not resource or resource.kind not in ("book", "pdf"):
        raise HTTPException(status_code=404, detail="Book not found")
    row = session.exec(
        select(BookProgress).where(
            BookProgress.user_id == user.id,
            BookProgress.resource_id == resource.id,
        )
    ).first()
    return {"slug": slug, "percent": row.percent if row else 0}


class BookProgressIn(BaseModel):
    percent: int


@router.put("/books/{slug}/progress")
def update_book_progress(
    slug: str,
    payload: BookProgressIn,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    resource = session.exec(select(Resource).where(Resource.slug == slug)).first()
    if not resource or resource.kind not in ("book", "pdf"):
        raise HTTPException(status_code=404, detail="Book not found")
    percent = max(0, min(100, payload.percent))
    row = session.exec(
        select(BookProgress).where(
            BookProgress.user_id == user.id,
            BookProgress.resource_id == resource.id,
        )
    ).first()
    if row is None:
        row = BookProgress(user_id=user.id or 0, resource_id=resource.id or 0, percent=percent)
        session.add(row)
    else:
        row.percent = percent
        row.updated_at = datetime.utcnow()
        session.add(row)
    session.commit()
    return {"slug": slug, "percent": percent}


@router.get("/saved", response_model=List[SavedOut])
def list_saved(
    item_type: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> List[SavedOut]:
    statement = select(SavedItem).where(SavedItem.user_id == user.id)
    if item_type and item_type != "all":
        statement = statement.where(SavedItem.item_type == item_type)
    rows = session.exec(statement.order_by(SavedItem.created_at.desc())).all()  # type: ignore[union-attr]

    articles: dict[str, Article] = {}
    resources: dict[str, Resource] = {}
    for row in rows:
        if row.item_type == "article" and row.item_key not in articles:
            found = session.exec(select(Article).where(Article.slug == row.item_key)).first()
            if found:
                articles[row.item_key] = found
        elif row.item_type != "article" and row.item_key not in resources:
            found = session.exec(select(Resource).where(Resource.slug == row.item_key)).first()
            if found:
                resources[row.item_key] = found

    localize.ensure_fields(
        session, localize.fields_for(list(articles.values()), ("title", "excerpt")), lang
    )
    localize.ensure_fields(
        session, localize.fields_for(list(resources.values()), ("description",)), lang
    )

    out: List[SavedOut] = []
    for row in rows:
        if row.item_type == "article":
            article = articles.get(row.item_key)
            if not article:
                continue
            out.append(
                SavedOut(
                    id=row.id or 0,
                    item_type="article",
                    item_key=row.item_key,
                    title=localize.read(article, "title", lang),
                    subtitle=article.author,
                    description=localize.read(article, "excerpt", lang),
                    href=f"/feed/{article.slug}",
                    meta=f"{article.read_minutes} min read · {article.tag}",
                    cover=article.cover,
                    cover_alt=article.cover_alt,
                    saved_at=row.created_at,
                )
            )
        else:
            resource = resources.get(row.item_key)
            if not resource:
                continue
            meta = resource.duration or f"{resource.downloads} downloads"
            out.append(
                SavedOut(
                    id=row.id or 0,
                    item_type=row.item_type,
                    item_key=row.item_key,
                    title=resource.title,
                    subtitle=resource.author,
                    description=localize.read(resource, "description", lang),
                    # Empty when the demo resource has no file behind it. The UI
                    # says so rather than offering a button that goes nowhere.
                    href=resource.url,
                    meta=meta,
                    premium=resource.premium,
                    cover_hue=resource.cover_hue,
                    cover=resource.cover,
                    cover_alt=f"Cover art for {resource.title}",
                    saved_at=row.created_at,
                )
            )
    return out


@router.post("/saved", response_model=SavedOut, status_code=201)
def save_item(
    payload: SaveIn,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> SavedOut:
    """Save something. Saving twice returns the existing row, never a duplicate."""
    if payload.item_type not in ITEM_TYPES:
        raise HTTPException(status_code=422, detail=f"Unknown item type '{payload.item_type}'")

    if payload.item_type == "article":
        target = session.exec(select(Article).where(Article.slug == payload.item_key)).first()
        if not target:
            raise HTTPException(status_code=404, detail="Nothing to save under that key")
    else:
        resource = session.exec(
            select(Resource).where(Resource.slug == payload.item_key)
        ).first()
        if not resource:
            raise HTTPException(status_code=404, detail="Nothing to save under that key")
        # Saving a book as a video would file it under the wrong tab forever.
        if resource.kind != payload.item_type:
            raise HTTPException(
                status_code=422,
                detail=f"'{payload.item_key}' is a {resource.kind}, not a {payload.item_type}",
            )

    existing = session.exec(
        select(SavedItem).where(
            SavedItem.user_id == user.id,
            SavedItem.item_type == payload.item_type,
            SavedItem.item_key == payload.item_key,
        )
    ).first()
    if not existing:
        existing = SavedItem(
            user_id=user.id or 0,
            item_type=payload.item_type,
            item_key=payload.item_key,
        )
        session.add(existing)
        session.commit()
        session.refresh(existing)
        gamification.sync_badges(session, user)

    entry = next(
        (
            item
            for item in list_saved(item_type=payload.item_type, session=session, user=user, lang=lang)
            if item.item_key == payload.item_key
        ),
        None,
    )
    if entry is None:  # pragma: no cover — the row was just written
        raise HTTPException(status_code=500, detail="Saved item could not be read back")
    return entry


@router.delete("/saved", status_code=204)
def unsave_item(
    item_type: str,
    item_key: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    row = session.exec(
        select(SavedItem).where(
            SavedItem.user_id == user.id,
            SavedItem.item_type == item_type,
            SavedItem.item_key == item_key,
        )
    ).first()
    if row:
        session.delete(row)
        session.commit()


@router.get("/saved/counts")
def saved_counts(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    rows = session.exec(select(SavedItem).where(SavedItem.user_id == user.id)).all()
    counts = {key: 0 for key in ITEM_TYPES}
    for row in rows:
        counts[row.item_type] = counts.get(row.item_type, 0) + 1
    counts["all"] = len(rows)
    return counts
