"""Feed search, comments, and the Saved collection."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_feed_search_matches_the_article_body_not_only_the_title(
    client: TestClient, student_headers: dict
) -> None:
    """The requirement in one test.

    "neuroplasticity" appears in the body of an article whose title does not
    contain the word. A title-only filter would return nothing here.
    """
    response = client.get("/api/feed/articles?q=neuroplasticity", headers=student_headers)
    assert response.status_code == 200, response.text
    results = response.json()
    assert results, "expected at least one article whose body mentions neuroplasticity"
    assert any("neuroplasticity" not in item["title"].lower() for item in results)


def test_feed_search_is_case_insensitive(client: TestClient, student_headers: dict) -> None:
    lower = client.get("/api/feed/articles?q=immune system", headers=student_headers).json()
    upper = client.get("/api/feed/articles?q=IMMUNE SYSTEM", headers=student_headers).json()
    assert [item["slug"] for item in lower] == [item["slug"] for item in upper]
    assert lower


def test_article_detail_has_more_than_the_card(client: TestClient, student_headers: dict) -> None:
    listing = client.get("/api/feed/articles", headers=student_headers).json()
    slug = listing[0]["slug"]
    detail = client.get(f"/api/feed/articles/{slug}", headers=student_headers).json()
    assert len(detail["body_md"]) > len(detail["excerpt"]) * 3
    assert "comments" in detail


def test_comment_round_trip(client: TestClient, student_headers: dict) -> None:
    listing = client.get("/api/feed/articles", headers=student_headers).json()
    slug = listing[0]["slug"]

    created = client.post(
        f"/api/feed/articles/{slug}/comments",
        json={"body": "Does the override rate get published anywhere?"},
        headers=student_headers,
    )
    assert created.status_code == 201, created.text

    detail = client.get(f"/api/feed/articles/{slug}", headers=student_headers).json()
    assert any(comment["id"] == created.json()["id"] for comment in detail["comments"])

    removed = client.delete(f"/api/feed/comments/{created.json()['id']}", headers=student_headers)
    assert removed.status_code == 204


def test_saving_is_idempotent_and_persists(client: TestClient, student_headers: dict) -> None:
    listing = client.get("/api/feed/articles", headers=student_headers).json()
    slug = listing[0]["slug"]

    first = client.post(
        "/api/saved", json={"item_type": "article", "item_key": slug}, headers=student_headers
    )
    second = client.post(
        "/api/saved", json={"item_type": "article", "item_key": slug}, headers=student_headers
    )
    assert first.status_code == 201 and second.status_code == 201

    saved = client.get("/api/saved?item_type=article", headers=student_headers).json()
    assert sum(1 for item in saved if item["item_key"] == slug) == 1, "duplicate saved row"

    # A fresh request is a fresh session — this is what "survives a refresh" means.
    reloaded = client.get("/api/feed/articles", headers=student_headers).json()
    assert next(item for item in reloaded if item["slug"] == slug)["saved"] is True

    client.delete(
        f"/api/saved?item_type=article&item_key={slug}", headers=student_headers
    )
    after = client.get("/api/saved?item_type=article", headers=student_headers).json()
    assert all(item["item_key"] != slug for item in after)


def test_every_content_type_can_be_saved(client: TestClient, student_headers: dict) -> None:
    resources = client.get("/api/resources", headers=student_headers).json()
    for kind in ("book", "pdf", "video"):
        resource = next(item for item in resources if item["kind"] == kind)
        response = client.post(
            "/api/saved",
            json={"item_type": kind, "item_key": resource["slug"]},
            headers=student_headers,
        )
        assert response.status_code == 201, response.text

    counts = client.get("/api/saved/counts", headers=student_headers).json()
    assert counts["book"] >= 1 and counts["pdf"] >= 1 and counts["video"] >= 1
