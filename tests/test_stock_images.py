"""The stock image service, its fallbacks, and the cache that protects the API.

Pexels is never called for real here. Every test substitutes the HTTP layer, in
the same spirit as the Gemini tests: what is under test is our selection,
orientation and fallback logic, not their service.
"""
from __future__ import annotations

from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models.social import Article
from app.services import stock_images
from app.services.article_images import ensure_article_image
from app.services.stock_images import build_query, get_stock_image, orientation_of


def _photo(pid: int, width: int, height: int) -> dict:
    return {
        "id": pid,
        "width": width,
        "height": height,
        "url": f"https://www.pexels.com/photo/{pid}/",
        "photographer": "A Photographer",
        "photographer_url": "https://www.pexels.com/@someone",
        "alt": "a clinical scene",
        "src": {"large": f"https://images.pexels.com/photos/{pid}/large.jpg"},
    }


class _Response:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            # Real Request/Response objects rather than None: httpx does not
            # validate these at runtime today, but an exception whose .request
            # raises when something reads it is a trap for the next person.
            request = httpx.Request("GET", stock_images._ENDPOINT)
            raise httpx.HTTPStatusError(
                f"Client error '{self.status_code}' for url '{stock_images._ENDPOINT}'",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )

    def json(self) -> dict:
        return self._payload


