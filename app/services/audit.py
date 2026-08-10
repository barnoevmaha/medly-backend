"""Audit writer. Rule 5 of the safety standard.

Nothing AI-related happens without a row landing here.
"""
from __future__ import annotations

import json
from typing import Optional

from sqlmodel import Session

from app.models.audit import AuditEvent
from app.models.enums import EventType, RiskLevel


def log_event(
    session: Session,
    *,
    user_id: Optional[int],
    event_type: EventType,
    risk_level: RiskLevel = RiskLevel.NONE,
    ai_model: Optional[str] = None,
    ai_version: Optional[str] = None,
    ai_output_summary: Optional[str] = None,
    confidence: Optional[float] = None,
    human_decision: Optional[str] = None,
    overridden: Optional[bool] = None,
    disclaimer_shown: bool = True,
    blocked: bool = False,
    block_reason: Optional[str] = None,
    requires_review: bool = False,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    session_id: Optional[str] = None,
    meta: Optional[dict] = None,
    commit: bool = True,
) -> AuditEvent:
    event = AuditEvent(
        user_id=user_id,
        event_type=event_type,
        risk_level=risk_level,
        ai_model=ai_model,
        ai_version=ai_version,
        ai_output_summary=(ai_output_summary or "")[:500] or None,
        confidence=confidence,
        human_decision=human_decision,
        overridden=overridden,
        disclaimer_shown=disclaimer_shown,
        blocked=blocked,
        block_reason=block_reason,
        requires_review=requires_review,
        resource_type=resource_type,
        resource_id=resource_id,
        session_id=session_id,
        meta_json=json.dumps(meta or {}),
    )
    session.add(event)
    if commit:
        session.commit()
        session.refresh(event)
    return event
