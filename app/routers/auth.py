"""Registration, login, and the current-user endpoint."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select

from app.db import get_session
from app.models.enums import Role
from app.models.user import User
from app.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    institution: Optional[str] = None
    year_of_study: Optional[int] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role: Role
    institution: Optional[str] = None
    year_of_study: Optional[int] = None
    points: int = 0
    is_premium: bool = False
    show_on_leaderboard: bool = True
    avatar_url: str = ""


def _to_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id or 0,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        institution=user.institution,
        year_of_study=user.year_of_study,
        points=user.points or 0,
        is_premium=bool(user.is_premium),
        show_on_leaderboard=bool(user.show_on_leaderboard),
        avatar_url=user.avatar_url or "",
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, session: Session = Depends(get_session)) -> TokenResponse:
    existing = session.exec(select(User).where(User.email == payload.email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="That email is already registered")
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    user = User(
        email=str(payload.email),
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        institution=payload.institution,
        year_of_study=payload.year_of_study,
        role=Role.STUDENT,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return TokenResponse(access_token=create_access_token(user.email, user.role.value))


@router.post("/login", response_model=TokenResponse)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
) -> TokenResponse:
    user = session.exec(select(User).where(User.email == form.username)).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(access_token=create_access_token(user.email, user.role.value))


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> UserResponse:
    return _to_response(user)


class UpdateProfileRequest(BaseModel):
    """Everything the Settings page is allowed to change about an account.

    Notably absent: `role`, `points` and `is_premium`. Those are earned or
    granted elsewhere, and a settings form is not the place to edit them — a
    client that sends them is ignored rather than obeyed.
    """

    full_name: Optional[str] = None
    institution: Optional[str] = None
    year_of_study: Optional[int] = None
    show_on_leaderboard: Optional[bool] = None


@router.patch("/me", response_model=UserResponse)
def update_me(
    payload: UpdateProfileRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> UserResponse:
    if payload.full_name is not None:
        name = payload.full_name.strip()
        if len(name) < 2:
            raise HTTPException(status_code=422, detail="Name must be at least 2 characters")
        user.full_name = name
    if payload.institution is not None:
        user.institution = payload.institution.strip() or None
    if payload.year_of_study is not None:
        if not 1 <= payload.year_of_study <= 10:
            raise HTTPException(status_code=422, detail="Year of study must be between 1 and 10")
        user.year_of_study = payload.year_of_study
    if payload.show_on_leaderboard is not None:
        user.show_on_leaderboard = payload.show_on_leaderboard

    session.add(user)
    session.commit()
    session.refresh(user)
    return _to_response(user)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChangeRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    """Change the password.

    The current password is required even though the caller already holds a
    valid token — a stolen token should not be enough to lock the owner out.
    """
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=400, detail="New password must be different")

    user.hashed_password = hash_password(payload.new_password)
    session.add(user)
    session.commit()
