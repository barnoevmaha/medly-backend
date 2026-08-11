"""Audit trail and the governance dashboard.

Students see their own trail. Instructors and admins see everyone's, because
oversight that only covers volunteers is not oversight.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.config import settings
from app.db import get_session
from app.models.audit import AuditEvent
from app.models.enums import EventType, RiskLevel, Role
from app.models.user import User
from app.security import get_current_user, require_roles
from app.services.safety import SAFETY_STANDARD

router = APIRouter(prefix="/api/governance", tags=["governance"])


class AuditEventOut(BaseModel):
    id: int
    created_at: datetime
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    event_type: EventType
    risk_level: RiskLevel
    ai_model: Optional[str] = None
    ai_version: Optional[str] = None
    ai_output_summary: Optional[str] = None
    confidence: Optional[float] = None
    human_decision: Optional[str] = None
    overridden: Optional[bool] = None
    blocked: bool
    block_reason: Optional[str] = None
    requires_review: bool
    disclaimer_shown: bool
    resource_type: Optional[str] = None
    resource_id: Optional[int] = None
    meta: Dict = {}


class Summary(BaseModel):
    total_ai_interactions: int
    blocked_count: int
    block_rate: float
    override_count: int
    review_count: int
    # The headline metric: how often a human departed from the model.
    override_rate: float
    low_confidence_count: int
    disclaimer_coverage: float
    by_event_type: Dict[str, int]
    by_risk_level: Dict[str, int]
    total_users: int
    confidence_threshold: float
    pending_review: int


class TimeseriesPoint(BaseModel):
    date: str
    interactions: int
    blocked: int
    overrides: int


def _name_map(session: Session, user_ids: List[int]) -> Dict[int, str]:
    ids = [uid for uid in set(user_ids) if uid]
    if not ids:
        return {}
    users = session.exec(select(User).where(User.id.in_(ids))).all()  # type: ignore[union-attr]
    return {u.id: u.full_name for u in users if u.id is not None}


def _to_out(event: AuditEvent, names: Dict[int, str]) -> AuditEventOut:
    try:
        meta = json.loads(event.meta_json or "{}")
    except json.JSONDecodeError:
        meta = {}
    return AuditEventOut(
        id=event.id or 0,
        created_at=event.created_at,
        user_id=event.user_id,
        user_name=names.get(event.user_id or -1),
        event_type=event.event_type,
        risk_level=event.risk_level,
        ai_model=event.ai_model,
        ai_version=event.ai_version,
        ai_output_summary=event.ai_output_summary,
        confidence=event.confidence,
        human_decision=event.human_decision,
        overridden=event.overridden,
        blocked=event.blocked,
        block_reason=event.block_reason,
        requires_review=event.requires_review,
        disclaimer_shown=event.disclaimer_shown,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        meta=meta,
    )


@router.get("/standard")
def standard() -> Dict:
    """The safety standard itself, so the frontend and judges can read it."""
    return {
        "version": "1.0",
        "confidence_threshold": settings.low_confidence_threshold,
        "disclaimer": settings.disclaimer,
        "rules": SAFETY_STANDARD,
    }


@router.get("/audit", response_model=List[AuditEventOut])
def audit_log(
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    event_type: Optional[EventType] = None,
    risk_level: Optional[RiskLevel] = None,
    only_blocked: bool = False,
    only_review: bool = False,
    user_id: Optional[int] = None,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> List[AuditEventOut]:
    statement = select(AuditEvent)

    # Students are scoped to their own trail.
    if user.role == Role.STUDENT:
        statement = statement.where(AuditEvent.user_id == user.id)
    elif user_id is not None:
        statement = statement.where(AuditEvent.user_id == user_id)

    if event_type:
        statement = statement.where(AuditEvent.event_type == event_type)
    if risk_level:
        statement = statement.where(AuditEvent.risk_level == risk_level)
    if only_blocked:
        statement = statement.where(AuditEvent.blocked == True)  # noqa: E712
    if only_review:
        statement = statement.where(AuditEvent.requires_review == True)  # noqa: E712

    events = session.exec(
        statement.order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit)  # type: ignore[union-attr]
    ).all()
    names = _name_map(session, [e.user_id or 0 for e in events])
    return [_to_out(e, names) for e in events]


@router.get("/summary", response_model=Summary)
def summary(
    days: int = Query(default=30, ge=1, le=365),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Summary:
    since = datetime.utcnow() - timedelta(days=days)
    statement = select(AuditEvent).where(AuditEvent.created_at >= since)
    if user.role == Role.STUDENT:
        statement = statement.where(AuditEvent.user_id == user.id)
    events = session.exec(statement).all()

    ai_events = [
        e
        for e in events
        if e.event_type
        in (
            EventType.ASSISTANT_QUERY,
            EventType.ASSISTANT_BLOCKED,
            EventType.ANALYSIS_RETURNED,
            EventType.ANALYSIS_ACCEPTED,
            EventType.ANALYSIS_OVERRIDDEN,
        )
    ]
    decided = [e for e in events if e.overridden is not None]
    overrides = [e for e in decided if e.overridden]
    blocked = [e for e in events if e.blocked]
    low_confidence = [
        e for e in events if e.confidence is not None and e.confidence < settings.low_confidence_threshold
    ]
    reviewable = [e for e in events if e.requires_review]
    pending_review = [e for e in reviewable if e.reviewed_at is None]

    users = session.exec(select(User)).all()

    return Summary(
        total_ai_interactions=len(ai_events),
        blocked_count=len(blocked),
        block_rate=round(len(blocked) / len(ai_events), 4) if ai_events else 0.0,
        override_count=len(overrides),
        review_count=len(reviewable),
        override_rate=round(len(overrides) / len(decided), 4) if decided else 0.0,
        low_confidence_count=len(low_confidence),
        disclaimer_coverage=(
            round(sum(1 for e in ai_events if e.disclaimer_shown) / len(ai_events), 4)
            if ai_events
            else 1.0
        ),
        by_event_type=dict(Counter(e.event_type.value for e in events)),
        by_risk_level=dict(Counter(e.risk_level.value for e in events)),
        total_users=len(users),
        confidence_threshold=settings.low_confidence_threshold,
        pending_review=len(pending_review),
    )


@router.get("/timeseries", response_model=List[TimeseriesPoint])
def timeseries(
    days: int = Query(default=14, ge=1, le=90),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> List[TimeseriesPoint]:
    since = datetime.utcnow() - timedelta(days=days)
    statement = select(AuditEvent).where(AuditEvent.created_at >= since)
    if user.role == Role.STUDENT:
        statement = statement.where(AuditEvent.user_id == user.id)
    events = session.exec(statement).all()

    buckets: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"interactions": 0, "blocked": 0, "overrides": 0}
    )
    for event in events:
        key = event.created_at.date().isoformat()
        buckets[key]["interactions"] += 1
        if event.blocked:
            buckets[key]["blocked"] += 1
        if event.overridden:
            buckets[key]["overrides"] += 1

    points: List[TimeseriesPoint] = []
    for offset in range(days, -1, -1):
        day = (datetime.utcnow() - timedelta(days=offset)).date().isoformat()
        bucket = buckets.get(day, {"interactions": 0, "blocked": 0, "overrides": 0})
        points.append(
            TimeseriesPoint(
                date=day,
                interactions=bucket["interactions"],
                blocked=bucket["blocked"],
                overrides=bucket["overrides"],
            )
        )
    return points


@router.post("/audit/{event_id}/review", response_model=AuditEventOut)
def mark_reviewed(
    event_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_roles(Role.INSTRUCTOR, Role.ADMIN)),
) -> AuditEventOut:
    event = session.get(AuditEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Audit event not found")
    event.reviewed_by = user.id
    event.reviewed_at = datetime.utcnow()
    event.requires_review = False
    session.add(event)
    session.commit()
    session.refresh(event)
    return _to_out(event, _name_map(session, [event.user_id or 0]))
