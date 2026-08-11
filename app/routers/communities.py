"""Communities: discovery, membership, chat, and the premium gate on creation."""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, func, or_, select

from app.db import get_session
from app.lang import get_lang
from app.models.community import Community, CommunityMember, CommunityMessage
from app.models.enums import Role
from app.models.user import User
from app.security import get_current_user
from app.services import gamification, localize

router = APIRouter(prefix="/api/communities", tags=["communities"])

# Instructors and admins run the teaching side, so they are not held behind the
# consumer paywall. Everyone else needs premium.
CAN_CREATE_ROLES = {Role.INSTRUCTOR, Role.ADMIN}


class CommunityOut(BaseModel):
    id: int
    slug: str
    name: str
    description: str
    specialty: str
    icon: str
    cover: str
    members: int
    messages: int
    joined: bool
    owned: bool
    created_at: datetime


class MessageOut(BaseModel):
    id: int
    author: str
    author_role: str
    body: str
    created_at: datetime
    mine: bool


class CommunityDetailOut(CommunityOut):
    member_names: List[str]
    can_post: bool


class CommunityIn(BaseModel):
    name: str = PydanticField(min_length=3, max_length=60)
    description: str = PydanticField(min_length=10, max_length=280)
    specialty: str = "General"
    icon: str = "stethoscope"


class MessageIn(BaseModel):
    body: str = PydanticField(min_length=1, max_length=1000)


def _may_create(user: User) -> bool:
    return bool(user.is_premium) or user.role in CAN_CREATE_ROLES


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return base or "community"


def _member_count(session: Session, community: Community) -> int:
    real = int(
        session.exec(
            select(func.count()).select_from(CommunityMember).where(
                CommunityMember.community_id == community.id
            )
        ).one()
    )
    return community.base_members + real


def _message_count(session: Session, community_id: int) -> int:
    return int(
        session.exec(
            select(func.count()).select_from(CommunityMessage).where(
                CommunityMessage.community_id == community_id
            )
        ).one()
    )


def _to_out(session: Session, community: Community, user: User, joined_ids: set, lang: str) -> CommunityOut:
    return CommunityOut(
        id=community.id or 0,
        slug=community.slug,
        name=localize.read(community, "name", lang),
        description=localize.read(community, "description", lang),
        specialty=community.specialty,
        icon=community.icon,
        cover=community.cover,
        members=_member_count(session, community),
        messages=_message_count(session, community.id or 0),
        joined=community.id in joined_ids,
        owned=community.created_by == user.id,
        created_at=community.created_at,
    )


def _joined_ids(session: Session, user_id: int) -> set:
    return {
        row.community_id
        for row in session.exec(
            select(CommunityMember).where(CommunityMember.user_id == user_id)
        ).all()
    }


@router.get("/permissions")
def permissions(user: User = Depends(get_current_user)) -> dict:
    """What the current account may do — the UI mirrors this, it does not invent it."""
    return {
        "can_create": _may_create(user),
        "is_premium": bool(user.is_premium),
        "role": user.role.value,
        "reason": (
            ""
            if _may_create(user)
            else "Creating a community is a Premium feature."
        ),
    }


