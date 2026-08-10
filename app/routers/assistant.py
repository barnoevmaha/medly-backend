"""The fixed-corner study assistant.

Every request follows the same path, with no bypass:

    screen -> (refuse and log) or (answer -> disclaimer -> log)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.config import settings
from app.db import get_session
from app.models.assistant import AssistantMessage
from app.models.enums import EventType, RiskLevel
from app.models.user import User
from app.security import get_current_user
from app.services import safety
from app.services.assistant import SUGGESTED_PROMPTS, get_provider
from app.services.audit import log_event

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

HISTORY_TURNS = 6


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    blocked: bool
    block_reason: Optional[str] = None
    risk_level: RiskLevel
    disclaimer: str
    provider: str
    audit_event_id: Optional[int] = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    blocked: bool
    risk_level: RiskLevel
    created_at: datetime


@router.get("/suggestions", response_model=List[str])
def suggestions() -> List[str]:
    return SUGGESTED_PROMPTS


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    session_id = payload.session_id or str(uuid.uuid4())
    verdict = safety.screen_message(payload.message)

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
    history = [
        {"role": row.role, "content": row.content}
        for row in reversed(history_rows)
        if row.content != verdict.redacted_text
    ]

    provider = get_provider()
    result = provider.reply(verdict.redacted_text, history)
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
    )


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
