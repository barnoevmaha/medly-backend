"""The fixed-corner study assistant.

Every request follows the same path, with no bypass:

    screen -> (refuse and log) or (answer -> disclaimer -> log)
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, select

from app.config import settings
from app.db import engine, get_session
from app.lang import get_lang
from app.models.assistant import AssistantMessage
from app.models.enums import EventType, RiskLevel
from app.models.challenge import Challenge
from app.models.social import Article, Resource
from app.models.user import User
from app.security import get_current_user
from app.services import ratelimit, safety, scope
from app.services.assistant import RuleBasedProvider, get_provider, suggested_prompts
from app.services.audit import log_event
from app.services.gemini import (
    GeminiError,
    GeminiRateLimited,
    GeminiUnavailable,
)

logger = logging.getLogger("medly.assistant")

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

HISTORY_TURNS = settings.ai_history_turns

# Shown when the paid provider was out of capacity and the offline engine
# answered instead. It names the degradation rather than hiding it: a student
# who gets a narrower answer than usual should know why, and an assessor
# reading the audit trail should see that the row says "rules", not "gemini".
def _chunk_for_stream(text: str, size: int = 24) -> List[str]:
    """Break a complete answer into SSE-sized pieces.

    The offline engine returns its answer whole, but the client is a streaming
    client: handing it one enormous chunk would render as a paragraph
    appearing instantly, which reads as a different feature rather than a
    degraded one. Splitting on whitespace keeps words intact.
    """
    words = text.split(" ")
    return [
        " ".join(words[i:i + size]) + (" " if i + size < len(words) else "")
        for i in range(0, len(words), size)
    ] or [text]


FALLBACK_NOTICE = (
    "Medly AI is busy right now, so this answer came from the offline "
    "safety engine. The same screening and disclaimer rules apply."
)

# Process-wide. Both are per user, and both exist because the AI path is the
# only endpoint here that costs money per call.
_limiter, _in_flight = ratelimit.build(
    settings.ai_rate_limit_per_minute, settings.ai_rate_limit_per_hour
)

# Follow-ups the UI offers under an answer. Kept server-side so the wording
# stays consistent with the system prompt rather than drifting in the client.
QUICK_ACTIONS = {
    "simpler": "Explain that again more simply, as if I am earlier in my training.",
    "deeper": "Go deeper on that — more mechanism and more clinical detail.",
    "example": "Give me a concrete clinical example of that.",
    "mcq": "Write 5 exam-style MCQs on that topic, with answers and brief explanations.",
    "case": "Give me a clinical case based on that topic, with guiding questions.",
    "summary": "Summarise that in a short set of key points I can revise from.",
    "quiz": "Quiz me on that topic. Ask one question at a time and wait for my answer.",
}


def _record_refusal(
    session: Session,
    *,
    session_id: str,
    user_id: int,
    reason: str,
    lang: str = "en",
) -> Optional[int]:
    """Persist an out-of-scope refusal and audit it. No provider is called.

    Stored in the language the student was shown, so their transcript reads
    back the way they experienced it. `ai_output_summary` stays English: the
    audit log is read by staff across locales and must stay comparable.
    """
    session.add(
        AssistantMessage(
            session_id=session_id,
            user_id=user_id,
            role="assistant",
            content=scope.refusal_for(lang),
            risk_level=RiskLevel.NONE,
            blocked=True,
            block_reason=f"out of scope: {reason}",
            provider="scope-guard",
        )
    )
    session.commit()
    event = log_event(
        session,
        user_id=user_id,
        event_type=EventType.ASSISTANT_BLOCKED,
        risk_level=RiskLevel.NONE,
        ai_model="scope-guard",
        ai_version="1.0",
        ai_output_summary=scope.REFUSAL,
        blocked=True,
        block_reason=f"out of scope: {reason}",
        session_id=session_id,
        meta={"scope_reason": reason},
    )
    return event.id


def _page_context(
    session: Session, kind: Optional[str], key: Optional[str], note: Optional[str]
) -> Optional[str]:
    """What the user is looking at, resolved from our own database.

    The client sends a kind and a slug, never content. Whatever the model is
    told about an article or a challenge therefore comes from the same rows the
    page rendered, trimmed to a budget — a client cannot enlarge the prompt or
    put words in the source material.

    `note` is the exception: on-screen state the server has no cheap way to
    know, such as which question is showing. It is capped hard.
    """
    parts: List[str] = []

    if kind == "article" and key:
        article = session.exec(select(Article).where(Article.slug == key)).first()
        if article:
            body = (article.body_md or article.excerpt or "")[
                : settings.ai_article_context_chars
            ]
            parts.append(
                "CONTEXT — the user is reading this Medly article, so their question "
                "is probably about it. Treat it as the primary source and say so when "
                "you add knowledge from outside it.\n\n"
                f"Article: {article.title}\n\n{body}"
            )

    elif kind == "resource" and key:
        resource = session.exec(select(Resource).where(Resource.slug == key)).first()
        if resource:
            parts.append(
                "CONTEXT — the user is studying this item from the Medly library. "
                "You have its description, not its full text; do not pretend to have "
                "read or watched it.\n\n"
                f"Title: {resource.title}\n"
                f"Author: {resource.author}\n"
                f"Topic: {resource.topic}\n\n{resource.description}"
            )

    elif kind == "challenge" and key:
        challenge = session.exec(select(Challenge).where(Challenge.slug == key)).first()
        if challenge:
            parts.append(
                "CONTEXT — the user is working through this Medly challenge. Teach the "
                "reasoning behind the question. Do not simply reveal an answer they have "
                "not attempted yet.\n\n"
                f"Challenge: {challenge.title}\n"
                f"Difficulty: {challenge.difficulty}\n\n{challenge.description}"
            )

    if note:
        parts.append(f"ON SCREEN NOW:\n{note[: settings.ai_note_context_chars]}")

    return "\n\n".join(parts) if parts else None


def _trim_history(rows: List[AssistantMessage], skip_content: str) -> List[dict]:
    """Newest-first rows to oldest-first turns, inside a character budget."""
    turns: List[dict] = []
    budget = settings.ai_max_context_chars
    for row in rows:
        if row.content == skip_content:
            continue
        if budget - len(row.content) < 0:
            break
        budget -= len(row.content)
        turns.append({"role": row.role, "content": row.content})
    return list(reversed(turns))


class ChatRequest(BaseModel):
    message: str = PydanticField(default="", max_length=8000)
    session_id: Optional[str] = None
    # Optional page grounding. The server resolves kind+key from its own rows.
    context_kind: Optional[str] = None
    context_key: Optional[str] = None
    context_note: Optional[str] = PydanticField(default=None, max_length=4000)
    # Legacy alias, still accepted so older clients keep working.
    article_slug: Optional[str] = None
    # Optional: one of QUICK_ACTIONS, used instead of a typed message.
    action: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    blocked: bool
    block_reason: Optional[str] = None
    risk_level: RiskLevel
    disclaimer: str
    provider: str
    audit_event_id: Optional[int] = None
    model: Optional[str] = None
    # Set only when the paid provider was unreachable and the offline rules
    # engine answered instead. The client shows it as a small line under the
    # answer; older clients ignore an unknown field, so this is additive.
    notice: Optional[str] = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    blocked: bool
    risk_level: RiskLevel
    created_at: datetime


@router.get("/suggestions", response_model=List[str])
def suggestions() -> List[str]:
    return suggested_prompts()


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    response: Response,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> ChatResponse:
    session_id = payload.session_id or str(uuid.uuid4())

    text = (QUICK_ACTIONS.get(payload.action) if payload.action else payload.message) or ""
    text = text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Type a question first.")
    if len(text) > settings.ai_max_message_chars:
        raise HTTPException(
            status_code=422,
            detail=(
                f"That message is too long. Keep it under "
                f"{settings.ai_max_message_chars:,} characters."
            ),
        )

    verdict = safety.screen_message(text)

    # The stored copy is always redacted, even when the message is allowed.
    session.add(
        AssistantMessage(
            session_id=session_id,
            user_id=user.id or 0,
            role="user",
            content=verdict.redacted_text,
            risk_level=verdict.risk_level,
            blocked=verdict.blocked,
            block_reason="; ".join(verdict.reasons) or None,
        )
    )
    session.commit()

    # ---- refused ----------------------------------------------------------
    if verdict.blocked:
        reply_text = verdict.refusal_message or "I cannot help with that request."
        session.add(
            AssistantMessage(
                session_id=session_id,
                user_id=user.id or 0,
                role="assistant",
                content=reply_text,
                risk_level=verdict.risk_level,
                blocked=True,
                block_reason="; ".join(verdict.reasons) or None,
                provider="guardrail",
            )
        )
        session.commit()

        event = log_event(
            session,
            user_id=user.id,
            event_type=EventType.ASSISTANT_BLOCKED,
            risk_level=verdict.risk_level,
            ai_model="guardrail",
            ai_version="1.0",
            ai_output_summary=reply_text,
            blocked=True,
            block_reason="; ".join(verdict.reasons),
            requires_review=verdict.risk_level == RiskLevel.HIGH,
            session_id=session_id,
            meta={"reasons": verdict.reasons},
        )
        return ChatResponse(
            session_id=session_id,
            reply=reply_text,
            blocked=True,
            block_reason="; ".join(verdict.reasons),
            risk_level=verdict.risk_level,
            disclaimer=settings.disclaimer,
            provider="guardrail",
            audit_event_id=event.id,
        )

    # ---- answered ---------------------------------------------------------
    history_rows = session.exec(
        select(AssistantMessage)
        .where(AssistantMessage.session_id == session_id, AssistantMessage.blocked == False)  # noqa: E712
        .order_by(AssistantMessage.created_at.desc())  # type: ignore[union-attr]
        .limit(HISTORY_TURNS * 2)
    ).all()
    history = _trim_history(list(history_rows), verdict.redacted_text)

    ctx_kind = payload.context_kind or ("article" if payload.article_slug else None)
    ctx_key = payload.context_key or payload.article_slug
    context = _page_context(session, ctx_kind, ctx_key, payload.context_note)

    # ---- topic boundary ---------------------------------------------------
    # Before the provider and before the rate window: an off-topic question
    # costs nothing and is answered from this process.
    in_scope = scope.classify(
        text,
        has_page_context=bool(context),
        has_history=bool(history),
        is_quick_action=bool(payload.action),
    )
    if not in_scope.in_scope:
        logger.info(
            "assistant refused out of scope user=%s reason=%s", user.id, in_scope.reason
        )
        event_id = _record_refusal(
            session,
            session_id=session_id,
            user_id=user.id or 0,
            reason=in_scope.reason,
            lang=lang,
        )
        return ChatResponse(
            session_id=session_id,
            reply=scope.refusal_for(lang),
            blocked=True,
            block_reason="out of scope",
            risk_level=RiskLevel.NONE,
            disclaimer=settings.disclaimer,
            provider="scope-guard",
            audit_event_id=event_id,
        )

    # Two ceilings before the paid call: one request at a time per user, and a
    # sliding window on top of it.
    key = str(user.id)
    if not _in_flight.acquire(key):
        raise HTTPException(
            status_code=429,
            detail="Medly AI is still working on your last question. Give it a moment.",
        )
    try:
        verdict_rate = _limiter.check(key)
        if not verdict_rate.allowed:
            response.headers["Retry-After"] = str(verdict_rate.retry_after_seconds)
            raise HTTPException(
                status_code=429,
                detail=(
                    "You have reached the Medly AI limit for now. "
                    f"Try again in {verdict_rate.retry_after_seconds} seconds."
                ),
            )

        provider = get_provider()
        started = time.monotonic()
        notice: Optional[str] = None
        try:
            result = provider.reply(verdict.redacted_text, history, context, lang)
        except GeminiError as exc:
            # The detail goes to the log; only `user_message` reaches the client.
            logger.error(
                "assistant provider failed user=%s provider=%s error=%s",
                user.id, settings.assistant_provider, exc.detail,
            )
            # Being out of quota is not a reason to show a student an error.
            # Rate limiting and provider outage are temporary and say nothing
            # about the question, so the offline engine answers instead.
            # Nothing that makes an answer safe is skipped: the message was
            # screened and redacted before this point, and the disclaimer is
            # applied below on the same path as any other answer.
            #
            # Configuration failures are deliberately not caught here. A wrong
            # key, a missing model or an unconfigured provider is a deployment
            # fault, and degrading it silently would hide that fault for as
            # long as nobody reads a log.
            if isinstance(exc, (GeminiRateLimited, GeminiUnavailable)):
                logger.warning(
                    "assistant falling back to rules user=%s reason=%s",
                    user.id, type(exc).__name__,
                )
                result = RuleBasedProvider().reply(
                    verdict.redacted_text, history, context, lang
                )
                result.provider = f"{result.provider} (fallback)"
                notice = FALLBACK_NOTICE
            else:
                raise HTTPException(
                    status_code=503, detail=exc.user_message
                ) from exc
        except Exception as exc:  # noqa: BLE001 - never leak a provider traceback
            logger.exception("assistant provider crashed user=%s", user.id)
            raise HTTPException(
                status_code=503,
                detail="Medly AI is temporarily unavailable. Please try again in a moment.",
            ) from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "assistant reply user=%s provider=%s latency_ms=%d chars=%d context=%s",
            user.id, result.provider, latency_ms, len(result.content),
            f"{ctx_kind or '-'}:{ctx_key or '-'}",
        )
    finally:
        _in_flight.release(key)

    answer = safety.apply_disclaimer(result.content, verdict.risk_level, lang)

    session.add(
        AssistantMessage(
            session_id=session_id,
            user_id=user.id or 0,
            role="assistant",
            content=answer,
            risk_level=verdict.risk_level,
            provider=result.provider,
        )
    )
    session.commit()

    event = log_event(
        session,
        user_id=user.id,
        event_type=EventType.ASSISTANT_QUERY,
        risk_level=verdict.risk_level,
        ai_model=result.provider,
        ai_version="1.0",
        ai_output_summary=result.content,
        disclaimer_shown=True,
        session_id=session_id,
        meta={"question": verdict.redacted_text[:200]},
    )

    return ChatResponse(
        session_id=session_id,
        reply=answer,
        blocked=False,
        risk_level=verdict.risk_level,
        disclaimer=settings.disclaimer,
        provider=result.provider,
        audit_event_id=event.id,
        model=settings.gemini_model if result.provider.startswith("gemini") else None,
        notice=notice,
    )


@router.delete("/history", status_code=204)
def clear_history(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    """Delete this user's assistant conversation history.

    The audit trail is deliberately untouched. Conversation history is the
    user's; the audit log is the institution's record that an AI interaction
    happened, and a product that let people erase that would not be auditable.
    """
    rows = session.exec(
        select(AssistantMessage).where(AssistantMessage.user_id == user.id)
    ).all()
    for row in rows:
        session.delete(row)
    session.commit()


@router.get("/history/{session_id}", response_model=List[MessageOut])
def history(
    session_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> List[MessageOut]:
    rows = session.exec(
        select(AssistantMessage)
        .where(
            AssistantMessage.session_id == session_id,
            AssistantMessage.user_id == user.id,
        )
        .order_by(AssistantMessage.created_at)  # type: ignore[arg-type]
    ).all()
    return [
        MessageOut(
            id=row.id or 0,
            role=row.role,
            content=row.content,
            blocked=row.blocked,
            risk_level=row.risk_level,
            created_at=row.created_at,
        )
        for row in rows
    ]


# ==========================================================================
# Streaming
# ==========================================================================


def _sse(event: str, data: dict) -> str:
    """One Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _persist_answer(
    *,
    session_id: str,
    user_id: int,
    risk_level: RiskLevel,
    question: str,
    text: str,
    provider: str,
    interrupted: bool,
    lang: str = "en",
) -> None:
    """Save the finished answer as ONE row and write the audit entry.

    Called once, after the stream ends — never per chunk. A stopped or failed
    generation still saves what was produced, so the conversation the model
    sees next turn matches the conversation the user is looking at.

    Opens its own session on purpose. FastAPI closes `yield` dependencies
    before a StreamingResponse body is sent, so by the time this runs the
    request-scoped session is gone and its ORM objects are detached — which is
    also why this takes plain ints and strings rather than a `User` row.
    """
    session = Session(engine)
    answer = safety.apply_disclaimer(text, risk_level, lang)
    session.add(
        AssistantMessage(
            session_id=session_id,
            user_id=user_id,
            role="assistant",
            content=answer,
            risk_level=risk_level,
            provider=provider,
        )
    )
    session.commit()

    log_event(
        session,
        user_id=user_id,
        event_type=EventType.ASSISTANT_QUERY,
        risk_level=risk_level,
        ai_model=provider,
        ai_version="1.0",
        ai_output_summary=text,
        disclaimer_shown=True,
        session_id=session_id,
        meta={"question": question[:200], "streamed": True, "interrupted": interrupted},
    )
    session.close()


