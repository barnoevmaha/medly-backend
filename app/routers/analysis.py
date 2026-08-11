"""Imaging analysis, sequenced to fight automation bias.

The order is deliberate and enforced server-side:

    1. POST /cases            create the case
    2. POST /{id}/my-reading  the student commits their own read
    3. POST /{id}/analyze     only now is the model run and revealed
    4. POST /{id}/decide      the student records the final call, agree or not

Step 3 refuses to run before step 2. Reading the model first is not an option.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.config import settings
from app.db import get_session
from app.models.analysis import AnalysisJob
from app.models.enums import AnalysisStatus, EventType, Modality, RiskLevel
from app.models.user import User
from app.security import get_current_user
from app.services.audit import log_event
from app.services.inference import get_engine
from app.services.safety import evaluate_confidence

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


class CaseCreate(BaseModel):
    case_ref: str
    modality: Modality = Modality.XRAY


class ReadingRequest(BaseModel):
    finding: str


class DecisionRequest(BaseModel):
    final_decision: str
    agreed_with_ai: bool


class FindingOut(BaseModel):
    label: str
    confidence: float
    bbox: List[float]
    description: str


class JobOut(BaseModel):
    id: int
    case_ref: str
    modality: Modality
    status: AnalysisStatus
    student_finding: Optional[str] = None
    findings: List[FindingOut] = []
    model_name: str = ""
    model_version: str = ""
    mean_confidence: float = 0.0
    uncertainty_flag: bool = False
    requires_review: bool = False
    final_decision: Optional[str] = None
    agreed_with_ai: Optional[bool] = None
    disclaimer: str = settings.disclaimer
    known_limitations: List[str] = []
    created_at: datetime


def _to_out(job: AnalysisJob, limitations: Optional[List[str]] = None) -> JobOut:
    raw = json.loads(job.findings_json or "[]")
    return JobOut(
        id=job.id or 0,
        case_ref=job.case_ref,
        modality=job.modality,
        status=job.status,
        student_finding=job.student_finding,
        findings=[FindingOut(**f) for f in raw],
        model_name=job.model_name,
        model_version=job.model_version,
        mean_confidence=job.mean_confidence,
        uncertainty_flag=job.uncertainty_flag,
        requires_review=job.requires_review,
        final_decision=job.final_decision,
        agreed_with_ai=job.agreed_with_ai,
        known_limitations=limitations or [],
        created_at=job.created_at,
    )


def _owned(session: Session, job_id: int, user: User) -> AnalysisJob:
    job = session.get(AnalysisJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Case not found")
    return job


@router.post("/cases", response_model=JobOut, status_code=201)
def create_case(
    payload: CaseCreate,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> JobOut:
    job = AnalysisJob(
        user_id=user.id or 0, case_ref=payload.case_ref, modality=payload.modality
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return _to_out(job)


@router.get("/cases", response_model=List[JobOut])
def my_cases(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> List[JobOut]:
    jobs = session.exec(
        select(AnalysisJob)
        .where(AnalysisJob.user_id == user.id)
        .order_by(AnalysisJob.created_at.desc())  # type: ignore[union-attr]
    ).all()
    return [_to_out(job) for job in jobs]


@router.post("/{job_id}/my-reading", response_model=JobOut)
def submit_reading(
    job_id: int,
    payload: ReadingRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> JobOut:
    """Step 2. The student's own interpretation, recorded before any AI output."""
    job = _owned(session, job_id, user)
    if job.student_finding:
        raise HTTPException(status_code=400, detail="Your reading is already recorded")
    if not payload.finding.strip():
        raise HTTPException(status_code=400, detail="Write your interpretation first")

    job.student_finding = payload.finding.strip()
    job.student_finding_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return _to_out(job)


@router.post("/{job_id}/analyze", response_model=JobOut)
def analyze(
    job_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> JobOut:
    """Step 3. Runs the model. Blocked until the student has committed a reading."""
    job = _owned(session, job_id, user)
    if not job.student_finding:
        raise HTTPException(
            status_code=409,
            detail=(
                "Record your own interpretation before the model runs. "
                "Seeing the AI first is what this exercise exists to prevent."
            ),
        )

    log_event(
        session,
        user_id=user.id,
        event_type=EventType.ANALYSIS_REQUESTED,
        resource_type="analysis_job",
        resource_id=job.id,
        meta={"modality": job.modality.value, "case_ref": job.case_ref},
    )

    engine = get_engine()
    result = engine.analyze(job.case_ref, job.modality)
    confidences = [f.confidence for f in result.findings]
    mean_confidence, uncertain, needs_review = evaluate_confidence(confidences)

    job.findings_json = json.dumps([f.to_dict() for f in result.findings])
    job.model_name = result.model_name
    job.model_version = result.model_version
    job.mean_confidence = mean_confidence
    job.uncertainty_flag = uncertain
    job.requires_review = needs_review
    job.status = AnalysisStatus.NEEDS_REVIEW if needs_review else AnalysisStatus.COMPLETE
    session.add(job)
    session.commit()
    session.refresh(job)

    top = result.findings[0] if result.findings else None
    log_event(
        session,
        user_id=user.id,
        event_type=EventType.ANALYSIS_RETURNED,
        risk_level=RiskLevel.HIGH if needs_review else RiskLevel.MEDIUM,
        ai_model=result.model_name,
        ai_version=result.model_version,
        ai_output_summary=f"{top.label} ({top.confidence})" if top else "no findings",
        confidence=mean_confidence,
        requires_review=needs_review,
        resource_type="analysis_job",
        resource_id=job.id,
        meta={
            "findings": [f.label for f in result.findings],
            "uncertainty_flag": uncertain,
            "threshold": settings.low_confidence_threshold,
        },
    )
    return _to_out(job, result.known_limitations)


@router.post("/{job_id}/decide", response_model=JobOut)
def decide(
    job_id: int,
    payload: DecisionRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> JobOut:
    """Step 4. The human's final call, and whether it departed from the model."""
    job = _owned(session, job_id, user)
    if job.status == AnalysisStatus.PENDING:
        raise HTTPException(status_code=409, detail="Run the analysis first")

    job.final_decision = payload.final_decision.strip()
    job.agreed_with_ai = payload.agreed_with_ai
    session.add(job)
    session.commit()
    session.refresh(job)

    log_event(
        session,
        user_id=user.id,
        event_type=(
            EventType.ANALYSIS_ACCEPTED if payload.agreed_with_ai else EventType.ANALYSIS_OVERRIDDEN
        ),
        risk_level=RiskLevel.MEDIUM,
        ai_model=job.model_name,
        ai_version=job.model_version,
        confidence=job.mean_confidence,
        human_decision=job.final_decision,
        overridden=not payload.agreed_with_ai,
        resource_type="analysis_job",
        resource_id=job.id,
    )
    return _to_out(job)
