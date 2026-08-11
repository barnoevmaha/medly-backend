"""Badges earned from real activity.

Badge definitions live in services/badges.py; this table only records what a
given user has actually earned, and when.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class UserBadge(SQLModel, table=True):
    __tablename__ = "user_badges"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    badge_key: str = Field(index=True)
    earned_at: datetime = Field(default_factory=datetime.utcnow)