@router.post("/chat/stream")
def chat_stream(
    payload: ChatRequest,
    response: Response,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
):
    """Server-Sent Events: the same answer, forwarded as Gemini writes it.

    Every guard from `/chat` runs here first and none of them can be skipped by
    choosing this endpoint — length cap, safety screen, in-flight lock and the
    per-user rate window are all applied before a single byte is streamed, so
    they can still be reported as real HTTP status codes.

    Frames:
        event: start   {"session_id": ...}
        event: chunk   {"text": "..."}          (many)
        event: done    {"disclaimer": ..., "risk_level": ..., "interrupted": ...}
        event: error   {"detail": "...", "partial": true|false}
    """
    session_id = payload.session_id or str(uuid.uuid4())

    text = (QUICK_ACTIONS.get(payload.action) if payload.action else payload.message) or ""
    text = text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Type a question first.")
    if len(text) > settings.ai_max_message_chars:
        raise HTTPException(
            status_code=422,
            detail=(
                f"That message is too long. Keep it under "
                f"{settings.ai_max_message_chars:,} characters."
            ),
        )

    verdict = safety.screen_message(text)

    session.add(
        AssistantMessage(
            session_id=session_id,
            user_id=user.id or 0,
            role="user",
            content=verdict.redacted_text,
            risk_level=verdict.risk_level,
            blocked=verdict.blocked,
            block_reason="; ".join(verdict.reasons) or None,
        )
    )
    session.commit()

    # ---- refused: still a valid stream, just a very short one ---------------
    if verdict.blocked:
        reply_text = verdict.refusal_message or "I cannot help with that request."
        session.add(
            AssistantMessage(
                session_id=session_id,
                user_id=user.id or 0,
                role="assistant",
                content=reply_text,
                risk_level=verdict.risk_level,
                blocked=True,
                block_reason="; ".join(verdict.reasons) or None,
                provider="guardrail",
            )
        )
        session.commit()
        log_event(
            session,
            user_id=user.id,
            event_type=EventType.ASSISTANT_BLOCKED,
            risk_level=verdict.risk_level,
            ai_model="guardrail",
            ai_version="1.0",
            ai_output_summary=reply_text,
            blocked=True,
            block_reason="; ".join(verdict.reasons),
            requires_review=verdict.risk_level == RiskLevel.HIGH,
            session_id=session_id,
            meta={"reasons": verdict.reasons},
        )

        def refusal():
            yield _sse("start", {"session_id": session_id})
            yield _sse("chunk", {"text": reply_text})
            yield _sse(
                "done",
                {
                    "session_id": session_id,
                    "blocked": True,
                    "block_reason": "; ".join(verdict.reasons),
                    "risk_level": verdict.risk_level.value,
                    "disclaimer": settings.disclaimer,
                    "interrupted": False,
                },
            )

        return StreamingResponse(refusal(), media_type="text/event-stream")

    provider = get_provider()
    if not hasattr(provider, "stream"):
        raise HTTPException(
            status_code=501,
            detail="Streaming is not available with the current assistant provider.",
        )

    history_rows = session.exec(
        select(AssistantMessage)
        .where(AssistantMessage.session_id == session_id, AssistantMessage.blocked == False)  # noqa: E712
        .order_by(AssistantMessage.created_at.desc())  # type: ignore[union-attr]
        .limit(HISTORY_TURNS * 2)
    ).all()
    history = _trim_history(list(history_rows), verdict.redacted_text)

    kind = payload.context_kind or ("article" if payload.article_slug else None)
    key = payload.context_key or payload.article_slug
    context = _page_context(session, kind, key, payload.context_note)

    # ---- topic boundary ---------------------------------------------------
    # No Gemini stream is opened for an off-topic question. The refusal is a
    # complete, valid SSE exchange so the client needs no special case.
    in_scope = scope.classify(
        text,
        has_page_context=bool(context),
        has_history=bool(history),
        is_quick_action=bool(payload.action),
    )
    if not in_scope.in_scope:
        logger.info(
            "assistant refused out of scope (stream) user=%s reason=%s",
            user.id, in_scope.reason,
        )
        _record_refusal(
            session,
            session_id=session_id,
            user_id=user.id or 0,
            reason=in_scope.reason,
            lang=lang,
        )

        def out_of_scope():
            yield _sse("start", {"session_id": session_id})
            yield _sse("chunk", {"text": scope.refusal_for(lang)})
            yield _sse(
                "done",
                {
                    "session_id": session_id,
                    "blocked": True,
                    "block_reason": "out of scope",
                    "risk_level": RiskLevel.NONE.value,
                    "disclaimer": settings.disclaimer,
                    "interrupted": False,
                },
            )

        return StreamingResponse(out_of_scope(), media_type="text/event-stream")

    # Same two ceilings as the blocking endpoint, applied before streaming so
    # they can be reported as a real status code rather than buried in a frame.
    limit_key = str(user.id)
    if not _in_flight.acquire(limit_key):
        raise HTTPException(
            status_code=429,
            detail="Medly AI is still working on your last question. Give it a moment.",
        )
    rate = _limiter.check(limit_key)
    if not rate.allowed:
        _in_flight.release(limit_key)
        response.headers["Retry-After"] = str(rate.retry_after_seconds)
        raise HTTPException(
            status_code=429,
            detail=(
                "You have reached the Medly AI limit for now. "
                f"Try again in {rate.retry_after_seconds} seconds."
            ),
        )

    # Everything the generator needs, captured as plain values while the
    # request-scoped session is still alive.
    user_id = user.id or 0
    risk_level = verdict.risk_level
    question_text = verdict.redacted_text

    def event_stream():
        collected: List[str] = []
        interrupted = False
        started = time.monotonic()
        provider_name = f"gemini:{settings.gemini_model}"
        frames = 0
        first_frame_at: Optional[float] = None

        def mark(stage: str, extra: str = "") -> None:
            if settings.stream_debug:
                logger.info(
                    "[SSE] %s t=%.3fs %s", stage, time.monotonic() - started, extra
                )

        try:
            # Padding first. A proxy that holds a response until some minimum
            # is buffered will otherwise keep the stream open and silent, which
            # looks exactly like "streaming does not work". SSE comment lines
            # start with ':' and every client ignores them.
            if settings.sse_preamble_bytes > 0:
                yield ":" + (" " * settings.sse_preamble_bytes) + "\n\n"
                mark("preamble flushed", f"bytes={settings.sse_preamble_bytes}")

            yield _sse("start", {"session_id": session_id})
            mark("start frame")

            for fragment in provider.stream(question_text, history, context, lang):
                collected.append(fragment)
                frames += 1
                if first_frame_at is None:
                    first_frame_at = time.monotonic() - started
                mark("chunk sent to client", f"n={frames} chars={len(fragment)}")
                yield _sse("chunk", {"text": fragment})

            mark("done frame", f"frames={frames}")
            if settings.stream_debug:
                logger.info(
                    "[SSE] SUMMARY frames=%d first_at=%.2fs last_at=%.2fs "
                    "-> compare with [GEMINI] SUMMARY: equal means this process "
                    "forwarded every chunk the moment it arrived",
                    frames, first_frame_at or 0.0, time.monotonic() - started,
                )
            yield _sse(
                "done",
                {
                    "session_id": session_id,
                    "blocked": False,
                    "risk_level": risk_level.value,
                    "disclaimer": settings.disclaimer,
                    "model": settings.gemini_model,
                    "interrupted": False,
                },
            )

        except GeneratorExit:
            # The client went away — Stop was pressed, or the tab closed.
            # Whatever arrived is still the user's, so it is saved.
            interrupted = True
            raise
        except GeminiError as exc:
            logger.error(
                "assistant stream failed user=%s chars=%d error=%s",
                user_id, sum(len(c) for c in collected), exc.detail,
            )
            # Same reasoning as the non-streaming path: a capacity failure
            # degrades to the offline engine rather than surfacing an error.
            #
            # The `not collected` guard matters. Once fragments have reached
            # the client, swapping providers would splice the first half of a
            # Gemini answer onto the whole of a rules answer, and the student
            # would read one incoherent paragraph. A partial answer that stops
            # honestly is better than a seamless one that is two answers.
            if isinstance(exc, (GeminiRateLimited, GeminiUnavailable)) and not collected:
                logger.warning(
                    "assistant stream falling back to rules user=%s reason=%s",
                    user_id, type(exc).__name__,
                )
                provider_name = "rules (fallback)"
                fallback = RuleBasedProvider().reply(
                    question_text, history, context, lang
                )
                for piece in _chunk_for_stream(fallback.content):
                    collected.append(piece)
                    yield _sse("chunk", {"text": piece})
                yield _sse(
                    "done",
                    {
                        "session_id": session_id,
                        "blocked": False,
                        "risk_level": risk_level.value,
                        "disclaimer": settings.disclaimer,
                        "model": None,
                        "notice": FALLBACK_NOTICE,
                        "interrupted": False,
                    },
                )
            else:
                interrupted = True
                yield _sse(
                    "error", {"detail": exc.user_message, "partial": bool(collected)}
                )
        except Exception:  # noqa: BLE001 - never leak a traceback into the stream
            interrupted = True
            logger.exception("assistant stream crashed user=%s", user_id)
            yield _sse(
                "error",
                {
                    "detail": "Medly AI is temporarily unavailable. Please try again in a moment.",
                    "partial": bool(collected),
                },
            )
        finally:
            _in_flight.release(limit_key)
            final = "".join(collected)
            if final:
                try:
                    # One row for the whole answer, not one per chunk.
                    _persist_answer(
                        session_id=session_id,
                        user_id=user_id,
                        risk_level=risk_level,
                        question=question_text,
                        text=final,
                        provider=provider_name,
                        interrupted=interrupted,
                        lang=lang,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("assistant stream: could not persist answer")
            logger.info(
                "assistant stream end user=%s latency_ms=%d chars=%d interrupted=%s context=%s",
                user_id, int((time.monotonic() - started) * 1000), len(final),
                interrupted, f"{kind or '-'}:{key or '-'}",
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # nginx/proxies must not buffer this
            "Connection": "keep-alive",
        },
    )


