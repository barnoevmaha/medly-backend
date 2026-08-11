"""Teacher-authored case references, and the route a scan takes to a student.

    Teacher -> Case reference -> Scan -> Anonymisation -> Verification -> Student

Only instructors and admins can create or manage cases. Students can only read
published ones, and a case cannot be published while any of its images is still
waiting on human verification of its redaction.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, select

from app.db import get_session
from app.models.casebook import CaseImage, CaseReference, CaseView
from app.models.enums import Modality, Role
from app.models.user import User
from app.security import get_current_user
from app.services.anonymize import RESIDUAL_RISKS, anonymize

router = APIRouter(prefix="/api/casebook", tags=["casebook"])

TEACHER_ROLES = {Role.INSTRUCTOR, Role.ADMIN}


def _is_teacher(user: User) -> bool:
    return user.role in TEACHER_ROLES


def _require_teacher(user: User = Depends(get_current_user)) -> User:
    if not _is_teacher(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Only teachers can create or manage case references. Students can "
                "open published cases."
            ),
        )
    return user


class ImageOut(BaseModel):
    id: int
    caption: str
    view: str
    render_seed: str
    anonymization_status: str
    redacted_fields: List[str]
    review_notes: str
    verified_by_name: Optional[str] = None
    verified_at: Optional[datetime] = None


class CaseOut(BaseModel):
    id: int
    case_ref: str
    title: str
    modality: Modality
    body_region: str
    patient_age_band: str
    patient_sex: str
    clinical_context: str
    difficulty: str
    source: str
    published: bool
    author_name: str
    image_count: int
    pending_verification: int
    created_at: datetime
    mine: bool


class CaseDetailOut(CaseOut):
    teaching_points: str
    findings_summary: str
    images: List[ImageOut]
    residual_risks: List[str]


class CaseIn(BaseModel):
    case_ref: str = PydanticField(min_length=3, max_length=40)
    title: str = PydanticField(min_length=3, max_length=140)
    modality: Modality = Modality.XRAY
    body_region: str = "Chest"
    patient_age_band: str = ""
    patient_sex: str = ""
    clinical_context: str = ""
    teaching_points: str = ""
    findings_summary: str = ""
    difficulty: str = "medium"
    source: str = "synthetic"


class ImageIn(BaseModel):
    caption: str = ""
    view: str = "PA"
    # Stand-in for the DICOM header that would arrive with a hospital scan.
    metadata: Dict[str, str] = {}
    # Stand-in for text burned into the pixels.
    overlay_text: str = ""


def _image_out(session: Session, image: CaseImage) -> ImageOut:
    verifier = session.get(User, image.verified_by) if image.verified_by else None
    return ImageOut(
        id=image.id or 0,
        caption=image.caption,
        view=image.view,
        render_seed=image.render_seed,
        anonymization_status=image.anonymization_status,
        redacted_fields=json.loads(image.redacted_fields_json or "[]"),
        review_notes=image.review_notes,
        verified_by_name=verifier.full_name if verifier else None,
        verified_at=image.verified_at,
    )


def _images(session: Session, case_id: int) -> List[CaseImage]:
    return list(
        session.exec(select(CaseImage).where(CaseImage.case_id == case_id)).all()
    )


def _case_out(session: Session, case: CaseReference, user: User) -> CaseOut:
    author = session.get(User, case.created_by)
    images = _images(session, case.id or 0)
    return CaseOut(
        id=case.id or 0,
        case_ref=case.case_ref,
        title=case.title,
        modality=case.modality,
        body_region=case.body_region,
        patient_age_band=case.patient_age_band,
        patient_sex=case.patient_sex,
        clinical_context=case.clinical_context,
        difficulty=case.difficulty,
        source=case.source,
        published=case.published,
        author_name=author.full_name if author else "Unknown",
        image_count=len(images),
        pending_verification=sum(
            1 for image in images if image.anonymization_status != "verified"
        ),
        created_at=case.created_at,
        mine=case.created_by == user.id,
    )


@router.get("/permissions")
def permissions(user: User = Depends(get_current_user)) -> dict:
    return {
        "can_author": _is_teacher(user),
        "role": user.role.value,
        "reason": "" if _is_teacher(user) else "Case references are authored by teachers.",
    }


@router.get("/cases", response_model=List[CaseOut])
def list_cases(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> List[CaseOut]:
    statement = select(CaseReference)
    if not _is_teacher(user):
        statement = statement.where(CaseReference.published == True)  # noqa: E712
    cases = session.exec(statement.order_by(CaseReference.created_at.desc())).all()  # type: ignore[union-attr]
    return [_case_out(session, case, user) for case in cases]


@router.post("/cases", response_model=CaseDetailOut, status_code=201)
def create_case(
    payload: CaseIn,
    session: Session = Depends(get_session),
    user: User = Depends(_require_teacher),
) -> CaseDetailOut:
    existing = session.exec(
        select(CaseReference).where(CaseReference.case_ref == payload.case_ref.strip())
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="That case reference already exists")

    case = CaseReference(
        case_ref=payload.case_ref.strip(),
        title=payload.title.strip(),
        modality=payload.modality,
        body_region=payload.body_region,
        patient_age_band=payload.patient_age_band,
        patient_sex=payload.patient_sex,
        clinical_context=payload.clinical_context,
        teaching_points=payload.teaching_points,
        findings_summary=payload.findings_summary,
        difficulty=payload.difficulty,
        source=payload.source,
        created_by=user.id or 0,
        published=False,
    )
    session.add(case)
    session.commit()
    session.refresh(case)
    return _detail(session, case, user)


def _detail(session: Session, case: CaseReference, user: User) -> CaseDetailOut:
    base = _case_out(session, case, user)
    images = _images(session, case.id or 0)
    if not _is_teacher(user):
        # A student never receives an image whose redaction is unverified.
        images = [image for image in images if image.anonymization_status == "verified"]
    return CaseDetailOut(
        **base.model_dump(),
        teaching_points=case.teaching_points,
        findings_summary=case.findings_summary,
        images=[_image_out(session, image) for image in images],
        residual_risks=RESIDUAL_RISKS,
    )


@router.get("/cases/{case_id}", response_model=CaseDetailOut)
def get_case(
    case_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CaseDetailOut:
    case = session.get(CaseReference, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if not case.published and not _is_teacher(user):
        raise HTTPException(status_code=403, detail="This case has not been published yet")

    if not _is_teacher(user):
        session.add(CaseView(case_id=case.id or 0, user_id=user.id or 0))
        session.commit()

    return _detail(session, case, user)


@router.post("/cases/{case_id}/images", response_model=ImageOut, status_code=201)
def add_image(
    case_id: int,
    payload: ImageIn,
    session: Session = Depends(get_session),
    user: User = Depends(_require_teacher),
) -> ImageOut:
    """Attach a scan and run the automatic redaction pass over its metadata.

    The image lands as `auto_redacted`, which is explicitly not good enough to
    show anybody. A teacher has to verify it.
    """
    case = session.get(CaseReference, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    result = anonymize(payload.metadata, payload.overlay_text)
    image = CaseImage(
        case_id=case.id or 0,
        caption=payload.caption.strip(),
        view=payload.view.strip() or "PA",
        render_seed=f"{case.case_ref}-{payload.view}-{datetime.utcnow().timestamp():.0f}",
        anonymization_status=str(result["status"]),
        redacted_fields_json=json.dumps(result["removed_fields"]),
        review_notes=str(result["notes"]),
    )
    session.add(image)
    session.commit()
    session.refresh(image)
    return _image_out(session, image)


@router.post("/images/{image_id}/verify", response_model=ImageOut)
def verify_anonymization(
    image_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(_require_teacher),
) -> ImageOut:
    """The human step. Only a teacher can sign off a redaction."""
    image = session.get(CaseImage, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    if image.anonymization_status == "pending":
        raise HTTPException(
            status_code=409,
            detail="Run the redaction pass before verifying it",
        )
    image.anonymization_status = "verified"
    image.verified_by = user.id
    image.verified_at = datetime.utcnow()
    session.add(image)
    session.commit()
    session.refresh(image)
    return _image_out(session, image)


@router.post("/cases/{case_id}/publish", response_model=CaseDetailOut)
def publish(
    case_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(_require_teacher),
) -> CaseDetailOut:
    case = session.get(CaseReference, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    images = _images(session, case.id or 0)
    if not images:
        raise HTTPException(status_code=409, detail="Add at least one image before publishing")
    unverified = [image for image in images if image.anonymization_status != "verified"]
    if unverified:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{len(unverified)} image(s) still need anonymisation verified. A case "
                "cannot reach students until every image has been signed off."
            ),
        )

    case.published = True
    session.add(case)
    session.commit()
    session.refresh(case)
    return _detail(session, case, user)


@router.post("/cases/{case_id}/unpublish", response_model=CaseDetailOut)
def unpublish(
    case_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(_require_teacher),
) -> CaseDetailOut:
    case = session.get(CaseReference, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    case.published = False
    session.add(case)
    session.commit()
    session.refresh(case)
    return _detail(session, case, user)
