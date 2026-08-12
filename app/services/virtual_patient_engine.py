"""Virtual Patient game engine.

Every clinically meaningful decision in a simulation is made here, from data
an author wrote, with no network call and no language model. Given the same
case and the same choices this produces the same result on every run.

That separation is the point of the feature. A model asked "was this the right
management?" will answer confidently and sometimes wrongly, and a student
being marked by it would have no way to tell the difference. So correctness,
scoring, the patient's condition, the vitals and the ending all come from the
authored graph; the model is only ever asked to phrase things.

The engine is pure with respect to the database: it reads rows, returns
plain results, and leaves persistence to the router.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from sqlmodel import Session, select

from app.models.enums import PatientState, SessionStatus
from app.models.virtual_patient import (
    VirtualPatientCase,
    VirtualPatientDecision,
    VirtualPatientOption,
    VirtualPatientSession,
    VirtualPatientStage,
)


class EngineError(Exception):
    """A move the rules do not allow. Carries a message safe to show."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# --------------------------------------------------------------------------
# Patient condition
# --------------------------------------------------------------------------

# Where an unmanaged patient drifts if the student keeps getting it wrong.
# Only ever applied when the chosen option is harmful and does not name a
# state of its own, so an author can always override the default.
DETERIORATION: Dict[PatientState, PatientState] = {
    PatientState.IMPROVING: PatientState.STABLE,
    PatientState.STABLE: PatientState.DETERIORATING,
    PatientState.DETERIORATING: PatientState.CRITICAL,
    PatientState.CRITICAL: PatientState.FAILED,
}

# Harmful choices also push the observations in a recognisable direction, so
# the numbers on screen agree with the word describing the patient.
DETERIORATION_VITALS: Dict[str, int] = {"hr": 12, "rr": 4, "spo2": -3}


def parse_vitals(raw: str) -> Dict[str, object]:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def dump_vitals(vitals: Dict[str, object]) -> str:
    return json.dumps(vitals, ensure_ascii=False)


def _apply_drift(vitals: Dict[str, object]) -> Dict[str, object]:
    """Nudge numeric observations the wrong way, within survivable bounds."""
    updated = dict(vitals)
    for key, delta in DETERIORATION_VITALS.items():
        current = updated.get(key)
        if isinstance(current, (int, float)):
            value = current + delta
            if key == "spo2":
                value = max(70, min(100, value))
            if key in ("hr", "rr"):
                value = max(0, value)
            updated[key] = value
    return updated


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------

@dataclass
class OptionView:
    key: str
    label: str
    detail: str


@dataclass
class StageView:
    key: str
    kind: str
    title: str
    narrative: str
    patient_line: str
    clinical_note: str
    prompt: str
    is_terminal: bool
    outcome: str
    options: List[OptionView] = field(default_factory=list)


@dataclass
class DecisionResult:
    was_correct: bool
    was_harmful: bool
    score_delta: int
    feedback: str
    state_before: PatientState
    state_after: PatientState
    vitals: Dict[str, object]
    next_stage: Optional[StageView]
    finished: bool
    outcome: str


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def get_case(session: Session, slug: str) -> VirtualPatientCase:
    case = session.exec(
        select(VirtualPatientCase).where(VirtualPatientCase.slug == slug)
    ).first()
    if not case or not case.published:
        raise EngineError("That case does not exist.", 404)
    return case


def stages_for(session: Session, case_id: int) -> List[VirtualPatientStage]:
    return list(
        session.exec(
            select(VirtualPatientStage)
            .where(VirtualPatientStage.case_id == case_id)
            .order_by(VirtualPatientStage.order)  # type: ignore[arg-type]
        ).all()
    )


def get_stage(session: Session, case_id: int, key: str) -> VirtualPatientStage:
    stage = session.exec(
        select(VirtualPatientStage).where(
            VirtualPatientStage.case_id == case_id,
            VirtualPatientStage.key == key,
        )
    ).first()
    if not stage:
        raise EngineError("That step is not part of this case.", 404)
    return stage


