"""Google Gemini client.

Talks to the documented REST surface with `httpx`, which the project already
depends on, rather than adding an SDK. The payload shape is small and stable,
the failure modes are the ones below, and keeping it dependency-free means the
default `rules` provider still installs and boots with nothing extra — the same
bargain the Anthropic and OpenAI providers already make.

Everything Google can return that is not a clean answer is mapped to one of the
exceptions here, so the router never has to reason about HTTP status codes and
the user never sees a raw provider error.

    Frontend -> /api/assistant/chat -> this module -> Google

The API key is read from the environment in this process only.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger("medly.gemini")

# 429 and 5xx are worth another go; 400/401/403/404 will fail identically
# forever, so retrying them just burns quota and delays the error.
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
BASE_BACKOFF_SECONDS = 1.0


class GeminiError(Exception):
    """Base class. `user_message` is the only part safe to show a user."""

    user_message = "Medly AI could not answer that just now. Please try again."

    def __init__(self, detail: str, user_message: Optional[str] = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if user_message:
            self.user_message = user_message


class GeminiNotConfigured(GeminiError):
    user_message = "Medly AI is not configured on this server yet."


class GeminiAuthError(GeminiError):
    user_message = "Medly AI is not configured correctly. An administrator has been notified."


class GeminiModelNotFound(GeminiError):
    user_message = "Medly AI is not configured correctly. An administrator has been notified."


class GeminiRateLimited(GeminiError):
    user_message = "Medly AI is temporarily busy. Please try again in a moment."


class GeminiUnavailable(GeminiError):
    user_message = "Medly AI is temporarily unavailable. Please try again in a moment."


class GeminiBadResponse(GeminiError):
    user_message = "Medly AI returned an unusable answer. Try rephrasing your question."


@dataclass
class GeminiResult:
    text: str
    model: str
    latency_ms: int
    finish_reason: str = ""


def _sleep_for(attempt: int, retry_after: Optional[str]) -> float:
    """1s, 2s, 4s with jitter — or whatever Google asked for, if it asked."""
    if retry_after:
        try:
            return min(float(retry_after), 10.0)
        except ValueError:
            pass
    return BASE_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, 0.4)


def _raise_for_status(status: int, body: str) -> None:
    # `body` goes to the log, never to the caller — it can echo request content.
    if status in (401, 403):
        raise GeminiAuthError(f"gemini auth rejected ({status}): {body[:300]}")
    if status == 404:
        raise GeminiModelNotFound(
            f"gemini model '{settings.gemini_model}' not found: {body[:300]}"
        )
    if status == 429:
        raise GeminiRateLimited(f"gemini rate limited: {body[:300]}")
    if status >= 500:
        raise GeminiUnavailable(f"gemini {status}: {body[:300]}")
    if status >= 400:
        raise GeminiError(f"gemini rejected the request ({status}): {body[:300]}")


def _extract_text(payload: dict) -> tuple[str, str]:
    """Pull the answer out of a generateContent response.

    A response with no candidates is normal when a safety filter fired, so it
    is a handled case rather than a crash.
    """
    candidates = payload.get("candidates") or []
    if not candidates:
        blocked = (payload.get("promptFeedback") or {}).get("blockReason")
        if blocked:
            raise GeminiBadResponse(
                f"gemini blocked the prompt: {blocked}",
                user_message=(
                    "Medly AI could not answer that. Try rewording it as an "
                    "educational question."
                ),
            )
        raise GeminiBadResponse("gemini returned no candidates")

    candidate = candidates[0]
    finish = str(candidate.get("finishReason") or "")
    parts = ((candidate.get("content") or {}).get("parts")) or []
    text = "".join(part.get("text", "") for part in parts).strip()

    if not text:
        if finish == "MAX_TOKENS":
            raise GeminiBadResponse(
                "gemini hit the output cap before producing text",
                user_message="That answer was too long to finish. Try a narrower question.",
            )
        raise GeminiBadResponse(f"gemini returned an empty answer (finish={finish})")
    return text, finish


def generate(
    *,
    system_prompt: str,
    history: List[Dict[str, str]],
    message: str,
    max_output_tokens: Optional[int] = None,
    temperature: float = 0.4,
) -> GeminiResult:
    """One turn against Gemini. Raises a `GeminiError` subclass on any failure.

    `history` is a list of `{"role": "user"|"assistant", "content": ...}` in
    chronological order; it is converted to Gemini's `user`/`model` roles here
    so callers do not have to know the wire format.
    """
    if not settings.gemini_api_key:
        raise GeminiNotConfigured("GEMINI_API_KEY is not set")

    model = settings.gemini_model
    contents = [
        {
            "role": "model" if turn.get("role") == "assistant" else "user",
            "parts": [{"text": turn.get("content", "")}],
        }
        for turn in history
        if turn.get("content")
    ]
    contents.append({"role": "user", "parts": [{"text": message}]})

    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens or settings.ai_max_output_tokens,
        },
    }
    url = f"{settings.gemini_base_url}/models/{model}:generateContent"
    headers = {"x-goog-api-key": settings.gemini_api_key, "Content-Type": "application/json"}

    started = time.monotonic()
    last_error: Optional[GeminiError] = None

    for attempt in range(MAX_ATTEMPTS):
        try:
            logger.info(
                "gemini request start model=%s attempt=%d turns=%d",
                model, attempt + 1, len(contents),
            )
            with httpx.Client(timeout=settings.gemini_timeout_seconds) as client:
                response = client.post(url, json=body, headers=headers)

            if response.status_code in RETRY_STATUS and attempt < MAX_ATTEMPTS - 1:
                delay = _sleep_for(attempt, response.headers.get("retry-after"))
                logger.warning(
                    "gemini transient %s, retrying in %.1fs (attempt %d/%d)",
                    response.status_code, delay, attempt + 1, MAX_ATTEMPTS,
                )
                time.sleep(delay)
                continue

            _raise_for_status(response.status_code, response.text)

            try:
                payload = response.json()
            except ValueError as exc:
                raise GeminiBadResponse(f"gemini returned non-JSON: {exc}") from exc

            text, finish = _extract_text(payload)
            latency_ms = int((time.monotonic() - started) * 1000)
            logger.info(
                "gemini request ok model=%s status=200 latency_ms=%d chars=%d finish=%s",
                model, latency_ms, len(text), finish or "STOP",
            )
            return GeminiResult(
                text=text, model=model, latency_ms=latency_ms, finish_reason=finish
            )

        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = GeminiUnavailable(f"gemini network error: {exc}")
            if attempt < MAX_ATTEMPTS - 1:
                delay = _sleep_for(attempt, None)
                logger.warning("gemini network error, retrying in %.1fs: %s", delay, exc)
                time.sleep(delay)
                continue
            break
        except GeminiError as exc:
            # Already classified. Non-retryable ones propagate immediately;
            # retryable ones only reach here on the final attempt.
            last_error = exc
            break

    latency_ms = int((time.monotonic() - started) * 1000)
    error = last_error or GeminiUnavailable("gemini exhausted retries")
    logger.error(
        "gemini request failed model=%s latency_ms=%d error=%s",
        model, latency_ms, error.detail,
    )
    raise error
