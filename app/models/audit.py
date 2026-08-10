"""The accountability layer.

Every AI-touched action writes one immutable row here. This is what makes the
platform auditable, and it is the evidence base for the governance dashboard.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.models.enums import EventType, RiskLevel


class AuditEvent(SQLModel, table=True):
    __tablename__ = "audit_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    event_type: EventType = Field(index=True)
    risk_level: RiskLevel = Field(default=RiskLevel.NONE, index=True)

    # What the AI was and what it said.
    ai_model: Optional[str] = None
    ai_version: Optional[str] = None
    ai_output_summary: Optional[str] = None
    confidence: Optional[float] = None

    # What the human did about it. `overridden` is the automation-bias metric:
    # if it is always False, students are rubber-stamping the model.
    human_decision: Optional[str] = None
    overridden: Optional[bool] = Field(default=None, index=True)

    # Safety posture at the moment of the event.
    disclaimer_shown: bool = Field(default=True)
    blocked: bool = Field(default=False, index=True)
    block_reason: Optional[str] = None
    requires_review: bool = Field(default=False, index=True)
    reviewed_by: Optional[int] = Field(default=None, foreign_key="users.id")
    reviewed_at: Optional[datetime] = None

    resource_type: Optional[str] = None
    resource_id: Optional[int] = None
    session_id: Optional[str] = Field(default=None, index=True)
    meta_json: str = Field(default="{}")