def options_for(session: Session, stage_id: int) -> List[VirtualPatientOption]:
    return list(
        session.exec(
            select(VirtualPatientOption)
            .where(VirtualPatientOption.stage_id == stage_id)
            .order_by(VirtualPatientOption.order)  # type: ignore[arg-type]
        ).all()
    )


def stage_view(session: Session, stage: VirtualPatientStage, lang: str = "en") -> StageView:
    """The student-facing shape of a stage, in `lang`.

    `localize.read` is a plain attribute lookup with an English fallback — no
    network, no model, nothing that could fail or take time. Translation is
    filled in beforehand by the router; this only chooses which column to
    read, which keeps the engine as deterministic as it was.
    """
    from app.services import localize

    return StageView(
        key=stage.key,
        kind=stage.kind,
        title=localize.read(stage, "title", lang),
        narrative=localize.read(stage, "narrative", lang),
        patient_line=localize.read(stage, "patient_line", lang),
        clinical_note=localize.read(stage, "clinical_note", lang),
        prompt=localize.read(stage, "prompt", lang),
        is_terminal=stage.is_terminal,
        outcome=stage.outcome,
        options=[
            # `is_correct` is deliberately absent: the answer key never
            # crosses the wire before the student has chosen.
            OptionView(
                key=o.key,
                label=localize.read(o, "label", lang),
                detail=localize.read(o, "detail", lang),
            )
            for o in options_for(session, stage.id or 0)
        ],
    )


def max_score_for(session: Session, case_id: int) -> int:
    """The best reachable total: the highest-scoring option at every stage."""
    total = 0
    for stage in stages_for(session, case_id):
        deltas = [o.score_delta for o in options_for(session, stage.id or 0)]
        if deltas:
            total += max(deltas)
    return total


# --------------------------------------------------------------------------
# Session lifecycle
# --------------------------------------------------------------------------

