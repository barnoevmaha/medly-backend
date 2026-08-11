"""Medly AI (Gemini provider) — wiring, limits and failure modes.

No network. `httpx.Client.post` is replaced with a fake, so these assert what
the code does with a response rather than what Google returns.
"""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.routers import assistant as assistant_router
from app.services import gemini
from app.services.assistant import GeminiProvider


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or json.dumps(payload or {})
        self.headers: dict = {}

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def ok_payload(text: str = "## Definition\n\nAcute kidney injury is…") -> dict:
    return {
        "candidates": [
            {"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}
        ]
    }


@pytest.fixture
def gemini_on(monkeypatch):
    """Point the app at the Gemini provider with a dummy key."""
    monkeypatch.setattr(settings, "assistant_provider", "gemini", raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "gemini_model", "gemini-3.5-flash", raising=False)
    assistant_router._limiter.reset()
    yield
    assistant_router._limiter.reset()


def patch_post(monkeypatch, responses):
    """Serve `responses` in order; record every request body."""
    sent = []
    queue = list(responses)

    def fake_post(self, url, json=None, headers=None):  # noqa: A002
        sent.append({"url": url, "body": json, "headers": headers or {}})
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    return sent


# --------------------------------------------------------------------------
# provider
# --------------------------------------------------------------------------

def test_provider_sends_system_prompt_and_history(gemini_on, monkeypatch) -> None:
    sent = patch_post(monkeypatch, [FakeResponse(200, ok_payload())])

    reply = GeminiProvider().reply(
        "What are the main causes?",
        [{"role": "user", "content": "What is nephrotic syndrome?"},
         {"role": "assistant", "content": "It is…"}],
    )

    assert reply.content.startswith("## Definition")
    assert reply.provider == "gemini:gemini-3.5-flash"

    body = sent[0]["body"]
    assert "Medly AI" in body["systemInstruction"]["parts"][0]["text"]
    # assistant turns are converted to Gemini's "model" role
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]
    assert body["generationConfig"]["maxOutputTokens"] == settings.ai_max_output_tokens
    # the key travels in a header, never in the URL
    assert sent[0]["headers"]["x-goog-api-key"] == "test-key"
    assert "test-key" not in sent[0]["url"]


def test_article_context_is_passed_as_system_context(gemini_on, monkeypatch) -> None:
    sent = patch_post(monkeypatch, [FakeResponse(200, ok_payload())])
    GeminiProvider().reply("Why does ST elevation occur?", [], "CONTEXT — an article body")
    assert "CONTEXT — an article body" in sent[0]["body"]["systemInstruction"]["parts"][0]["text"]


def test_missing_key_raises_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "gemini_api_key", "", raising=False)
    with pytest.raises(gemini.GeminiNotConfigured):
        gemini.generate(system_prompt="s", history=[], message="Explain sepsis")


def test_auth_error_is_not_retried(gemini_on, monkeypatch) -> None:
    sent = patch_post(monkeypatch, [FakeResponse(403, {}, "forbidden")])
    with pytest.raises(gemini.GeminiAuthError):
        gemini.generate(system_prompt="s", history=[], message="Explain sepsis")
    assert len(sent) == 1


def test_model_not_found(gemini_on, monkeypatch) -> None:
    patch_post(monkeypatch, [FakeResponse(404, {}, "not found")])
    with pytest.raises(gemini.GeminiModelNotFound):
        gemini.generate(system_prompt="s", history=[], message="Explain sepsis")


def test_429_retries_then_gives_up(gemini_on, monkeypatch) -> None:
    monkeypatch.setattr(gemini, "BASE_BACKOFF_SECONDS", 0.0)
    sent = patch_post(monkeypatch, [FakeResponse(429, {}, "quota")])
    with pytest.raises(gemini.GeminiRateLimited):
        gemini.generate(system_prompt="s", history=[], message="Explain sepsis")
    assert len(sent) == gemini.MAX_ATTEMPTS  # 1 try + 2 retries, then stop


def test_transient_500_then_success(gemini_on, monkeypatch) -> None:
    monkeypatch.setattr(gemini, "BASE_BACKOFF_SECONDS", 0.0)
    patch_post(monkeypatch, [FakeResponse(503, {}, "unavailable"), FakeResponse(200, ok_payload())])
    result = gemini.generate(system_prompt="s", history=[], message="Explain sepsis")
    assert result.text.startswith("## Definition")


def test_empty_candidates_is_handled(gemini_on, monkeypatch) -> None:
    patch_post(monkeypatch, [FakeResponse(200, {"promptFeedback": {"blockReason": "SAFETY"}})])
    with pytest.raises(gemini.GeminiBadResponse):
        gemini.generate(system_prompt="s", history=[], message="Explain sepsis")


# --------------------------------------------------------------------------
# endpoint
# --------------------------------------------------------------------------