def _with_pexels_key(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    """Point the service at a different key for the duration of one test.

    `Settings` is a frozen dataclass, so `setattr(settings, ...)` raises
    FrozenInstanceError. A replacement instance is bound onto the module under
    test instead — which is also the only object `get_stock_image` reads.
    """
    monkeypatch.setattr(stock_images, "settings", replace(settings, pexels_api_key=key))


@pytest.fixture()
def with_key(monkeypatch: pytest.MonkeyPatch):
    _with_pexels_key(monkeypatch, "test-key")


_IMAGE_FIELDS = (
    "image_provider", "image_provider_id", "image_url", "image_source_url",
    "image_photographer", "image_photographer_url", "image_width",
    "image_height", "image_orientation", "image_alt",
)


@pytest.fixture()
def article_id():
    """The first seeded article, with its image fields put back afterwards.

    The database is seeded once for the whole session, so a test that writes a
    photo onto a row leaves it there for every test that runs later — including
    the ones in other files. Restoring keeps these order-independent, and keeps
    `ensure_article_image` seeing the empty `image_url` it needs to do anything.
    Ordering by id rather than relying on the database's natural order is the
    other half of that: the same row every run.
    """
    with Session(engine) as session:
        article = session.exec(select(Article).order_by(Article.id)).first()
        assert article is not None, "seed produced no articles"
        pk = article.id
        before = {field: getattr(article, field) for field in _IMAGE_FIELDS}

    yield pk

    with Session(engine) as session:
        article = session.get(Article, pk)
        for field, value in before.items():
            setattr(article, field, value)
        session.add(article)
        session.commit()


# ------------------------------------------------------------ orientation --

@pytest.mark.parametrize(
    "width,height,expected",
    [
        (1920, 1080, "landscape"),
        (4000, 3000, "landscape"),   # 4:3 is still landscape
        (1080, 1920, "portrait"),
        (800, 1000, "portrait"),
        (1000, 1000, "square"),
        (1050, 1000, "square"),      # near-square must not be cropped as 16:9
        (0, 0, "landscape"),         # unknown falls back rather than dividing
    ],
)
def test_orientation_comes_from_real_dimensions(width, height, expected) -> None:
    assert orientation_of(width, height) == expected


def test_picks_the_photo_whose_pixels_match_the_request(
    with_key, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pexels' own orientation filter is a hint; the dimensions decide."""
    payload = {"photos": [_photo(1, 1080, 1920), _photo(2, 1000, 1000), _photo(3, 1920, 1080)]}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Response(payload))

    landscape = get_stock_image("neurology brain", orientation="landscape")
    assert landscape is not None and landscape.provider_id == "3"
    assert landscape.orientation == "landscape"

    portrait = get_stock_image("neurology brain", orientation="portrait")
    assert portrait is not None and portrait.provider_id == "1"
    assert portrait.orientation == "portrait"

    square = get_stock_image("neurology brain", orientation="square")
    assert square is not None and square.provider_id == "2"
    assert square.orientation == "square"


def test_requested_orientation_is_sent_to_the_provider(
    with_key, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(params or {})
        seen["auth"] = (headers or {}).get("Authorization")
        return _Response({"photos": [_photo(9, 1920, 1080)]})

    monkeypatch.setattr(httpx, "get", fake_get)
    get_stock_image("brain mri", orientation="portrait")
    assert seen["orientation"] == "portrait"
    assert seen["auth"] == "test-key"


# --------------------------------------------------------------- failures --

def test_no_api_key_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_pexels_key(monkeypatch, "")

    def never(*args, **kwargs):  # pragma: no cover - asserts it is not reached
        raise AssertionError("Pexels must not be called without a key")

    monkeypatch.setattr(httpx, "get", never)
    assert get_stock_image("anything") is None


def test_failed_request_returns_none(with_key, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise httpx.ConnectTimeout("no route")

    monkeypatch.setattr(httpx, "get", boom)
    assert get_stock_image("brain mri") is None


def test_error_status_returns_none(with_key, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Response({}, status=429))
    assert get_stock_image("brain mri") is None


def test_empty_result_set_returns_none(with_key, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Response({"photos": []}))
    assert get_stock_image("something with no photographs") is None


def test_malformed_payload_returns_none(with_key, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Response({"unexpected": True}))
    assert get_stock_image("brain mri") is None


def test_photo_without_a_usable_source_is_rejected(
    with_key, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = _photo(4, 1920, 1080)
    broken["src"] = {}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Response({"photos": [broken]}))
    assert get_stock_image("brain mri") is None


# ------------------------------------------------------------------ query --

def test_query_leads_with_the_category_not_the_headline() -> None:
    query = build_query(
        title="Post-Concussion Syndrome: When Symptoms Don't Go Away",
        category="Neurology",
    )
    assert query.startswith("brain mri scan neurology")
    # "when", "go" and "away" would retrieve stock photos of sad people.
    for stopword in (" when", " away", " go "):
        assert stopword not in f" {query} "


def test_query_falls_back_when_nothing_is_known() -> None:
    assert build_query() == "medicine hospital clinical"


# ------------------------------------------------------------------ cache --

def test_an_article_with_an_image_is_not_refetched(
    client: TestClient, with_key, article_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def counting_get(*args, **kwargs):
        calls["n"] += 1
        return _Response({"photos": [_photo(7, 1920, 1080)]})

    monkeypatch.setattr(httpx, "get", counting_get)

    with Session(engine) as session:
        article = session.get(Article, article_id)
        assert article is not None
        assert not article.image_url, "the seed must not ship a stock photo"

        assert ensure_article_image(session, article) is True
        assert calls["n"] == 1
        assert article.image_url.endswith("/7/large.jpg")

        # Second call must serve from the row, not the provider.
        assert ensure_article_image(session, article) is False
        assert calls["n"] == 1

        # Regenerating replaces the same fields rather than adding a second one.
        monkeypatch.setattr(
            httpx, "get", lambda *a, **k: _Response({"photos": [_photo(8, 1000, 1000)]})
        )
        assert ensure_article_image(session, article, force=True) is True
        assert article.image_provider_id == "8"
        assert article.image_orientation == "square"


def test_a_failed_lookup_keeps_the_existing_image(
    client: TestClient, with_key, article_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine) as session:
        article = session.get(Article, article_id)
        assert article is not None
        monkeypatch.setattr(
            httpx, "get", lambda *a, **k: _Response({"photos": [_photo(11, 1920, 1080)]})
        )
        ensure_article_image(session, article, force=True)
        before = article.image_url

        def boom(*args, **kwargs):
            raise httpx.ConnectTimeout("gone")

        monkeypatch.setattr(httpx, "get", boom)
        assert ensure_article_image(session, article, force=True) is False
        assert article.image_url == before


# -------------------------------------------------------------- endpoints --

def test_regenerate_requires_staff(client: TestClient, student_headers: dict) -> None:
    listing = client.get("/api/feed/articles", headers=student_headers).json()
    slug = listing[0]["slug"]
    response = client.post(
        f"/api/feed/articles/{slug}/image/regenerate", headers=student_headers
    )
    assert response.status_code in (401, 403)


def test_article_response_never_carries_the_api_key(
    client: TestClient, student_headers: dict, with_key
) -> None:
    body = client.get("/api/feed/articles", headers=student_headers).text
    assert "test-key" not in body
