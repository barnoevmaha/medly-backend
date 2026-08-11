"""Library and Saved are separate: saving never removes anything from Library."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_library_holds_books_pdfs_and_videos(client: TestClient, student_headers: dict) -> None:
    resources = client.get("/api/resources", headers=student_headers).json()
    kinds = {resource["kind"] for resource in resources}
    assert {"book", "pdf", "video"} <= kinds
    for kind in ("book", "pdf", "video"):
        filtered = client.get(f"/api/resources?kind={kind}", headers=student_headers).json()
        assert filtered and all(item["kind"] == kind for item in filtered)


def test_saving_leaves_the_resource_in_the_library(
    client: TestClient, student_headers: dict
) -> None:
    before = client.get("/api/resources", headers=student_headers).json()
    target = next(item for item in before if item["kind"] == "book")

    client.post(
        "/api/saved",
        json={"item_type": "book", "item_key": target["slug"]},
        headers=student_headers,
    )

    after = client.get("/api/resources", headers=student_headers).json()
    assert len(after) == len(before), "the library must not shrink when something is saved"

    still_there = next(item for item in after if item["slug"] == target["slug"])
    assert still_there["saved"] is True, "the library marks it as saved, it does not remove it"

    saved = client.get("/api/saved?item_type=book", headers=student_headers).json()
    assert any(item["item_key"] == target["slug"] for item in saved)


def test_removing_from_saved_leaves_the_library_intact(
    client: TestClient, student_headers: dict
) -> None:
    resources = client.get("/api/resources", headers=student_headers).json()
    target = next(item for item in resources if item["kind"] == "video")

    client.post(
        "/api/saved",
        json={"item_type": "video", "item_key": target["slug"]},
        headers=student_headers,
    )
    client.delete(
        f"/api/saved?item_type=video&item_key={target['slug']}", headers=student_headers
    )

    after = client.get("/api/resources", headers=student_headers).json()
    assert any(item["slug"] == target["slug"] for item in after)
    assert next(item for item in after if item["slug"] == target["slug"])["saved"] is False


def test_a_resource_cannot_be_saved_under_the_wrong_type(
    client: TestClient, student_headers: dict
) -> None:
    resources = client.get("/api/resources", headers=student_headers).json()
    book = next(item for item in resources if item["kind"] == "book")
    response = client.post(
        "/api/saved",
        json={"item_type": "video", "item_key": book["slug"]},
        headers=student_headers,
    )
    assert response.status_code == 422


def test_saved_holds_all_four_types_at_once(client: TestClient, premium_headers: dict) -> None:
    articles = client.get("/api/feed/articles", headers=premium_headers).json()
    client.post(
        "/api/saved",
        json={"item_type": "article", "item_key": articles[0]["slug"]},
        headers=premium_headers,
    )
    resources = client.get("/api/resources", headers=premium_headers).json()
    for kind in ("book", "pdf", "video"):
        resource = next(item for item in resources if item["kind"] == kind)
        client.post(
            "/api/saved",
            json={"item_type": kind, "item_key": resource["slug"]},
            headers=premium_headers,
        )

    counts = client.get("/api/saved/counts", headers=premium_headers).json()
    assert counts["article"] >= 1
    assert counts["book"] >= 1
    assert counts["pdf"] >= 1
    assert counts["video"] >= 1
    assert counts["all"] == counts["article"] + counts["book"] + counts["pdf"] + counts["video"]
