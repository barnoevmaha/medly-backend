"""Feed articles, engagement, library resources and the Saved collection."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Article(SQLModel, table=True):
    """A feed item with a full body, not just the card copy.

    `excerpt` is what the card shows; `body_md` is the article a reader opens.
    Search runs over both plus the title — see routers/feed.py.
    """

    __tablename__ = "articles"

    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    tag: str = Field(default="Medical News", index=True)
    title: str
    excerpt: str = Field(default="")
    body_md: str = Field(default="")
    # Machine-translated on first read in that language and cached here from
    # then on — see app/services/translate.py and app/services/localize.py.
    # Blank means "not translated yet"; the API falls back to English, never
    # blank text.
    title_ru: str = Field(default="")
    title_uz: str = Field(default="")
    excerpt_ru: str = Field(default="")
    excerpt_uz: str = Field(default="")
    body_md_ru: str = Field(default="")
    body_md_uz: str = Field(default="")
    author: str = Field(default="Medly")
    author_role: str = Field(default="")
    read_minutes: int = Field(default=5)
    # Cover art. A path under /covers, generated as SVG at build time so there
    # are no external requests and no layout shift; `cover_alt` describes it.
    cover: str = Field(default="")
    cover_alt: str = Field(default="")
    # The cover's shape, so a card can reserve the right box before the image
    # loads. Stored rather than measured: the browser only learns an image's
    # real dimensions after fetching it, and a card that guesses 16:9 and then
    # reflows to a portrait photo is the layout shift this avoids.
    # landscape | portrait | square
    cover_orientation: str = Field(default="landscape")

    # A stock photo chosen for this article, cached here so the provider is
    # called once per article rather than once per page load. `image_url` being
    # set is what marks the article as resolved; clearing it schedules a refetch.
    # Width and height are the provider's real dimensions, and image_orientation
    # is derived from them rather than from what was requested.
    image_provider: str = Field(default="")
    image_provider_id: str = Field(default="")
    image_url: str = Field(default="")
    image_source_url: str = Field(default="")
    image_photographer: str = Field(default="")
    image_photographer_url: str = Field(default="")
    image_width: int = Field(default=0)
    image_height: int = Field(default=0)
    image_orientation: str = Field(default="")
    image_alt: str = Field(default="")
    # Language of the content, for the Library language filter. Demo content
    # ships in English, Russian and Uzbek.
    language: str = Field(default="en", index=True)
    # Teacher-authored articles start as drafts and only appear in the library
    # once published.
    published: bool = Field(default=True, index=True)
    created_by: Optional[int] = None
    # Baseline so a fresh install does not show every article on zero.
    base_likes: int = Field(default=0)
    published_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class ArticleComment(SQLModel, table=True):
    __tablename__ = "article_comments"

    id: Optional[int] = Field(default=None, primary_key=True)
    article_id: int = Field(foreign_key="articles.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    body: str
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class ArticleLike(SQLModel, table=True):
    """One row per (user, article). The uniqueness is enforced in the router."""

    __tablename__ = "article_likes"

    id: Optional[int] = Field(default=None, primary_key=True)
    article_id: int = Field(foreign_key="articles.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Resource(SQLModel, table=True):
    """Library material: books, PDFs and videos a student can save."""

    __tablename__ = "resources"

    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    kind: str = Field(default="book", index=True)  # book | pdf | video
    title: str
    author: str = Field(default="")
    description: str = Field(default="")
    # The title is a real published work's title and is not translated (the
    # same convention as author/publisher below). The description is prose
    # about the item, machine-translated on demand — see localize.py.
    description_ru: str = Field(default="")
    description_uz: str = Field(default="")
    rating: float = Field(default=0.0)
    downloads: str = Field(default="")
    duration: str = Field(default="")
    premium: bool = Field(default=False)
    url: str = Field(default="")
    # Per-item destinations. Empty falls back to the shared demo asset in the
    # player/reader route, so swapping in a real URL is a data change.
    video_url: str = Field(default="")
    # Videos only: how the source was shot. The player and the library card
    # read this to frame the item at its own proportions instead of forcing
    # every video into 16:9. landscape | portrait
    orientation: str = Field(default="landscape", index=True)
    pdf_url: str = Field(default="")
    cover_hue: int = Field(default=210)

    # Real metadata, so the Library filters describe something that exists.
    # Nothing here is invented at render time: if a field is blank the UI omits
    # the row rather than showing a placeholder.
    cover: str = Field(default="")
    publisher: str = Field(default="")
    year: Optional[int] = None
    pages: Optional[int] = None
    level: str = Field(default="", index=True)  # foundation | clinical | advanced
    topic: str = Field(default="", index=True)
    language: str = Field(default="en", index=True)  # en | ru | uz
    # Videos only: a number, so the duration filter can compare instead of
    # parsing the display string ("3h 20m").
    duration_minutes: Optional[int] = None
    # Teacher-authored entries start as drafts and only show in the Library
    # once published.
    published: bool = Field(default=True, index=True)
    created_by: Optional[int] = None


class BookProgress(SQLModel, table=True):
    """A student's reading progress on a book, as a percentage 0..100.

    One row per (user, resource); the uniqueness is enforced in the router.
    """

    __tablename__ = "book_progress"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    resource_id: int = Field(index=True)
    percent: int = Field(default=0)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SavedItem(SQLModel, table=True):
    """The user's Saved collection — one table for every content type.

    (user_id, item_type, item_key) is the natural key. The router checks it
    before inserting, so saving twice is a no-op rather than a duplicate row.
    """

    __tablename__ = "saved_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    item_type: str = Field(index=True)  # article | book | pdf | video
    item_key: str = Field(index=True)  # article slug or resource slug
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