def start_session(
    session: Session, case: VirtualPatientCase, user_id: int
) -> VirtualPatientSession:
    """Open a run. An unfinished run for the same case is resumed, not cloned."""
    existing = session.exec(
        select(VirtualPatientSession).where(
            VirtualPatientSession.case_id == case.id,
            VirtualPatientSession.user_id == user_id,
            VirtualPatientSession.status == SessionStatus.IN_PROGRESS.value,
        )
    ).first()
    if existing:
        return existing

    run = VirtualPatientSession(
        case_id=case.id or 0,
        user_id=user_id,
        current_stage_key=case.first_stage_key,
        patient_state=PatientState.STABLE.value,
        vitals_json=case.opening_vitals_json or "{}",
        score=0,
        max_score=max_score_for(session, case.id or 0),
        status=SessionStatus.IN_PROGRESS.value,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def owned_session(
    session: Session, session_id: int, user_id: int
) -> VirtualPatientSession:
    """Load a run, refusing anyone else's. Not-found and not-yours look alike."""
    run = session.get(VirtualPatientSession, session_id)
    if not run or run.user_id != user_id:
        raise EngineError("That session does not exist.", 404)
    return run


def submit_decision(
    session: Session,
    run: VirtualPatientSession,
    case: VirtualPatientCase,
    stage_key: str,
    option_key: str,
    lang: str = "en",
) -> DecisionResult:
    """Apply one choice. Every consequence below is authored, not inferred."""
    if run.status != SessionStatus.IN_PROGRESS.value:
        raise EngineError("This case is already finished.", 409)

    # Answering a stage you are not on would let a client skip ahead.
    if stage_key != run.current_stage_key:
        raise EngineError(
            f"You are at '{run.current_stage_key}', not '{stage_key}'.", 409
        )

    stage = get_stage(session, case.id or 0, stage_key)
    if stage.is_terminal:
        raise EngineError("This step has no decision to make.", 409)

    options = options_for(session, stage.id or 0)
    if not options:
        raise EngineError("This step has no decision to make.", 409)

    chosen = next((o for o in options if o.key == option_key), None)
    if chosen is None:
        raise EngineError("That is not one of the available choices.", 400)

    state_before = PatientState(run.patient_state)

    # ---- condition ------------------------------------------------------
    if chosen.state_after:
        state_after = PatientState(chosen.state_after)
    elif chosen.is_harmful:
        state_after = DETERIORATION.get(state_before, PatientState.CRITICAL)
    else:
        state_after = state_before

    # ---- observations ---------------------------------------------------
    vitals = parse_vitals(run.vitals_json)
    patch = parse_vitals(chosen.vitals_patch_json)
    if patch:
        vitals.update(patch)
    elif chosen.is_harmful:
        vitals = _apply_drift(vitals)

    # ---- score ----------------------------------------------------------
    run.score = max(0, run.score + chosen.score_delta)
    run.decisions_made += 1
    if chosen.is_harmful:
        run.harmful_choices += 1

    # ---- where next -----------------------------------------------------
    next_key = chosen.next_stage_key or stage.key
    next_stage = get_stage(session, case.id or 0, next_key)

    # A patient who has died ends the run wherever the graph pointed.
    finished = next_stage.is_terminal or state_after is PatientState.FAILED
    outcome = next_stage.outcome if next_stage.is_terminal else ""

    if state_after is PatientState.FAILED:
        outcome = outcome or "poor"

    # Arriving at a stage that sets vitals outright overrides the patch.
    stage_vitals = parse_vitals(next_stage.vitals_json)
    if stage_vitals:
        vitals.update(stage_vitals)

    run.patient_state = state_after.value
    run.vitals_json = dump_vitals(vitals)
    run.current_stage_key = next_stage.key
    run.updated_at = datetime.utcnow()

    if finished:
        run.status = (
            SessionStatus.FAILED.value
            if state_after is PatientState.FAILED
            else SessionStatus.COMPLETED.value
        )
        run.outcome = outcome
        run.completed_at = datetime.utcnow()
        run.passed = (
            state_after is not PatientState.FAILED
            and run.max_score > 0
            and run.score / run.max_score >= case.pass_ratio
        )

    session.add(
        VirtualPatientDecision(
            session_id=run.id or 0,
            order=run.decisions_made,
            stage_key=stage_key,
            option_key=chosen.key,
            option_label=chosen.label,
            was_correct=chosen.is_correct,
            was_harmful=chosen.is_harmful,
            score_delta=chosen.score_delta,
            state_before=state_before.value,
            state_after=state_after.value,
            feedback=chosen.feedback,
        )
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    from app.services import localize

    return DecisionResult(
        was_correct=chosen.is_correct,
        was_harmful=chosen.is_harmful,
        score_delta=chosen.score_delta,
        # The verdict is the engine's; only the wording of the teaching point
        # follows the reader's language.
        feedback=localize.read(chosen, "feedback", lang),
        state_before=state_before,
        state_after=state_after,
        vitals=vitals,
        next_stage=stage_view(session, next_stage, lang),
        finished=finished,
        outcome=run.outcome,
    )


def decisions_for(session: Session, session_id: int) -> List[VirtualPatientDecision]:
    return list(
        session.exec(
            select(VirtualPatientDecision)
            .where(VirtualPatientDecision.session_id == session_id)
            .order_by(VirtualPatientDecision.order)  # type: ignore[arg-type]
        ).all()
    )


def abandon(session: Session, run: VirtualPatientSession) -> VirtualPatientSession:
    if run.status == SessionStatus.IN_PROGRESS.value:
        run.status = SessionStatus.ABANDONED.value
        run.completed_at = datetime.utcnow()
        run.updated_at = datetime.utcnow()
        session.add(run)
        session.commit()
        session.refresh(run)
    return run