def test_chat_returns_gemini_answer(client: TestClient, student_headers: dict, gemini_on, monkeypatch) -> None:
    patch_post(monkeypatch, [FakeResponse(200, ok_payload())])
    response = client.post(
        "/api/assistant/chat",
        json={"message": "Explain acute kidney injury"},
        headers=student_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert "Definition" in body["reply"]
    assert body["model"] == "gemini-3.5-flash"
    assert body["session_id"]
    assert body["disclaimer"]


def test_rate_limit_returns_429_and_friendly_message(
    client: TestClient, student_headers: dict, gemini_on, monkeypatch
) -> None:
    patch_post(monkeypatch, [FakeResponse(200, ok_payload())])
    monkeypatch.setattr(assistant_router._limiter, "per_minute", 2)

    for _ in range(2):
        assert client.post(
            "/api/assistant/chat", json={"message": "Explain sepsis"}, headers=student_headers
        ).status_code == 200

    blocked = client.post(
        "/api/assistant/chat", json={"message": "Explain sepsis"}, headers=student_headers
    )
    assert blocked.status_code == 429
    assert "limit" in blocked.json()["detail"].lower()


def test_upstream_429_becomes_friendly_message(
    client: TestClient, student_headers: dict, gemini_on, monkeypatch
) -> None:
    monkeypatch.setattr(gemini, "BASE_BACKOFF_SECONDS", 0.0)
    patch_post(monkeypatch, [FakeResponse(429, {}, "quota exceeded")])
    response = client.post(
        "/api/assistant/chat", json={"message": "Explain sepsis"}, headers=student_headers
    )
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail == "Medly AI is temporarily busy. Please try again in a moment."
    # no raw provider error, no key
    assert "quota exceeded" not in detail


def test_message_length_is_capped(client: TestClient, student_headers: dict, gemini_on) -> None:
    response = client.post(
        "/api/assistant/chat",
        json={"message": "x" * (settings.ai_max_message_chars + 1)},
        headers=student_headers,
    )
    assert response.status_code == 422


def test_quick_action_needs_no_typed_message(
    client: TestClient, student_headers: dict, gemini_on, monkeypatch
) -> None:
    sent = patch_post(monkeypatch, [FakeResponse(200, ok_payload())])
    response = client.post(
        "/api/assistant/chat", json={"action": "quiz"}, headers=student_headers
    )
    assert response.status_code == 200
    asked = sent[0]["body"]["contents"][-1]["parts"][0]["text"]
    assert "Quiz me" in asked


def test_chat_requires_authentication(client: TestClient) -> None:
    assert client.post("/api/assistant/chat", json={"message": "Explain sepsis"}).status_code == 401


def test_rules_provider_still_default(client: TestClient, student_headers: dict) -> None:
    """The offline path must keep working with no key set."""
    response = client.post(
        "/api/assistant/chat",
        json={"message": "What is automation bias?"},
        headers=student_headers,
    )
    assert response.status_code == 200
    assert response.json()["provider"] == "rules"


# --------------------------------------------------------------------------
# streaming
# --------------------------------------------------------------------------

class FakeStream:
    """Stands in for httpx's streaming response context manager."""

    def __init__(self, status_code: int, lines: list[str], text: str = ""):
        self.status_code = status_code
        self._lines = lines
        self.text = text
        self.headers: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b""

    def iter_lines(self):
        yield from self._lines


def sse(text: str) -> str:
    return "data: " + json.dumps(
        {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    )


def patch_stream(monkeypatch, stream):
    def fake_stream(self, method, url, json=None, headers=None):  # noqa: A002
        return stream

    monkeypatch.setattr(httpx.Client, "stream", fake_stream)


def test_generate_stream_yields_fragments(gemini_on, monkeypatch) -> None:
    patch_stream(
        monkeypatch,
        FakeStream(200, [sse("Myocardial "), "", sse("infarction "), sse("occurs.")]),
    )
    out = list(gemini.generate_stream(system_prompt="s", history=[], message="Explain sepsis"))
    assert out == ["Myocardial ", "infarction ", "occurs."]


def test_generate_stream_maps_http_errors(gemini_on, monkeypatch) -> None:
    patch_stream(monkeypatch, FakeStream(429, [], "quota"))
    with pytest.raises(gemini.GeminiRateLimited):
        list(gemini.generate_stream(system_prompt="s", history=[], message="Explain sepsis"))


def test_stream_endpoint_emits_sse_and_saves_one_message(
    client: TestClient, student_headers: dict, gemini_on, monkeypatch
) -> None:
    patch_stream(monkeypatch, FakeStream(200, [sse("Acute "), sse("kidney injury.")]))

    with client.stream(
        "POST",
        "/api/assistant/chat/stream",
        json={"message": "Explain AKI"},
        headers=student_headers,
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    assert "event: start" in body
    assert body.count("event: chunk") == 2
    assert "event: done" in body
    assert "Acute " in body and "kidney injury." in body

    # One assistant row for the whole answer, not one per chunk.
    session_id = json.loads(body.split("event: start\ndata: ")[1].split("\n")[0])["session_id"]
    history = client.get(
        f"/api/assistant/history/{session_id}", headers=student_headers
    ).json()
    answers = [row for row in history if row["role"] == "assistant"]
    assert len(answers) == 1
    assert answers[0]["content"].startswith("Acute kidney injury.")


def test_stream_respects_rate_limit(
    client: TestClient, student_headers: dict, gemini_on, monkeypatch
) -> None:
    patch_stream(monkeypatch, FakeStream(200, [sse("ok")]))
    monkeypatch.setattr(assistant_router._limiter, "per_minute", 1)

    with client.stream(
        "POST", "/api/assistant/chat/stream",
        json={"message": "Explain sepsis"}, headers=student_headers,
    ) as first:
        assert first.status_code == 200
        first.read()

    blocked = client.post(
        "/api/assistant/chat/stream", json={"message": "Explain asthma"}, headers=student_headers
    )
    assert blocked.status_code == 429


def test_stream_requires_authentication(client: TestClient) -> None:
    assert client.post("/api/assistant/chat/stream", json={"message": "Explain sepsis"}).status_code == 401