@router.get("", response_model=List[CommunityOut])
def list_communities(
    q: Optional[str] = Query(default=None, description="Matches name and description only"),
    filter: Optional[str] = None,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> List[CommunityOut]:
    """Search is scoped to the name and the line under it — nothing else.

    Deliberately not messages and not member names: a search for "cardio" should
    return the Cardiology community, not every group where somebody typed the
    word in chat.
    """
    statement = select(Community)
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        statement = statement.where(
            or_(
                func.lower(Community.name).like(needle),
                func.lower(Community.description).like(needle),
            )
        )
    communities = session.exec(statement.order_by(Community.name)).all()
    joined = _joined_ids(session, user.id or 0)

    localize.ensure_fields(session, localize.fields_for(communities, ("name", "description")), lang)
    out = [_to_out(session, community, user, joined, lang) for community in communities]
    if filter == "My Communities":
        out = [item for item in out if item.joined]
    elif filter == "Popular":
        out = sorted(out, key=lambda item: item.members, reverse=True)
    elif filter == "New":
        out = sorted(out, key=lambda item: item.created_at, reverse=True)
    return out


@router.get("/mine", response_model=List[CommunityOut])
def my_communities(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> List[CommunityOut]:
    joined = _joined_ids(session, user.id or 0)
    if not joined:
        return []
    communities = session.exec(
        select(Community).where(Community.id.in_(joined))  # type: ignore[union-attr]
    ).all()
    localize.ensure_fields(session, localize.fields_for(communities, ("name", "description")), lang)
    return [_to_out(session, community, user, joined, lang) for community in communities]


@router.post("", response_model=CommunityOut, status_code=status.HTTP_201_CREATED)
def create_community(
    payload: CommunityIn,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> CommunityOut:
    """Premium-only, enforced here.

    The button is hidden for non-premium accounts, but that is a courtesy. This
    check is the actual rule: a direct POST from curl gets the same 403.
    """
    if not _may_create(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Creating a community is a Premium feature. Upgrade to Premium to "
                "start your own community."
            ),
        )

    slug = _slugify(payload.name)
    if session.exec(select(Community).where(Community.slug == slug)).first():
        slug = f"{slug}-{int(datetime.utcnow().timestamp()) % 10000}"

    community = Community(
        slug=slug,
        name=payload.name.strip(),
        description=payload.description.strip(),
        specialty=payload.specialty.strip() or "General",
        icon=payload.icon.strip() or "stethoscope",
        created_by=user.id,
    )
    session.add(community)
    session.commit()
    session.refresh(community)

    session.add(CommunityMember(community_id=community.id or 0, user_id=user.id or 0))
    session.commit()
    gamification.sync_badges(session, user)

    return _to_out(session, community, user, _joined_ids(session, user.id or 0), lang)


def _get(session: Session, slug: str) -> Community:
    community = session.exec(select(Community).where(Community.slug == slug)).first()
    if not community:
        raise HTTPException(status_code=404, detail="Community not found")
    return community


@router.get("/{slug}", response_model=CommunityDetailOut)
def get_community(
    slug: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> CommunityDetailOut:
    community = _get(session, slug)
    joined = _joined_ids(session, user.id or 0)
    localize.ensure_fields(session, [(community, "name"), (community, "description")], lang)
    base = _to_out(session, community, user, joined, lang)

    rows = session.exec(
        select(User)
        .where(User.id == CommunityMember.user_id)
        .where(CommunityMember.community_id == community.id)
        .limit(12)
    ).all()

    return CommunityDetailOut(
        **base.model_dump(),
        member_names=[person.full_name for person in rows],
        can_post=community.id in joined,
    )


@router.post("/{slug}/join", response_model=CommunityOut)
def join(
    slug: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> CommunityOut:
    community = _get(session, slug)
    existing = session.exec(
        select(CommunityMember).where(
            CommunityMember.community_id == community.id,
            CommunityMember.user_id == user.id,
        )
    ).first()
    if not existing:
        session.add(CommunityMember(community_id=community.id or 0, user_id=user.id or 0))
        session.commit()
        gamification.sync_badges(session, user)
    return _to_out(session, community, user, _joined_ids(session, user.id or 0), lang)


@router.post("/{slug}/leave", response_model=CommunityOut)
def leave(
    slug: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    lang: str = Depends(get_lang),
) -> CommunityOut:
    community = _get(session, slug)
    existing = session.exec(
        select(CommunityMember).where(
            CommunityMember.community_id == community.id,
            CommunityMember.user_id == user.id,
        )
    ).first()
    if existing:
        session.delete(existing)
        session.commit()
    return _to_out(session, community, user, _joined_ids(session, user.id or 0), lang)


@router.get("/{slug}/messages", response_model=List[MessageOut])
def messages(
    slug: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> List[MessageOut]:
    community = _get(session, slug)
    rows = session.exec(
        select(CommunityMessage)
        .where(CommunityMessage.community_id == community.id)
        .order_by(CommunityMessage.created_at.asc())  # type: ignore[union-attr]
    ).all()

    authors = {
        person.id: person
        for person in session.exec(
            select(User).where(
                User.id.in_([row.user_id for row in rows if row.user_id])  # type: ignore[union-attr]
            )
        ).all()
    } if any(row.user_id for row in rows) else {}

    out: List[MessageOut] = []
    for row in rows:
        person = authors.get(row.user_id) if row.user_id else None
        out.append(
            MessageOut(
                id=row.id or 0,
                author=person.full_name if person else (row.author_name or "Member"),
                author_role=person.role.value if person else "student",
                body=row.body,
                created_at=row.created_at,
                mine=bool(person and person.id == user.id),
            )
        )
    return out


@router.post("/{slug}/messages", response_model=MessageOut, status_code=201)
def post_message(
    slug: str,
    payload: MessageIn,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> MessageOut:
    community = _get(session, slug)

    # Posting implies membership; joining on first message is friendlier than a
    # 403 the user has to work out for themselves.
    joined = session.exec(
        select(CommunityMember).where(
            CommunityMember.community_id == community.id,
            CommunityMember.user_id == user.id,
        )
    ).first()
    if not joined:
        session.add(CommunityMember(community_id=community.id or 0, user_id=user.id or 0))
        session.commit()

    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="Message cannot be empty")

    message = CommunityMessage(
        community_id=community.id or 0, user_id=user.id, body=body
    )
    session.add(message)
    session.commit()
    session.refresh(message)

    return MessageOut(
        id=message.id or 0,
        author=user.full_name,
        author_role=user.role.value,
        body=message.body,
        created_at=message.created_at,
        mine=True,
    )
