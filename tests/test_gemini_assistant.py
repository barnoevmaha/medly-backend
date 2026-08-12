"""Medly AI (Gemini provider) — wiring, limits and failure modes.

No network. `httpx.Client.post` is replaced with a fake, so these assert what
the code does with a response rather than what Google returns.
"""
from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config
from app.config import settings
from app.routers import assistant as assistant_router
from app.services import assistant as assistant_service
from app.services import gemini
from app.services.assistant import GeminiProvider

# Settings is a frozen dataclass — production code relies on that immutability,
# so tests cannot monkeypatch attributes on the live `settings` instance
# (that raises `dataclasses.FrozenInstanceError`). Instead, build a replacement
# instance with the overridden fields and swap it into every module that holds
# its own `from app.config import settings` reference.
_SETTINGS_MODULES = (config, assistant_router, assistant_service, gemini)


def override_settings(monkeypatch, **overrides):
    """Point every module that imported `settings` at a patched replacement."""
    new_settings = replace(config.settings, **overrides)
    for module in _SETTINGS_MODULES:
        monkeypatch.setattr(module, "settings", new_settings)
    return new_settings


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
    override_settings(
        monkeypatch,
        assistant_provider="gemini",
        gemini_api_key="test-key",
        gemini_model="gemini-3.5-flash",
    )
    assistant_router._limiter.reset()
    yield
    assistant_router._limiter.reset()


def patch_post(monkeypatch, responses):
    """Serve `responses` in order; record every request body.

    `gemini.py` opens a bare `httpx.Client()` per call, so faking it means
    patching `httpx.Client.post` at the class level. `TestClient` is also an
    `httpx.Client` subclass, and its own request dispatch goes through that
    same method — patched carelessly, this would swallow the test's own call
    into the FastAPI app. Only exact `httpx.Client` instances are faked; a
    `TestClient` (or anything else) falls through to the real implementation.
    """
    sent = []
    queue = list(responses)
    real_post = httpx.Client.post

    def fake_post(self, url, *args, **kwargs):  # noqa: A002
        if type(self) is not httpx.Client:
            return real_post(self, url, *args, **kwargs)
        sent.append({"url": url, "body": kwargs.get("json"), "headers": kwargs.get("headers") or {}})
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
    override_settings(monkeypatch, gemini_api_key="")
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


def test_upstream_429_falls_back_to_the_rules_engine(
    client: TestClient, student_headers: dict, gemini_on, monkeypatch
) -> None:
    """Being out of quota must not put an error in front of a student.

    The offline engine answers instead, and the response says so — both in the
    notice the client renders and in the provider recorded for the audit trail.
    """
    monkeypatch.setattr(gemini, "BASE_BACKOFF_SECONDS", 0.0)
    patch_post(monkeypatch, [FakeResponse(429, {}, "quota exceeded")])
    response = client.post(
        "/api/assistant/chat",
        json={"message": "What is automation bias?"},
        headers=student_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "rules (fallback)"
    assert body["notice"]
    assert body["reply"].strip()
    assert body["disclaimer"]
    # the model field must not claim Gemini answered
    assert body["model"] is None
    # no raw provider error anywhere in what reaches the client
    assert "quota exceeded" not in json.dumps(body)


def test_upstream_503_also_falls_back(
    client: TestClient, student_headers: dict, gemini_on, monkeypatch
) -> None:
    monkeypatch.setattr(gemini, "BASE_BACKOFF_SECONDS", 0.0)
    patch_post(monkeypatch, [FakeResponse(503, {}, "unavailable")])
    response = client.post(
        "/api/assistant/chat",
        json={"message": "What is automation bias?"},
        headers=student_headers,
    )
    assert response.status_code == 200
    assert response.json()["provider"] == "rules (fallback)"


def test_auth_failure_still_errors_and_does_not_fall_back(
    client: TestClient, student_headers: dict, gemini_on, monkeypatch
) -> None:
    """A misconfigured deployment must stay loudly broken.

    Quota is temporary; a rejected key is a fault someone has to fix. Hiding
    it behind a working-looking answer would keep it hidden.
    """
    patch_post(monkeypatch, [FakeResponse(401, {}, "bad key")])
    response = client.post(
        "/api/assistant/chat",
        json={"message": "What is automation bias?"},
        headers=student_headers,
    )
    assert response.status_code == 503
    assert "administrator" in response.json()["detail"].lower()
    assert "bad key" not in response.json()["detail"]


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
    """Same `TestClient`-vs-`httpx.Client` split as `patch_post`, for `.stream()`."""
    real_stream = httpx.Client.stream

    def fake_stream(self, method, url, *args, **kwargs):  # noqa: A002
        if type(self) is not httpx.Client:
            return real_stream(self, method, url, *args, **kwargs)
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


def test_stream_429_falls_back_before_the_first_chunk(
    client: TestClient, student_headers: dict, gemini_on, monkeypatch
) -> None:
    """The stream degrades to a complete offline answer, not an error frame."""
    patch_stream(monkeypatch, FakeStream(429, [], "quota"))

    with client.stream(
        "POST",
        "/api/assistant/chat/stream",
        json={"message": "What is automation bias?"},
        headers=student_headers,
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert "event: error" not in body
    assert "event: chunk" in body
    assert "event: done" in body
    assert "offline" in body

    # persisted under the honest provider name
    session_id = json.loads(
        body.split("event: start\ndata: ")[1].split("\n")[0]
    )["session_id"]
    history = client.get(
        f"/api/assistant/history/{session_id}", headers=student_headers
    ).json()
    answers = [row for row in history if row["role"] == "assistant"]
    assert len(answers) == 1
    assert answers[0]["content"].strip()


def test_stream_failure_after_first_chunk_still_errors(
    client: TestClient, student_headers: dict, gemini_on, monkeypatch
) -> None:
    """Never splice two answers together.

    Once fragments have reached the client, a provider swap would join half a
    Gemini answer to a whole rules answer. A partial answer that stops
    honestly is better than a seamless one that is two answers.
    """

    class HalfwayStream(FakeStream):
        def iter_lines(self):
            yield sse("Automation bias is ")
            raise gemini.GeminiRateLimited("quota mid-stream")

    patch_stream(monkeypatch, HalfwayStream(200, []))

    with client.stream(
        "POST",
        "/api/assistant/chat/stream",
        json={"message": "What is automation bias?"},
        headers=student_headers,
    ) as response:
        body = "".join(response.iter_text())

    assert "event: error" in body
    assert '"partial": true' in body.lower()