@router.get("/debug-stream")
def debug_stream():
    """Infrastructure probe. Four frames, one second apart, no model involved.

    This exists to split one question into two: does the *path* stream, or
    does Gemini? Watch it with

        curl -N https://<backend>/api/assistant/debug-stream

    and read the arrival times:

      * frames arrive one per second  -> FastAPI, uvicorn and the proxy are all
        streaming correctly, and any delay in the real endpoint is Gemini or
        the browser.
      * all four arrive together at the end -> something between this process
        and your terminal is buffering. That is a proxy or platform setting,
        not application code.

    Unauthenticated on purpose so `curl` needs no token, and therefore disabled
    unless MEDLY_STREAM_DEBUG is set. It returns no data of any kind. Turn it
    off once the question is answered.
    """
    if not settings.stream_debug:
        raise HTTPException(status_code=404, detail="Not found")

    def frames():
        if settings.sse_preamble_bytes > 0:
            yield ":" + (" " * settings.sse_preamble_bytes) + "\n\n"
        started = time.monotonic()
        for word in ("ONE", " TWO", " THREE", " FOUR"):
            elapsed = time.monotonic() - started
            logger.info("[DEBUG-STREAM] sending %s at t=%.3fs", word.strip(), elapsed)
            yield _sse("chunk", {"text": word, "t": round(elapsed, 3)})
            time.sleep(1)
        yield _sse("done", {"total_seconds": round(time.monotonic() - started, 3)})

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
