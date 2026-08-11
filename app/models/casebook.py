"""Teacher-authored imaging case references, and their anonymisation state.

The intended production path is:

    Teacher -> Case reference -> Hospital scan -> Anonymisation -> Student

Nothing reaches a student until a human has confirmed the redaction. The
automatic pass is treated as a proposal, never as proof: `anonymization_status`
has to reach `verified`, and only a teacher can move it there.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.models.enums import Modality


class CaseReference(SQLModel, table=True):
    __tablename__ = "case_references"

    id: Optional[int] = Field(default=None, primary_key=True)
    case_ref: str = Field(index=True, unique=True)
    title: str
    modality: Modality = Field(default=Modality.XRAY)
    body_region: str = Field(default="Chest")
    # Age band and sex only — never a date of birth, never a name.
    patient_age_band: str = Field(default="")
    patient_sex: str = Field(default="")
    clinical_context: str = Field(default="")
    teaching_points: str = Field(default="")
    findings_summary: str = Field(default="")
    difficulty: str = Field(default="medium")
    source: str = Field(default="synthetic")  # synthetic | hospital
    created_by: int = Field(foreign_key="users.id", index=True)
    published: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class CaseImage(SQLModel, table=True):
    __tablename__ = "case_images"

    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: int = Field(foreign_key="case_references.id", index=True)
    caption: str = Field(default="")
    view: str = Field(default="PA")
    # Deterministic synthetic panel seed. Real deployments would put an object
    # key here instead; the anonymisation contract below is unchanged either way.
    render_seed: str = Field(default="")

    # ---- anonymisation ----
    # pending -> auto_redacted -> verified. Students only ever see `verified`.
    anonymization_status: str = Field(default="pending", index=True)
    # JSON list of identifier fields the automatic pass removed, e.g.
    # ["PatientName", "PatientBirthDate", "burned-in overlay"].
    redacted_fields_json: str = Field(default="[]")
    # What the automatic pass flagged but could not resolve on its own.
    review_notes: str = Field(default="")
    verified_by: Optional[int] = Field(default=None, foreign_key="users.id")
    verified_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CaseView(SQLModel, table=True):
    """Which student opened which case — the teaching-side audit trail."""

    __tablename__ = "case_views"

    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: int = Field(foreign_key="case_references.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    viewed_at: datetime = Field(default_factory=datetime.utcnow)
