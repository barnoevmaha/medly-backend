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

import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional

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


@dataclass(frozen=True)
class Credentials:
    """Which key, model and timeout a call should use.

    Defaults to the assistant's. Virtual Patient passes its own, so the two
    features can sit on separate keys and quotas without a second HTTP client
    or a second copy of the error handling.
    """

    api_key: str
    model: str
    timeout_seconds: float
    base_url: str


def assistant_credentials() -> Credentials:
    return Credentials(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        timeout_seconds=settings.gemini_timeout_seconds,
        base_url=settings.gemini_base_url,
    )


def virtual_patient_credentials() -> Credentials:
    # Falling back to the assistant key keeps one-project deployments working
    # with a single secret; set the VP key to split them.
    return Credentials(
        api_key=settings.vp_gemini_api_key or settings.gemini_api_key,
        model=settings.vp_gemini_model,
        timeout_seconds=settings.vp_gemini_timeout_seconds,
        base_url=settings.gemini_base_url,
    )


def _build_request(
    system_prompt: str,
    history: List[Dict[str, str]],
    message: str,
    max_output_tokens: Optional[int],
    temperature: float,
) -> tuple[dict, dict]:
    """The body and headers both the blocking and streaming calls share."""
    contents = [
        {
            "role": "model" if turn.get("role") == "assistant" else "user",
            "parts": [{"text": turn.get("content", "")}],
        }
        for turn in history
        if turn.get("content")
    ]
    contents.append({"role": "user", "parts": [{"text": message}]})

    generation_config: dict = {
        "temperature": temperature,
        "maxOutputTokens": max_output_tokens or settings.ai_max_output_tokens,
    }
    if settings.gemini_thinking_level:
        # Gemini 3 uses thinkingLevel (thinkingBudget is the 2.x spelling).
        generation_config["thinkingConfig"] = {
            "thinkingLevel": settings.gemini_thinking_level
        }

    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": generation_config,
    }
    headers = {"x-goog-api-key": settings.gemini_api_key, "Content-Type": "application/json"}
    return body, headers


