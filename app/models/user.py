"""Users and their competency state."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.models.enums import Role


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    hashed_password: str
    full_name: str
    role: Role = Field(default=Role.STUDENT, index=True)
    institution: Optional[str] = None
    year_of_study: Optional[int] = None

    # Competency gating: a student cannot use AI-assisted mode until they have
    # passed the safety certification. This is the core of the safety standard.
    certified: bool = Field(default=False, index=True)
    certified_at: Optional[datetime] = None
    competency_score: int = Field(default=0)

    # Gamification. Points are the single source of truth for rank — nothing in
    # the product is allowed to display a hardcoded score.
    points: int = Field(default=0, index=True)
    streak_days: int = Field(default=0)

    # Premium unlocks community creation. Enforced in the router, not the UI.
    is_premium: bool = Field(default=False, index=True)

    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
