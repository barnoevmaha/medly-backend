"""De-identification of imaging metadata, with a human in the loop.

The production shape of this is: a hospital scan arrives with DICOM headers and,
often, text burned into the pixels. Both carry identity. This module strips what
it can name and flags what it cannot, and it deliberately never marks its own
work as finished — `verify_anonymization` in the casebook router is the only
thing that can, and only a teacher may call it.

Treating an automated pass as proof would be the exact failure this platform
teaches students to avoid: trusting a model's output because it is confident.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

# DICOM tags that carry identity directly. Removed outright.
DIRECT_IDENTIFIERS = [
    "PatientName",
    "PatientID",
    "PatientBirthDate",
    "OtherPatientIDs",
    "OtherPatientNames",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "PatientMotherBirthName",
    "ReferringPhysicianName",
    "PerformingPhysicianName",
    "OperatorsName",
    "InstitutionName",
    "InstitutionAddress",
    "AccessionNumber",
    "StudyID",
    "IssuerOfPatientID",
]

# Kept in a coarsened form: useful teaching context, not an identifier.
COARSENED = {
    "PatientAge": "age band",
    "PatientSex": "sex",
    "StudyDate": "year only",
    "BodyPartExamined": "unchanged",
    "Modality": "unchanged",
}

# Things a text pass cannot be trusted to settle on its own.
RESIDUAL_RISKS = [
    "burned-in pixel text (corner annotations, scanner overlays)",
    "face-identifiable 3D reconstructions on head CT",
    "unique implants, hardware or rare anatomy",
    "free-text notes inside private DICOM tags",
]

_NAME_LIKE = re.compile(r"\b([A-Z][a-z]+),?\s+([A-Z][a-z]+)\b")
_DATE_LIKE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{8})\b")
_MRN_LIKE = re.compile(r"\b(MRN|NHS|ID)[:\s#]*([A-Z0-9-]{5,})\b", re.IGNORECASE)


def scrub_text(text: str) -> Tuple[str, List[str]]:
    """Redact identifier-shaped substrings from free text, e.g. an overlay.

    Returns the redacted text and a list of what was hit. Pattern matching is a
    filter, not a guarantee — anything it touches raises the review bar rather
    than lowering it.
    """
    found: List[str] = []
    cleaned = text

    if _MRN_LIKE.search(cleaned):
        found.append("record number in overlay text")
        cleaned = _MRN_LIKE.sub("[REDACTED-ID]", cleaned)
    if _DATE_LIKE.search(cleaned):
        found.append("date in overlay text")
        cleaned = _DATE_LIKE.sub("[REDACTED-DATE]", cleaned)
    if _NAME_LIKE.search(cleaned):
        found.append("name-shaped text in overlay")
        cleaned = _NAME_LIKE.sub("[REDACTED-NAME]", cleaned)

    return cleaned, found


def anonymize(metadata: Dict[str, str], overlay_text: str = "") -> Dict[str, object]:
    """Run the automatic pass.

    The result is a *proposal*: `status` is `auto_redacted`, never `verified`.
    """
    removed: List[str] = []
    kept: Dict[str, str] = {}

    for key, value in (metadata or {}).items():
        if key in DIRECT_IDENTIFIERS:
            removed.append(key)
            continue
        if key == "PatientAge":
            kept[key] = _age_band(str(value))
            continue
        if key == "StudyDate":
            kept[key] = str(value)[:4] if str(value)[:4].isdigit() else ""
            continue
        kept[key] = str(value)

    cleaned_overlay, overlay_hits = scrub_text(overlay_text or "")
    removed.extend(overlay_hits)

    notes = [
        "Automatic redaction is a first pass only — a teacher must confirm "
        "before any student sees this image.",
    ]
    if overlay_hits:
        notes.append(
            "Identifier-shaped text was found burned into the image and masked. "
            "Check the rendered image, not just the metadata."
        )

    return {
        "status": "auto_redacted",
        "removed_fields": removed,
        "kept_fields": kept,
        "overlay_text": cleaned_overlay,
        "residual_risks": RESIDUAL_RISKS,
        "notes": " ".join(notes),
    }


def _age_band(raw: str) -> str:
    digits = "".join(character for character in raw if character.isdigit())
    if not digits:
        return "unknown"
    age = int(digits[:3])
    if age < 18:
        return "under 18"
    lower = (age // 10) * 10
    return f"{lower}-{lower + 9}"
