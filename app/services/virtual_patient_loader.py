"""Load Virtual Patient scenarios from JSON and seed them.

Every case lives as one file in `app/data/virtual_patients/`. Adding a case is
adding a file — no Python changes, no UI changes — which is the whole point of
keeping the authoring format separate from the ORM.

A file is validated before anything touches the database, and a file that fails
validation is skipped with a warning rather than raised. One malformed scenario
must not take the Virtual Patient page down with it, and on a platform where a
half-seeded decision graph would silently mark students against branches that do
not exist, refusing to load is the safer failure.

Authoring format (`schema: 1`):

    {
      "schema": 1,
      "case":   { "slug": ..., "first_stage_key": ..., "opening_vitals": {...} },
      "stages": [ { "key": ..., "options": [ { "next_stage_key": ... } ] } ]
    }

Vitals are written as objects here and stored as JSON strings on the models, so
a case file stays readable and diffable.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

from sqlmodel import Session, select

from app.models.virtual_patient import (
    VirtualPatientCase,
    VirtualPatientOption,
    VirtualPatientStage,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "virtual_patients"

SUPPORTED_SCHEMA = 1

# Only fields the models actually define. Anything else in a file is ignored
# rather than passed to the ORM, so an authoring typo cannot raise at insert.
CASE_FIELDS = {
    "slug", "title", "summary", "specialty", "difficulty", "estimated_minutes",
    "patient_name", "patient_age", "patient_sex", "presenting_complaint",
    "patient_brief", "first_stage_key", "correct_diagnosis",
    "learning_objectives", "debrief_md", "pass_ratio", "icon", "cover",
    "order", "published",
}
STAGE_FIELDS = {
    "key", "kind", "title", "narrative", "patient_line", "clinical_note",
    "prompt", "is_terminal", "outcome",
}
OPTION_FIELDS = {
    "key", "label", "detail", "is_correct", "is_harmful", "score_delta",
    "next_stage_key", "feedback", "state_after",
}

REQUIRED_CASE = ("slug", "title", "first_stage_key")
REQUIRED_STAGE = ("key",)
REQUIRED_OPTION = ("key", "label")


class ScenarioError(ValueError):
    """A case file that cannot be trusted to drive a graded scenario."""


def _validate(doc: Dict[str, Any], source: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Return (case, stages) or raise ScenarioError naming what is wrong."""
    if not isinstance(doc, dict):
        raise ScenarioError(f"{source}: top level must be an object")

    schema = doc.get("schema", SUPPORTED_SCHEMA)
    if schema != SUPPORTED_SCHEMA:
        raise ScenarioError(f"{source}: unsupported schema {schema!r}")

    case = doc.get("case")
    stages = doc.get("stages")
    if not isinstance(case, dict) or not isinstance(stages, list) or not stages:
        raise ScenarioError(f"{source}: needs a 'case' object and a non-empty 'stages' list")

    for field in REQUIRED_CASE:
        if not case.get(field):
            raise ScenarioError(f"{source}: case is missing {field!r}")

    keys = set()
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            raise ScenarioError(f"{source}: stage {index} is not an object")
        for field in REQUIRED_STAGE:
            if not stage.get(field):
                raise ScenarioError(f"{source}: stage {index} is missing {field!r}")
        if stage["key"] in keys:
            raise ScenarioError(f"{source}: duplicate stage key {stage['key']!r}")
        keys.add(stage["key"])

    if case["first_stage_key"] not in keys:
        raise ScenarioError(
            f"{source}: first_stage_key {case['first_stage_key']!r} is not a stage"
        )

    # Every branch has to land somewhere, or a student reaches a dead end
    # mid-case with a score already recorded.
    for stage in stages:
        options = stage.get("options") or []
        if not options and not stage.get("is_terminal"):
            raise ScenarioError(
                f"{source}: stage {stage['key']!r} has no options and is not terminal"
            )
        for option in options:
            if not isinstance(option, dict):
                raise ScenarioError(f"{source}: an option in {stage['key']!r} is not an object")
            for field in REQUIRED_OPTION:
                if not option.get(field):
                    raise ScenarioError(
                        f"{source}: option in {stage['key']!r} is missing {field!r}"
                    )
            target = option.get("next_stage_key")
            if target and target not in keys:
                raise ScenarioError(
                    f"{source}: option {option['key']!r} in stage {stage['key']!r} "
                    f"points at unknown stage {target!r}"
                )
        if options and not any(o.get("is_correct") for o in options):
            raise ScenarioError(
                f"{source}: stage {stage['key']!r} has no correct option to mark against"
            )

    return case, stages


def _vitals(value: Any) -> str:
    """Accept an object, a pre-encoded string, or nothing."""
    if isinstance(value, str):
        return value or "{}"
    return json.dumps(value or {}, ensure_ascii=False)


def load_files() -> List[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    """Every valid scenario on disk, sorted by filename. Invalid files are skipped."""
    scenarios = []
    if not DATA_DIR.is_dir():
        logger.warning("virtual patient data directory missing: %s", DATA_DIR)
        return scenarios

    for path in sorted(DATA_DIR.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            scenarios.append(_validate(doc, path.name))
        except (json.JSONDecodeError, ScenarioError) as exc:
            # Skipped, never raised: one bad file must not empty the case list.
            logger.warning("skipping virtual patient scenario %s — %s", path.name, exc)
    return scenarios


def seed_cases(session: Session) -> int:
    """Insert every scenario that is not already present. Returns how many."""
    inserted = 0
    for order, (spec, stages) in enumerate(load_files()):
        slug = str(spec["slug"])
        if session.exec(
            select(VirtualPatientCase).where(VirtualPatientCase.slug == slug)
        ).first():
            continue

        fields = {k: v for k, v in spec.items() if k in CASE_FIELDS}
        fields.setdefault("order", order)
        case = VirtualPatientCase(
            **fields,
            opening_vitals_json=_vitals(spec.get("opening_vitals")),
        )
        session.add(case)
        session.commit()
        session.refresh(case)

        for stage_order, stage_spec in enumerate(stages):
            stage = VirtualPatientStage(
                case_id=case.id or 0,
                order=stage_order,
                vitals_json=_vitals(stage_spec.get("vitals")),
                **{k: v for k, v in stage_spec.items() if k in STAGE_FIELDS},
            )
            session.add(stage)
            session.commit()
            session.refresh(stage)

            for option_order, option in enumerate(stage_spec.get("options") or []):
                patch = option.get("vitals_patch", option.get("vitals_patch_json"))
                session.add(
                    VirtualPatientOption(
                        stage_id=stage.id or 0,
                        order=option_order,
                        vitals_patch_json=_vitals(patch) if patch else "",
                        **{k: v for k, v in option.items() if k in OPTION_FIELDS},
                    )
                )
            session.commit()
        inserted += 1
    return inserted
