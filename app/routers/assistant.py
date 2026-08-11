"""The fixed-corner study assistant.

Every request follows the same path, with no bypass:

    screen -> (refuse and log) or (answer -> disclaimer -> log)
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, select

from app.config import settings
from app.db import get_session
from app.models.assistant import AssistantMessage
from app.models.enums import EventType, RiskLevel
from app.models.challenge import Challenge
from app.models.social import Article, Resource
from app.models.user import User
from app.security import get_current_user
from app.services import ratelimit, safety
from app.services.assistant import get_provider, suggested_prompts
from app.services.audit import log_event
from app.services.gemini import (
    GeminiError,
    GeminiRateLimited,
    GeminiUnavailable,
)

logger = logging.getLogger("medly.assistant")

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

HISTORY_TURNS = settings.ai_history_turns

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

    kind = payload.context_kind or ("article" if payload.article_slug else None)
    key = payload.context_key or payload.article_slug
    context = _page_context(session, kind, key, payload.context_note)

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
        try:
            result = provider.reply(verdict.redacted_text, history, context)
        except GeminiError as exc:
            # The detail goes to the log; only `user_message` reaches the client.
            logger.error(
                "assistant provider failed user=%s provider=%s error=%s",
                user.id, settings.assistant_provider, exc.detail,
            )
            status = 429 if isinstance(exc, GeminiRateLimited) else 503
            if not isinstance(exc, (GeminiRateLimited, GeminiUnavailable)):
                status = 503
            raise HTTPException(status_code=status, detail=exc.user_message) from exc
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
            f"{kind or '-'}:{key or '-'}",
        )
    finally:
        _in_flight.release(key)

    answer = safety.apply_disclaimer(result.content, verdict.risk_level)

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
