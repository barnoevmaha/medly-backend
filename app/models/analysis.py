"""Imaging analysis jobs run through the simulated inference engine."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.models.enums import AnalysisStatus, Modality


class AnalysisJob(SQLModel, table=True):
    __tablename__ = "analysis_jobs"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    case_ref: str = Field(default="")
    modality: Modality = Field(default=Modality.XRAY)
    status: AnalysisStatus = Field(default=AnalysisStatus.PENDING, index=True)

    # JSON list of {"label", "confidence", "bbox": [x, y, w, h]}
    findings_json: str = Field(default="[]")
    model_name: str = Field(default="")
    model_version: str = Field(default="")
    mean_confidence: float = Field(default=0.0)
    # True when the model is not confident enough to be shown without a caveat.
    uncertainty_flag: bool = Field(default=False)
    requires_review: bool = Field(default=False, index=True)

    # The student commits their own read before the AI output is revealed.
    student_finding: Optional[str] = None
    student_finding_at: Optional[datetime] = None
    final_decision: Optional[str] = None
    agreed_with_ai: Optional[bool] = None

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