def generate_stream(
    *,
    system_prompt: str,
    history: List[Dict[str, str]],
    message: str,
    max_output_tokens: Optional[int] = None,
    temperature: float = 0.4,
) -> Iterator[str]:
    """Yield text fragments as Gemini produces them.

    Uses `:streamGenerateContent?alt=sse`, so a fragment is forwarded the moment
    Google emits it — nothing here waits for the full answer, and nothing here
    paces the output artificially.

    Deliberately not retried. A retry would mean replaying text the user has
    already watched appear, so the first failure ends the stream and the caller
    decides what to do with whatever arrived. Failures *before* the first byte
    still raise the same classified exceptions as `generate()`.
    """
    if not settings.gemini_api_key:
        raise GeminiNotConfigured("GEMINI_API_KEY is not set")

    model = settings.gemini_model
    body, headers = _build_request(
        system_prompt, history, message, max_output_tokens, temperature
    )
    url = f"{settings.gemini_base_url}/models/{model}:streamGenerateContent?alt=sse"

    started = time.monotonic()
    produced = 0
    fragments = 0
    first_at: Optional[float] = None
    last_at: Optional[float] = None
    gaps: List[float] = []

    def mark(stage: str, extra: str = "") -> None:
        """Millisecond-stamped stage marker, only when debugging is on."""
        if settings.stream_debug:
            logger.info(
                "[GEMINI] %s t=%.3fs %s", stage, time.monotonic() - started, extra
            )

    logger.info(
        "gemini stream start model=%s turns=%d thinking=%s",
        model, len(body["contents"]), settings.gemini_thinking_level or "default",
    )
    mark("request sent")

    with httpx.Client(timeout=settings.gemini_timeout_seconds) as client:
        with client.stream("POST", url, json=body, headers=headers) as response:
            if response.status_code >= 400:
                response.read()
                _raise_for_status(response.status_code, response.text)

            mark("upstream headers", f"status={response.status_code}")
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload_text = line[5:].strip()
                if not payload_text or payload_text == "[DONE]":
                    continue
                try:
                    payload = json.loads(payload_text)
                except ValueError:
                    # A malformed frame is skipped rather than killing a stream
                    # the user is already reading.
                    logger.warning("gemini stream: unparseable frame, skipped")
                    continue

                blocked = (payload.get("promptFeedback") or {}).get("blockReason")
                if blocked and not produced:
                    raise GeminiBadResponse(
                        f"gemini blocked the prompt: {blocked}",
                        user_message=(
                            "Medly AI could not answer that. Try rewording it as an "
                            "educational question."
                        ),
                    )

                for candidate in payload.get("candidates") or []:
                    parts = ((candidate.get("content") or {}).get("parts")) or []
                    for part in parts:
                        text = part.get("text")
                        if text:
                            now = time.monotonic()
                            produced += len(text)
                            fragments += 1
                            if first_at is None:
                                first_at = now
                                mark(
                                    "FIRST chunk received",
                                    f"chars={len(text)} (time to first token)",
                                )
                            else:
                                gap = now - (last_at or now)
                                gaps.append(gap)
                                mark(
                                    "chunk received",
                                    f"n={fragments} chars={len(text)} "
                                    f"gap={gap * 1000:.0f}ms total={produced}",
                                )
                            last_at = now
                            yield text

    latency_ms = int((time.monotonic() - started) * 1000)

    # One line that answers "did Gemini stream, or did it batch?" without
    # anyone having to read a wall of per-chunk lines.
    ttft = (first_at - started) if first_at else 0.0
    span = (last_at - first_at) if (first_at and last_at) else 0.0
    median_gap = sorted(gaps)[len(gaps) // 2] if gaps else 0.0
    if fragments <= 1:
        verdict = "GEMINI BATCHED - a single chunk carried the whole answer"
    elif span < 0.5:
        verdict = f"GEMINI BATCHED - {fragments} chunks all within {span * 1000:.0f}ms"
    else:
        verdict = (
            f"GEMINI STREAMED - {fragments} chunks over {span:.1f}s; "
            "any remaining delay is downstream of this process"
        )
    logger.info(
        "[GEMINI] SUMMARY model=%s ttft=%.2fs chunks=%d span=%.2fs "
        "median_gap=%.0fms chars=%d thinking=%s -> %s",
        model, ttft, fragments, span, median_gap * 1000, produced,
        settings.gemini_thinking_level or "default", verdict,
    )
    if not produced:
        raise GeminiBadResponse("gemini stream produced no text")


def generate(
    *,
    system_prompt: str,
    history: List[Dict[str, str]],
    message: str,
    max_output_tokens: Optional[int] = None,
    temperature: float = 0.4,
    credentials: Optional[Credentials] = None,
) -> GeminiResult:
    """One turn against Gemini. Raises a `GeminiError` subclass on any failure.

    `history` is a list of `{"role": "user"|"assistant", "content": ...}` in
    chronological order; it is converted to Gemini's `user`/`model` roles here
    so callers do not have to know the wire format.
    """
    creds = credentials or assistant_credentials()
    if not creds.api_key:
        raise GeminiNotConfigured("No Gemini API key is configured for this feature")

    model = creds.model
    contents = [
        {
            "role": "model" if turn.get("role") == "assistant" else "user",
            "parts": [{"text": turn.get("content", "")}],
        }
        for turn in history
        if turn.get("content")
    ]
    contents.append({"role": "user", "parts": [{"text": message}]})

    generation_config: dict = {
        "temperature": temperature,
        "maxOutputTokens": max_output_tokens or settings.ai_max_output_tokens,
    }
    if settings.gemini_thinking_level:
        # Gemini 3 uses thinkingLevel (thinkingBudget is the 2.x spelling).
        generation_config["thinkingConfig"] = {
            "thinkingLevel": settings.gemini_thinking_level
        }

    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": generation_config,
    }
    url = f"{creds.base_url}/models/{model}:generateContent"
    headers = {"x-goog-api-key": creds.api_key, "Content-Type": "application/json"}

    started = time.monotonic()
    last_error: Optional[GeminiError] = None

    for attempt in range(MAX_ATTEMPTS):
        try:
            logger.info(
                "gemini request start model=%s attempt=%d turns=%d",
                model, attempt + 1, len(contents),
            )
            with httpx.Client(timeout=creds.timeout_seconds) as client:
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
