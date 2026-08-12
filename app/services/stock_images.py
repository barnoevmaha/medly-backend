"""Stock imagery from Pexels, behind one reusable call.

`get_stock_image(query=..., orientation=..., category=...)` is the whole public
surface. Articles use it today; anything else that needs a picture can use the
same call rather than growing a second integration.

Three things this deliberately does:

* **Never runs on a page load.** Results are stored on the row that needed them
  (see `image_*` on `Article`) and re-read from there. Pexels is called when an
  image is first chosen or explicitly regenerated, not when a dashboard renders.
* **Fails soft, always.** No key, no network, a 429, a malformed payload or an
  empty result set all return `None`. The caller keeps whatever image it already
  had, and the placeholder catches the rest — a missing photo must never render
  as a broken one.
* **Trusts the pixels, not the query string.** `orientation=` is passed to
  Pexels as a hint, but the orientation recorded against the article is derived
  from the width and height Pexels actually returns, because the two do not
  always agree.

The API key is read from the environment and used only here, server-side. It is
never included in any response model, so it cannot reach the browser.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger("medly.stock_images")

PROVIDER = "pexels"
_ENDPOINT = "https://api.pexels.com/v1/search"

LANDSCAPE, PORTRAIT, SQUARE = "landscape", "portrait", "square"
ORIENTATIONS = (LANDSCAPE, PORTRAIT, SQUARE)

# Ratio bands. A 4:3 photo is landscape, a 5:4 is close enough to square that
# forcing it into a 16:9 slot would crop it badly.
_LANDSCAPE_FROM = 1.15
_PORTRAIT_UNDER = 0.87


@dataclass(frozen=True)
class StockImage:
    """Everything needed to render and credit a photo, with nothing secret."""

    provider: str
    provider_id: str
    url: str
    source_url: str
    photographer: str
    photographer_url: str
    width: int
    height: int
    orientation: str
    alt: str

    def as_fields(self, prefix: str = "image_") -> Dict[str, Any]:
        """Flatten onto a model that stores these with an `image_` prefix."""
        return {f"{prefix}{k}": v for k, v in asdict(self).items()}


def orientation_of(width: int, height: int) -> str:
    """The orientation the pixels actually describe."""
    if not width or not height:
        return LANDSCAPE
    ratio = width / height
    if ratio >= _LANDSCAPE_FROM:
        return LANDSCAPE
    if ratio <= _PORTRAIT_UNDER:
        return PORTRAIT
    return SQUARE


# ---------------------------------------------------------------- query ----

_STOPWORDS = {
    "a", "an", "and", "the", "of", "for", "with", "when", "what", "why", "how",
    "is", "are", "was", "were", "to", "in", "on", "at", "it", "its", "that",
    "this", "your", "you", "not", "no", "go", "away", "does", "do", "must",
    "confront", "hidden", "under", "after", "before", "about", "into", "from",
}

# A title alone makes a poor image search: "When Symptoms Don't Go Away"
# retrieves stock photos of people looking sad. Pairing the article's own
# category with a concrete visual subject is what keeps results on-topic.
_CATEGORY_TERMS = {
    "neurology": "brain mri scan neurology",
    "oncology": "laboratory research microscope oncology",
    "cardiology": "heart ecg cardiology monitor",
    "radiology": "radiology x-ray lightbox",
    "surgery": "operating theatre surgery",
    "paediatrics": "paediatric doctor child patient",
    "pediatrics": "paediatric doctor child patient",
    "emergency medicine": "emergency department hospital resuscitation",
    "clinical ai": "medical technology data screen",
    "medical news": "hospital clinical medicine",
    "sponsored": "hospital clinical medicine",
}

_DEFAULT_TERMS = "medicine hospital clinical"


def build_query(
    title: str = "",
    category: str = "",
    tags: Optional[List[str]] = None,
    description: str = "",
) -> str:
    """Turn what we know about a piece of content into a search Pexels can use.

    Category leads, because it names a visual subject; a few distinctive words
    from the title follow, to keep two neurology articles from resolving to the
    same photograph.
    """
    category_key = (category or "").strip().lower()
    lead = _CATEGORY_TERMS.get(category_key, "")
    if not lead and category_key:
        lead = category_key

    # Anything already in the lead is dropped, so an "Oncology" article does
    # not search for "oncology ... oncology".
    seen = set((lead or _DEFAULT_TERMS).split())
    words: List[str] = []
    for source in (title, " ".join(tags or []), description[:160]):
        for raw in re.split(r"[^A-Za-z]+", source or ""):
            word = raw.lower()
            if len(word) > 3 and word not in _STOPWORDS and word not in seen:
                seen.add(word)
                words.append(word)

    query = " ".join(filter(None, [lead or _DEFAULT_TERMS, *words[:3]]))
    return query.strip() or _DEFAULT_TERMS


# ---------------------------------------------------------------- fetch ----


def _pick(photos: List[Dict[str, Any]], wanted: str) -> Optional[Dict[str, Any]]:
    """Prefer a photo whose real dimensions match what was asked for."""
    for photo in photos:
        if orientation_of(photo.get("width", 0), photo.get("height", 0)) == wanted:
            return photo
    return photos[0] if photos else None


def _to_stock_image(photo: Dict[str, Any]) -> Optional[StockImage]:
    sources = photo.get("src") or {}
    # `large` is ~940px wide and is what the cards render; `original` is the
    # full-resolution file and is far too heavy for a feed.
    url = sources.get("large") or sources.get("medium") or sources.get("original")
    if not url:
        return None
    width = int(photo.get("width") or 0)
    height = int(photo.get("height") or 0)
    return StockImage(
        provider=PROVIDER,
        provider_id=str(photo.get("id") or ""),
        url=url,
        source_url=photo.get("url") or "",
        photographer=photo.get("photographer") or "",
        photographer_url=photo.get("photographer_url") or "",
        width=width,
        height=height,
        orientation=orientation_of(width, height),
        alt=(photo.get("alt") or "").strip(),
    )


def get_stock_image(
    query: str,
    orientation: str = LANDSCAPE,
    category: str = "",
    *,
    per_page: int = 15,
) -> Optional[StockImage]:
    """One appropriate photo, or `None`.

    `None` is a normal outcome — no key configured, provider unreachable, or
    nothing matched — and every caller is expected to fall back rather than
    treat it as an error.
    """
    key = settings.pexels_api_key
    if not key:
        logger.info("PEXELS_API_KEY is not set — skipping stock image lookup")
        return None

    wanted = orientation if orientation in ORIENTATIONS else LANDSCAPE
    search = " ".join(filter(None, [query, category])).strip() or _DEFAULT_TERMS

    try:
        response = httpx.get(
            _ENDPOINT,
            params={"query": search, "orientation": wanted, "per_page": per_page},
            headers={"Authorization": key},
            timeout=settings.pexels_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # Includes timeouts, 429s and malformed JSON. Never raised onward: the
        # caller has a fallback and a broken image is worse than an old one.
        logger.warning("pexels lookup failed for %r — %s", search, exc)
        return None

    photos = payload.get("photos") if isinstance(payload, dict) else None
    if not isinstance(photos, list) or not photos:
        logger.info("pexels returned no photos for %r", search)
        return None

    chosen = _pick(photos, wanted)
    return _to_stock_image(chosen) if chosen else None
