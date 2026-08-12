"""Virtual Patient: an authored clinical simulation.

The shape here is the whole safety argument for the feature. A case is a
directed graph of stages that an author writes; every option carries its own
verdict, its own score, its own effect on the patient, and the key of the
stage it leads to. Nothing about correctness is computed at runtime and
nothing is asked of a language model.

    VirtualPatientCase
      └── VirtualPatientStage        (nodes: intro, history, decision, outcome…)
            └── VirtualPatientOption (edges: verdict, effect, next stage)

    VirtualPatientSession            (one student's run through a case)
      └── VirtualPatientDecision     (an audit row per choice made)

JSON is stored as text in a `*_json` column, matching `CaseImage.redacted_
fields_json` elsewhere in this codebase, so the schema stays portable across
SQLite, Postgres and MySQL without a dialect-specific JSON type.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class VirtualPatientCase(SQLModel, table=True):
    __tablename__ = "virtual_patient_cases"

    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    title: str
    summary: str = Field(default="")
    specialty: str = Field(default="", index=True)
    difficulty: str = Field(default="medium")  # easy | medium | hard
    estimated_minutes: int = Field(default=10)

    # Who the student is about to meet.
    patient_name: str = Field(default="")
    patient_age: int = Field(default=0)
    patient_sex: str = Field(default="")
    presenting_complaint: str = Field(default="")
    # Everything the patient knows about themselves. The language model may
    # speak from this and from nothing else.
    patient_brief: str = Field(default="")

    opening_vitals_json: str = Field(default="{}")
    first_stage_key: str = Field(default="intro")

    # Revealed only in the debrief.
    correct_diagnosis: str = Field(default="")
    learning_objectives: str = Field(default="")
    debrief_md: str = Field(default="")

    # --- translations -----------------------------------------------------
    # Same convention as Article, Community and Challenge: the English column
    # is canonical, the siblings start empty and are filled on first view in
    # that language by localize.ensure_fields, then cached forever. Adding a
    # case in any way — seed, import, a future generator — needs no work here.
    #
    # `specialty` and `difficulty` are deliberately absent: they are closed
    # vocabularies rendered from i18n keys on the client, not free text.
    title_ru: str = Field(default="")
    title_uz: str = Field(default="")
    summary_ru: str = Field(default="")
    summary_uz: str = Field(default="")
    presenting_complaint_ru: str = Field(default="")
    presenting_complaint_uz: str = Field(default="")
    patient_brief_ru: str = Field(default="")
    patient_brief_uz: str = Field(default="")
    correct_diagnosis_ru: str = Field(default="")
    correct_diagnosis_uz: str = Field(default="")
    learning_objectives_ru: str = Field(default="")
    learning_objectives_uz: str = Field(default="")
    debrief_md_ru: str = Field(default="")
    debrief_md_uz: str = Field(default="")

    # A run at or above this fraction of the available score passes.
    pass_ratio: float = Field(default=0.6)

    icon: str = Field(default="stethoscope")
    cover: str = Field(default="")

    # Optional stock photograph for the scenario, cached exactly as an article's
    # is. Nothing populates these automatically: the authored Lottie art and the
    # drawn avatar remain the default, because a stock photo of a stranger
    # standing in for a named patient is a worse illustration, not a better one.
    # `app.services.stock_images.get_stock_image` fills them when asked.
    image_provider: str = Field(default="")
    image_provider_id: str = Field(default="")
    image_url: str = Field(default="")
    image_source_url: str = Field(default="")
    image_photographer: str = Field(default="")
    image_photographer_url: str = Field(default="")
    image_width: int = Field(default=0)
    image_height: int = Field(default=0)
    image_orientation: str = Field(default="")
    image_alt: str = Field(default="")
    order: int = Field(default=0)
    published: bool = Field(default=True)
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class VirtualPatientStage(SQLModel, table=True):
    """One node. `key` is the author-facing identifier options point at."""

    __tablename__ = "virtual_patient_stages"

    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: int = Field(foreign_key="virtual_patient_cases.id", index=True)
    key: str = Field(index=True)
    order: int = Field(default=0)

    # intro | history | examination | investigation | decision | diagnosis
    # | treatment | outcome
    kind: str = Field(default="decision")
    title: str = Field(default="")
    # What the simulation tells the student at this point.
    narrative: str = Field(default="")
    # What the patient says, in their own words. Used verbatim when the
    # language model is unavailable, and as the brief for it when it is.
    patient_line: str = Field(default="")
    # Clinical data unlocked by arriving here, e.g. a result. Free text.
    clinical_note: str = Field(default="")
    # Absolute vitals for this stage, if the stage sets them outright.
    vitals_json: str = Field(default="{}")

    prompt: str = Field(default="")  # the question put to the student
    # Terminal stages end the run. `outcome` is the authored ending.
    is_terminal: bool = Field(default=False)
    outcome: str = Field(default="")  # good | acceptable | poor

    # --- translations -----------------------------------------------------
    # `patient_line` is translated too, even though Gemini usually rephrases
    # it live: the translation is what a student sees when the model is down,
    # and an English fallback line inside a Russian case is exactly the mixed
    # output this is meant to remove.
    title_ru: str = Field(default="")
    title_uz: str = Field(default="")
    narrative_ru: str = Field(default="")
    narrative_uz: str = Field(default="")
    patient_line_ru: str = Field(default="")
    patient_line_uz: str = Field(default="")
    clinical_note_ru: str = Field(default="")
    clinical_note_uz: str = Field(default="")
    prompt_ru: str = Field(default="")
    prompt_uz: str = Field(default="")


class VirtualPatientOption(SQLModel, table=True):
    """One edge. Carries the verdict — the model never supplies it."""

    __tablename__ = "virtual_patient_options"

    id: Optional[int] = Field(default=None, primary_key=True)
    stage_id: int = Field(foreign_key="virtual_patient_stages.id", index=True)
    key: str = Field(index=True)
    order: int = Field(default=0)

    label: str
    detail: str = Field(default="")

    is_correct: bool = Field(default=False)
    # Not the same as "not correct": a harmful choice is one that actively
    # hurts the patient, and it is what drives deterioration.
    is_harmful: bool = Field(default=False)
    score_delta: int = Field(default=0)

    # Empty means "leave the patient as they are". Otherwise a PatientState.
    state_after: str = Field(default="")
    # Partial vitals update merged over the running set, e.g. {"hr": 130}.
    vitals_patch_json: str = Field(default="{}")

    next_stage_key: str = Field(default="")
    # Authored teaching point, shown immediately after the choice.
    feedback: str = Field(default="")

    # --- translations -----------------------------------------------------
    label_ru: str = Field(default="")
    label_uz: str = Field(default="")
    detail_ru: str = Field(default="")
    detail_uz: str = Field(default="")
    feedback_ru: str = Field(default="")
    feedback_uz: str = Field(default="")


class VirtualPatientSession(SQLModel, table=True):
    """One student's run. The server's record of truth for that run."""

    __tablename__ = "virtual_patient_sessions"

    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: int = Field(foreign_key="virtual_patient_cases.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)

    current_stage_key: str = Field(default="")
    patient_state: str = Field(default="stable")
    vitals_json: str = Field(default="{}")

    score: int = Field(default=0)
    max_score: int = Field(default=0)
    decisions_made: int = Field(default=0)
    harmful_choices: int = Field(default=0)

    # in_progress | completed | failed | abandoned
    status: str = Field(default="in_progress", index=True)
    outcome: str = Field(default="")
    passed: bool = Field(default=False)

    started_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class VirtualPatientDecision(SQLModel, table=True):
    """An immutable record of one choice, for the debrief and for review."""

    __tablename__ = "virtual_patient_decisions"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="virtual_patient_sessions.id", index=True)
    order: int = Field(default=0)

    stage_key: str = Field(default="")
    option_key: str = Field(default="")
    option_label: str = Field(default="")

    was_correct: bool = Field(default=False)
    was_harmful: bool = Field(default=False)
    score_delta: int = Field(default=0)
    state_before: str = Field(default="")
    state_after: str = Field(default="")
    feedback: str = Field(default="")

    created_at: datetime = Field(default_factory=datetime.utcnow)
