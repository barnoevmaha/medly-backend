"""Users and their competency state."""
from __future__ import annotations

from datetime import date, datetime
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
    # Data URL or path. Set from Settings; rendered by <Avatar> everywhere.
    avatar_url: str = Field(default="")

    # Gamification. Points are the single source of truth for rank — nothing in
    # the product is allowed to display a hardcoded score.
    points: int = Field(default=0, index=True)

    # Streak. `last_active_on` is a date, not a timestamp: a streak counts days
    # a student showed up, and storing the day directly makes the "did they
    # already count today?" check a comparison rather than a calculation.
    streak_days: int = Field(default=0)
    longest_streak: int = Field(default=0)
    last_active_on: Optional[date] = None

    # Premium unlocks community creation. Enforced in the router, not the UI.
    is_premium: bool = Field(default=False, index=True)

    # Privacy: opting out hides the row from the public leaderboard. The user's
    # own rank is still calculated honestly and shown to them.
    show_on_leaderboard: bool = Field(default=True)

    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Profile picture. Seeded demo accounts point at /covers/avatars/*.svg so a
    # single user has the same picture everywhere the avatar renders.
    avatar_url: str = Field(default="")
