"""Conversation history for the student-facing AI assistant."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.models.enums import RiskLevel


class AssistantMessage(SQLModel, table=True):
    __tablename__ = "assistant_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    role: str = Field(default="user")  # "user" | "assistant"
    content: str
    risk_level: RiskLevel = Field(default=RiskLevel.NONE)
    blocked: bool = Field(default=False)
    block_reason: Optional[str] = None
    provider: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
