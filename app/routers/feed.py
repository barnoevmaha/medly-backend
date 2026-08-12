"""The feed: articles, their full bodies, comments and likes."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, func, or_, select

from app.db import get_session
from app.lang import get_lang
from app.models.social import Article, ArticleComment, ArticleLike, SavedItem
from app.models.enums import Role
from app.models.user import User
from app.security import get_current_user, require_roles
from app.services import gamification, localize
from app.services.article_images import clear_image, ensure_article_image

router = APIRouter(prefix="/api/feed", tags=["feed"])

# Regenerating imagery is a staff action. Hiding the control in the UI is
# not what protects it — this dependency is.
STAFF = require_roles(Role.INSTRUCTOR, Role.ADMIN)


class CommentOut(BaseModel):
    id: int
    author: str
    author_role: str
    body: str
    created_at: datetime
    mine: bool


class ArticleImageOut(BaseModel):
    """Attribution and real dimensions for a provider-supplied photo.

    Present only when a stock image was chosen. Carries no credential — the
    provider key never leaves the server.
    """

    provider: str
    provider_id: str
    source_url: str
    photographer: str
    photographer_url: str
    width: int
    height: int
    alt: str


class ArticleOut(BaseModel):
    id: int
    slug: str
    tag: str
    title: str
    excerpt: str
    author: str
    author_role: str
    read_minutes: int
    cover: str
    cover_alt: str
    cover_orientation: str
    image: Optional[ArticleImageOut] = None
    language: str
    published_at: datetime
    like_count: int
    comment_count: int
    liked: bool
    saved: bool


class ArticleDetailOut(ArticleOut):
    body_md: str
    comments: List[CommentOut]


class CommentIn(BaseModel):
    body: str = PydanticField(min_length=1, max_length=2000)


def _counts(session: Session, article_id: int, user_id: int) -> dict:
    likes = int(
        session.exec(
            select(func.count()).select_from(ArticleLike).where(
                ArticleLike.article_id == article_id
            )
        ).one()
    )
    comments = int(
        session.exec(
            select(func.count()).select_from(ArticleComment).where(
                ArticleComment.article_id == article_id
            )
        ).one()
    )
    liked = session.exec(
        select(ArticleLike).where(
            ArticleLike.article_id == article_id, ArticleLike.user_id == user_id
        )
    ).first()
    return {"likes": likes, "comments": comments, "liked": liked is not None}


def _saved_slugs(session: Session, user_id: int) -> set:
    rows = session.exec(
        select(SavedItem).where(
            SavedItem.user_id == user_id, SavedItem.item_type == "article"
        )
    ).all()
    return {row.item_key for row in rows}


def _to_out(session: Session, article: Article, user_id: int, saved: set, lang: str) -> ArticleOut:
    counts = _counts(session, article.id or 0, user_id)
    return ArticleOut(
        id=article.id or 0,
        slug=article.slug,
        tag=article.tag,
        title=localize.read(article, "title", lang),
        excerpt=localize.read(article, "excerpt", lang),
        author=article.author,
        author_role=article.author_role,
        read_minutes=article.read_minutes,
        # A stock photo takes precedence when one has been chosen; the
        # authored cover is the fallback, and the placeholder catches the rest.
        cover=article.image_url or article.cover,
        cover_alt=article.image_alt or article.cover_alt,
        cover_orientation=(
            article.image_orientation or article.cover_orientation
        ),
        image=(
            ArticleImageOut(
                provider=article.image_provider,
                provider_id=article.image_provider_id,
                source_url=article.image_source_url,
                photographer=article.image_photographer,
                photographer_url=article.image_photographer_url,
                width=article.image_width,
                height=article.image_height,
                alt=article.image_alt,
            )
            if article.image_url and article.image_provider
            else None
        ),
        language=article.language,
        published_at=article.published_at,
        like_count=article.base_likes + counts["likes"],
        comment_count=counts["comments"],
        liked=counts["liked"],
        saved=article.slug in saved,
    )


@router.get("/articles", response_model=List[ArticleOut])
def list_articles(
    q: Optional[str] = Query(default=None, description="Free text — searches the body too"),
    tag: Optional[str] = None,
    language: Optional[str] = None,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> List[ArticleOut]:
    """List the feed.

    `q` deliberately matches the article *body* as well as the title. Searching
    "radiologists" has to find an article that only says the word halfway down,
    which a title-only filter would miss.
    """
    statement = select(Article).where(Article.published == True)  # noqa: E712
    if tag and tag != "All":
        statement = statement.where(Article.tag == tag)
    if language:
        statement = statement.where(Article.language == language)
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        statement = statement.where(
            or_(
                func.lower(Article.title).like(needle),
                func.lower(Article.excerpt).like(needle),
                func.lower(Article.body_md).like(needle),
                func.lower(Article.author).like(needle),
                func.lower(Article.tag).like(needle),
            )
        )
    articles = session.exec(statement.order_by(Article.published_at.desc())).all()  # type: ignore[union-attr]
    saved = _saved_slugs(session, user.id or 0)
    localize.ensure_fields(session, localize.fields_for(articles, ("title", "excerpt")), lang)
    return [_to_out(session, article, user.id or 0, saved, lang) for article in articles]


@router.get("/articles/{slug}", response_model=ArticleDetailOut)
def get_article(
    slug: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> ArticleDetailOut:
    article = session.exec(select(Article).where(Article.slug == slug)).first()
    if not article or not article.published:
        raise HTTPException(status_code=404, detail="Article not found")

    saved = _saved_slugs(session, user.id or 0)
    localize.ensure_fields(session, [(article, "title"), (article, "excerpt"), (article, "body_md")], lang)
    base = _to_out(session, article, user.id or 0, saved, lang)

    rows = session.exec(
        select(ArticleComment, User)
        .where(ArticleComment.article_id == article.id)
        .where(User.id == ArticleComment.user_id)
        .order_by(ArticleComment.created_at.asc())  # type: ignore[union-attr]
    ).all()

    return ArticleDetailOut(
        **base.model_dump(),
        body_md=localize.read(article, "body_md", lang),
        comments=[
            CommentOut(
                id=comment.id or 0,
                author=author.full_name,
                author_role=author.role.value,
                body=comment.body,
                created_at=comment.created_at,
                mine=author.id == user.id,
            )
            for comment, author in rows
        ],
    )


@router.post("/articles/{slug}/comments", response_model=CommentOut, status_code=201)
def add_comment(
    slug: str,
    payload: CommentIn,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CommentOut:
    article = session.exec(select(Article).where(Article.slug == slug)).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="A comment cannot be empty")

    comment = ArticleComment(article_id=article.id or 0, user_id=user.id or 0, body=body)
    session.add(comment)
    session.commit()
    session.refresh(comment)
    gamification.sync_badges(session, user)

    return CommentOut(
        id=comment.id or 0,
        author=user.full_name,
        author_role=user.role.value,
        body=comment.body,
        created_at=comment.created_at,
        mine=True,
    )


@router.delete("/comments/{comment_id}", status_code=204)
def delete_comment(
    comment_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    comment = session.get(ArticleComment, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.user_id != user.id and user.role.value not in {"instructor", "admin"}:
        raise HTTPException(status_code=403, detail="That is not your comment")
    session.delete(comment)
    session.commit()


@router.post("/articles/{slug}/like", response_model=ArticleOut)
def toggle_like(
    slug: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> ArticleOut:
    article = session.exec(select(Article).where(Article.slug == slug)).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    existing = session.exec(
        select(ArticleLike).where(
            ArticleLike.article_id == article.id, ArticleLike.user_id == user.id
        )
    ).first()
    if existing:
        session.delete(existing)
    else:
        session.add(ArticleLike(article_id=article.id or 0, user_id=user.id or 0))
    session.commit()

    return _to_out(session, article, user.id or 0, _saved_slugs(session, user.id or 0), lang)


class ImageRefreshOut(BaseModel):
    """What the regenerate endpoint reports back."""

    slug: str
    changed: bool
    cover: str
    cover_orientation: str
    image: Optional[ArticleImageOut] = None
    detail: str = ""


def _article_or_404(session: Session, slug: str) -> Article:
    article = session.exec(select(Article).where(Article.slug == slug)).first()
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@router.post("/articles/{slug}/image/regenerate", response_model=ImageRefreshOut)
def regenerate_article_image(
    slug: str,
    session: Session = Depends(get_session),
    user: User = Depends(STAFF),
) -> ImageRefreshOut:
    """Pick a fresh stock photo for one article, replacing the stored one.

    Overwrites the article's own image fields, so regenerating repeatedly leaves
    one photo on the row rather than accumulating them. A lookup that finds
    nothing is reported as `changed: false` and leaves the current image intact —
    the caller asked for a better picture, not for no picture.
    """
    article = _article_or_404(session, slug)
    changed = ensure_article_image(session, article, force=True)
    return ImageRefreshOut(
        slug=article.slug,
        changed=changed,
        cover=article.image_url or article.cover,
        cover_orientation=article.image_orientation or article.cover_orientation,
        image=(
            ArticleImageOut(
                provider=article.image_provider,
                provider_id=article.image_provider_id,
                source_url=article.image_source_url,
                photographer=article.image_photographer,
                photographer_url=article.image_photographer_url,
                width=article.image_width,
                height=article.image_height,
                alt=article.image_alt,
            )
            if article.image_url and article.image_provider
            else None
        ),
        detail="" if changed else "No suitable image found; existing image kept.",
    )


@router.delete("/articles/{slug}/image", response_model=ImageRefreshOut)
def drop_article_image(
    slug: str,
    session: Session = Depends(get_session),
    user: User = Depends(STAFF),
) -> ImageRefreshOut:
    """Forget the stock photo and fall back to the article's authored cover."""
    article = _article_or_404(session, slug)
    clear_image(article)
    session.add(article)
    session.commit()
    session.refresh(article)
    return ImageRefreshOut(
        slug=article.slug,
        changed=True,
        cover=article.cover,
        cover_orientation=article.cover_orientation,
        image=None,
        detail="Reverted to the authored cover.",
    )
