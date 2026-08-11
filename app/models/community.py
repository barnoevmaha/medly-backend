"""Communities, membership and community chat."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Community(SQLModel, table=True):
    __tablename__ = "communities"

    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    name: str = Field(index=True)
    # The line under the title on the card. Community search matches this and
    # the name only — never messages or member names.
    description: str = Field(default="")
    specialty: str = Field(default="General", index=True)
    icon: str = Field(default="stethoscope")
    cover: str = Field(default="")
    created_by: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    # Seeded communities carry a baseline so the card is not "1 member".
    base_members: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class CommunityMember(SQLModel, table=True):
    __tablename__ = "community_members"

    id: Optional[int] = Field(default=None, primary_key=True)
    community_id: int = Field(foreign_key="communities.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    joined_at: datetime = Field(default_factory=datetime.utcnow)


class CommunityMessage(SQLModel, table=True):
    __tablename__ = "community_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    community_id: int = Field(foreign_key="communities.id", index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    # Seeded conversation uses a display name with no account behind it.
    author_name: str = Field(default="")
    body: str
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
