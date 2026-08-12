"""Virtual Patient API.

Two rules these endpoints exist to enforce:

  * The server owns the run. Stage, score, patient condition and outcome are
    read from the engine, never accepted from the client, and a request that
    answers a stage the student is not on is refused rather than applied.
  * The answer key stays server-side. Options go out with a label and no
    verdict, so the correct choice is not sitting in the network tab.

Narration is best-effort. If Gemini is unavailable every endpoint still
returns a complete, playable stage using the authored text.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, select

from app.db import get_session
from app.models.enums import EventType, RiskLevel, SessionStatus
from app.models.user import User
from app.models.virtual_patient import VirtualPatientCase, VirtualPatientSession
from app.security import get_current_user
from app.services import virtual_patient_engine as engine
from app.services import virtual_patient_service as narration
from app.services.audit import log_event

logger = logging.getLogger("medly.virtual_patient")

router = APIRouter(prefix="/api/virtual-patient", tags=["virtual-patient"])

SIMULATION_DISCLAIMER = (
    "Simulated patient for education. This is not a real person and nothing "
    "here is medical advice or a diagnostic tool."
)


# --------------------------------------------------------------------------
# Wire models
# --------------------------------------------------------------------------

class CaseSummaryOut(BaseModel):
    slug: str
    title: str
    summary: str
    specialty: str
    difficulty: str
    estimated_minutes: int
    icon: str
    cover: str
    patient_name: str
    patient_age: int
    patient_sex: str
    presenting_complaint: str
    stage_count: int
    max_score: int
    # The caller's own in-progress run, if there is one.
    active_session_id: Optional[int] = None
    completed: bool = False


class OptionOut(BaseModel):
    key: str
    label: str
    detail: str


class StageOut(BaseModel):
    key: str
    kind: str
    title: str
    narrative: str
    patient_line: str
    clinical_note: str
    prompt: str
    is_terminal: bool
    outcome: str
    options: List[OptionOut]
    # True when `patient_line` was phrased by the model rather than read from
    # the case file. Handy in the UI, and honest.
    narrated: bool = False


class SessionOut(BaseModel):
    session_id: int
    case_slug: str
    status: str
    patient_state: str
    vitals: Dict[str, object]
    score: int
    max_score: int
    decisions_made: int
    passed: bool
    outcome: str
    stage: StageOut
    disclaimer: str = SIMULATION_DISCLAIMER
    started_at: datetime
    completed_at: Optional[datetime] = None


class DecisionIn(BaseModel):
    stage_key: str = PydanticField(min_length=1, max_length=120)
    option_key: str = PydanticField(min_length=1, max_length=120)


class DecisionOut(BaseModel):
    was_correct: bool
    was_harmful: bool
    score_delta: int
    feedback: str
    patient_state_before: str
    patient_state_after: str
    vitals: Dict[str, object]
    score: int
    max_score: int
    finished: bool
    outcome: str
    next_stage: StageOut
    disclaimer: str = SIMULATION_DISCLAIMER


class DecisionRecordOut(BaseModel):
    order: int
    stage_key: str
    option_label: str
    was_correct: bool
    was_harmful: bool
    score_delta: int
    feedback: str


class ResultOut(BaseModel):
    session_id: int
    case_slug: str
    case_title: str
    status: str
    outcome: str
    passed: bool
    score: int
    max_score: int
    patient_state: str
    correct_diagnosis: str
    learning_objectives: str
    debrief: str
    debrief_narrated: bool
    decisions: List[DecisionRecordOut]
    disclaimer: str = SIMULATION_DISCLAIMER


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _fail(exc: engine.EngineError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


def _stage_out(
    view: engine.StageView, *, patient_line: str, narrated: bool
) -> StageOut:
    return StageOut(
        key=view.key,
        kind=view.kind,
        title=view.title,
        narrative=view.narrative,
        patient_line=patient_line,
        clinical_note=view.clinical_note,
        prompt=view.prompt,
        is_terminal=view.is_terminal,
        outcome=view.outcome,
        options=[OptionOut(key=o.key, label=o.label, detail=o.detail) for o in view.options],
        narrated=narrated,
    )


def _narrate_stage(case: VirtualPatientCase, view: engine.StageView) -> StageOut:
    """Give the patient a voice, or use the authored line if we cannot."""
    if not view.patient_line:
        return _stage_out(view, patient_line="", narrated=False)

    spoken = narration.patient_says(
        case_brief=case.patient_brief,
        patient_name=case.patient_name,
        patient_age=case.patient_age,
        patient_sex=case.patient_sex,
        situation=f"{view.title}. {view.narrative}".strip(),
        authored_line=view.patient_line,
    )
    return _stage_out(view, patient_line=spoken.text, narrated=spoken.used_model)


def _session_out(
    db: Session, run: VirtualPatientSession, case: VirtualPatientCase, *, narrate: bool
) -> SessionOut:
    stage = engine.get_stage(db, case.id or 0, run.current_stage_key)
    view = engine.stage_view(db, stage)
    stage_out = (
        _narrate_stage(case, view)
        if narrate
        else _stage_out(view, patient_line=view.patient_line, narrated=False)
    )
    return SessionOut(
        session_id=run.id or 0,
        case_slug=case.slug,
        status=run.status,
        patient_state=run.patient_state,
        vitals=engine.parse_vitals(run.vitals_json),
        score=run.score,
        max_score=run.max_score,
        decisions_made=run.decisions_made,
        passed=run.passed,
        outcome=run.outcome,
        stage=stage_out,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

@router.get("/cases", response_model=List[CaseSummaryOut])
def list_cases(
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> List[CaseSummaryOut]:
    cases = db.exec(
        select(VirtualPatientCase)
        .where(VirtualPatientCase.published == True)  # noqa: E712
        .order_by(VirtualPatientCase.order)  # type: ignore[arg-type]
    ).all()

    out: List[CaseSummaryOut] = []
    for case in cases:
        runs = db.exec(
            select(VirtualPatientSession).where(
                VirtualPatientSession.case_id == case.id,
                VirtualPatientSession.user_id == user.id,
            )
        ).all()
        active = next(
            (r for r in runs if r.status == SessionStatus.IN_PROGRESS.value), None
        )
        out.append(
            CaseSummaryOut(
                slug=case.slug,
                title=case.title,
                summary=case.summary,
                specialty=case.specialty,
                difficulty=case.difficulty,
                estimated_minutes=case.estimated_minutes,
                icon=case.icon,
                cover=case.cover,
                patient_name=case.patient_name,
                patient_age=case.patient_age,
                patient_sex=case.patient_sex,
                presenting_complaint=case.presenting_complaint,
                stage_count=len(engine.stages_for(db, case.id or 0)),
                max_score=engine.max_score_for(db, case.id or 0),
                active_session_id=active.id if active else None,
                completed=any(
                    r.status == SessionStatus.COMPLETED.value for r in runs
                ),
            )
        )
    return out


@router.get("/cases/{slug}", response_model=CaseSummaryOut)
def get_case(
    slug: str,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CaseSummaryOut:
    try:
        case = engine.get_case(db, slug)
    except engine.EngineError as exc:
        raise _fail(exc) from exc

    runs = db.exec(
        select(VirtualPatientSession).where(
            VirtualPatientSession.case_id == case.id,
            VirtualPatientSession.user_id == user.id,
        )
    ).all()
    active = next((r for r in runs if r.status == SessionStatus.IN_PROGRESS.value), None)
    return CaseSummaryOut(
        slug=case.slug,
        title=case.title,
        summary=case.summary,
        specialty=case.specialty,
        difficulty=case.difficulty,
        estimated_minutes=case.estimated_minutes,
        icon=case.icon,
        cover=case.cover,
        patient_name=case.patient_name,
        patient_age=case.patient_age,
        patient_sex=case.patient_sex,
        presenting_complaint=case.presenting_complaint,
        stage_count=len(engine.stages_for(db, case.id or 0)),
        max_score=engine.max_score_for(db, case.id or 0),
        active_session_id=active.id if active else None,
        completed=any(r.status == SessionStatus.COMPLETED.value for r in runs),
    )


@router.post("/cases/{slug}/start", response_model=SessionOut)
def start(
    slug: str,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SessionOut:
    """Open a run, or hand back the one already in progress."""
    try:
        case = engine.get_case(db, slug)
        run = engine.start_session(db, case, user.id or 0)
    except engine.EngineError as exc:
        raise _fail(exc) from exc

    log_event(
        db,
        user_id=user.id,
        event_type=EventType.VP_SESSION_STARTED,
        risk_level=RiskLevel.NONE,
        ai_model="virtual-patient-engine",
        ai_version="1.0",
        ai_output_summary=f"Started {case.slug}",
        session_id=str(run.id),
        meta={"case": case.slug},
    )
    return _session_out(db, run, case, narrate=True)


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session_state(
    session_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SessionOut:
    """Where the run stands. Re-reads state; does not re-narrate."""
    try:
        run = engine.owned_session(db, session_id, user.id or 0)
    except engine.EngineError as exc:
        raise _fail(exc) from exc
    case = db.get(VirtualPatientCase, run.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="That case does not exist.")
    return _session_out(db, run, case, narrate=False)


@router.post("/sessions/{session_id}/decision", response_model=DecisionOut)
def submit_decision(
    session_id: int,
    payload: DecisionIn,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> DecisionOut:
    """Play one move. Every consequence is computed by the engine."""
    try:
        run = engine.owned_session(db, session_id, user.id or 0)
        case = db.get(VirtualPatientCase, run.case_id)
        if not case:
            raise HTTPException(status_code=404, detail="That case does not exist.")
        result = engine.submit_decision(
            db, run, case, payload.stage_key, payload.option_key
        )
    except engine.EngineError as exc:
        raise _fail(exc) from exc

    log_event(
        db,
        user_id=user.id,
        event_type=EventType.VP_DECISION_MADE,
        risk_level=RiskLevel.NONE,
        ai_model="virtual-patient-engine",
        ai_version="1.0",
        ai_output_summary=f"{payload.stage_key}:{payload.option_key}",
        session_id=str(run.id),
        meta={
            "case": case.slug,
            "correct": result.was_correct,
            "harmful": result.was_harmful,
            "state": result.state_after.value,
        },
    )
    if result.finished:
        log_event(
            db,
            user_id=user.id,
            event_type=EventType.VP_SESSION_COMPLETED,
            risk_level=RiskLevel.NONE,
            ai_model="virtual-patient-engine",
            ai_version="1.0",
            ai_output_summary=f"{case.slug} -> {run.outcome}",
            session_id=str(run.id),
            meta={"case": case.slug, "passed": run.passed, "score": run.score},
        )

    next_view = result.next_stage
    assert next_view is not None  # the engine always returns a stage
    stage_out = _narrate_stage(case, next_view)

    return DecisionOut(
        was_correct=result.was_correct,
        was_harmful=result.was_harmful,
        score_delta=result.score_delta,
        feedback=result.feedback,
        patient_state_before=result.state_before.value,
        patient_state_after=result.state_after.value,
        vitals=result.vitals,
        score=run.score,
        max_score=run.max_score,
        finished=result.finished,
        outcome=result.outcome,
        next_stage=stage_out,
    )


@router.post("/sessions/{session_id}/abandon", response_model=SessionOut)
def abandon(
    session_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SessionOut:
    try:
        run = engine.owned_session(db, session_id, user.id or 0)
    except engine.EngineError as exc:
        raise _fail(exc) from exc
    case = db.get(VirtualPatientCase, run.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="That case does not exist.")
    run = engine.abandon(db, run)
    return _session_out(db, run, case, narrate=False)


@router.get("/sessions/{session_id}/result", response_model=ResultOut)
def get_result(
    session_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ResultOut:
    """The debrief. Available only once the run has actually ended."""
    try:
        run = engine.owned_session(db, session_id, user.id or 0)
    except engine.EngineError as exc:
        raise _fail(exc) from exc

    if run.status == SessionStatus.IN_PROGRESS.value:
        raise HTTPException(
            status_code=409, detail="This case is still in progress."
        )

    case = db.get(VirtualPatientCase, run.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="That case does not exist.")

    records = engine.decisions_for(db, run.id or 0)
    written = narration.debrief(
        case_title=case.title,
        correct_diagnosis=case.correct_diagnosis,
        learning_objectives=case.learning_objectives,
        authored_debrief=case.debrief_md,
        outcome=run.outcome,
        score=run.score,
        max_score=run.max_score,
        passed=run.passed,
        decisions=[
            {
                "stage_key": d.stage_key,
                "option_label": d.option_label,
                "was_correct": d.was_correct,
                "was_harmful": d.was_harmful,
                "feedback": d.feedback,
            }
            for d in records
        ],
    )

    return ResultOut(
        session_id=run.id or 0,
        case_slug=case.slug,
        case_title=case.title,
        status=run.status,
        outcome=run.outcome,
        passed=run.passed,
        score=run.score,
        max_score=run.max_score,
        patient_state=run.patient_state,
        correct_diagnosis=case.correct_diagnosis,
        learning_objectives=case.learning_objectives,
        debrief=written.text,
        debrief_narrated=written.used_model,
        decisions=[
            DecisionRecordOut(
                order=d.order,
                stage_key=d.stage_key,
                option_label=d.option_label,
                was_correct=d.was_correct,
                was_harmful=d.was_harmful,
                score_delta=d.score_delta,
                feedback=d.feedback,
            )
            for d in records
        ],
    )
