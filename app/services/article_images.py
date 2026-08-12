"""Choose and cache a stock photo for an article.

The provider is called once per article. What comes back is written onto the
row, and every later read serves from there — a dashboard render never touches
Pexels. Clearing `image_url` is what schedules a refetch, which is also how the
regenerate endpoint works: it overwrites the same ten fields rather than
creating a second image record.

Orientation has two meanings here and they are deliberately separate:

* what the *layout* needs — `cover_orientation` on the article, which is what
  gets requested from the provider;
* what the *photo actually is* — derived from the width and height the provider
  returns, and what gets stored.

They usually agree. When they do not, the pixels win, because the card sizes
itself from the stored value and a wrong one is exactly the whitespace bug this
was meant to remove.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from app.models.social import Article
from app.services.stock_images import StockImage, build_query, get_stock_image

logger = logging.getLogger("medly.article_images")


def choose_image(article: Article) -> Optional[StockImage]:
    """Ask the provider for something appropriate to this article. No writes."""
    return get_stock_image(
        build_query(
            title=article.title,
            category=article.tag,
            description=article.excerpt,
        ),
        orientation=article.cover_orientation or "landscape",
    )


def apply_image(article: Article, image: StockImage) -> None:
    """Overwrite the cached photo in place."""
    for field, value in image.as_fields().items():
        setattr(article, field, value)


def clear_image(article: Article) -> None:
    """Forget the cached photo, so the authored cover shows again."""
    for field, value in {
        "image_provider": "", "image_provider_id": "", "image_url": "",
        "image_source_url": "", "image_photographer": "",
        "image_photographer_url": "", "image_width": 0, "image_height": 0,
        "image_orientation": "", "image_alt": "",
    }.items():
        setattr(article, field, value)


def ensure_article_image(
    session: Session, article: Article, *, force: bool = False
) -> bool:
    """Fill in a photo if the article has none. Returns True if one was stored.

    `force` re-runs the lookup for an article that already has one — the
    regenerate path. A failed lookup during a forced refresh leaves the existing
    photo alone rather than clearing it: a poor image beats no image.
    """
    if article.image_url and not force:
        return False

    image = choose_image(article)
    if image is None:
        logger.info("no stock image found for %r — keeping existing", article.slug)
        return False

    apply_image(article, image)
    session.add(article)
    session.commit()
    session.refresh(article)
    logger.info(
        "stored %s photo %s (%dx%d, %s) for %r",
        image.provider, image.provider_id, image.width, image.height,
        image.orientation, article.slug,
    )
    return True


def backfill(session: Session, *, force: bool = False, limit: int = 0) -> int:
    """Resolve images for every article missing one. Returns how many changed."""
    statement = select(Article)
    if not force:
        statement = statement.where(Article.image_url == "")
    articles = session.exec(statement).all()
    if limit:
        articles = articles[:limit]

    changed = 0
    for article in articles:
        if ensure_article_image(session, article, force=force):
            changed += 1
    return changed


# --------------------------------------------------------- virtual patients --

def choose_patient_image(
    *,
    age: int = 0,
    sex: str = "",
    specialty: str = "",
    presenting_complaint: str = "",
    orientation: str = "landscape",
) -> Optional[StockImage]:
    """A scenario-appropriate photograph for a Virtual Patient case.

    Nothing calls this on its own. It exists so that a case can be given a
    photograph deliberately, with the demographic carried into the query — a
    paediatric scenario illustrated by a stock photo of an adult is worse than
    no photograph, and the query is where that is prevented.
    """
    if age and age < 16:
        who = "child patient" if not sex else f"{'girl' if sex.lower().startswith('f') else 'boy'} child patient"
    elif age >= 65:
        who = "elderly patient" if not sex else (
            "elderly woman patient" if sex.lower().startswith("f") else "elderly man patient"
        )
    elif sex:
        who = "woman patient" if sex.lower().startswith("f") else "man patient"
    else:
        who = "patient"

    return get_stock_image(
        build_query(title=presenting_complaint, category=specialty or "medical news"),
        orientation=orientation,
        category=who,
    )
