"""The guardrail layer.

This module is the product. The hackathon premise is that AI is already being
used on X-ray and CT without agreed safety standards; this file encodes those
standards as executable rules rather than a PDF nobody reads.

Five rules, applied to every AI interaction:

  1. Scope    - the assistant teaches, it does not diagnose real patients.
  2. Identify - anything that looks like patient identifiers is refused.
  3. Caveat   - every output carries a disclaimer, always, with no opt-out.
  4. Confidence - low-confidence model output is flagged, never shown bare.
  5. Trace   - every interaction is written to the audit log.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from app.config import settings
from app.models.enums import RiskLevel

# --------------------------------------------------------------------------
# Rule 1 & 2 - patterns that must never be answered by a teaching assistant.
# --------------------------------------------------------------------------

# Asking the tool to make the call on a real, present patient.
CLINICAL_DIRECTIVE_PATTERNS: List[Tuple[str, str]] = [
    (r"\b(?:my|our|this|the)\s+patient\b", "Request concerns a real patient"),
    (r"\bshould\s+(?:i|we)\s+(?:prescribe|administer|give|start|stop|discharge|operate)\b",
     "Request asks for a treatment decision"),
    (r"\b(?:what|which)\s+(?:dose|dosage)\b", "Request asks for a dosing decision"),
    (r"\bis\s+(?:it|this)\s+(?:cancer|malignant|benign|a\s+tumou?r)\b",
     "Request asks for a definitive diagnosis"),
    (r"\bdiagnos(?:e|is)\s+(?:this|my|the)\s+(?:patient|scan|x-?ray|ct)\b",
     "Request asks for a definitive diagnosis"),
    (r"\bcan\s+(?:i|we)\s+discharge\b", "Request asks for a disposition decision"),
]

# Protected identifiers that should never reach an AI service.
PHI_PATTERNS: List[Tuple[str, str]] = [
    (r"\b\d{3}-\d{2}-\d{4}\b", "Looks like a social security number"),
    (r"\bMRN[:\s#]*\d+\b", "Contains a medical record number"),
    (r"\b\d{2}[/-]\d{2}[/-]\d{4}\b", "Contains a date of birth"),
    (r"\b[\w.+-]+@[\w-]+\.[\w.]+\b", "Contains an email address"),
    (r"\b(?:\+?\d[\d\s().-]{8,}\d)\b", "Contains what may be a phone number"),
]

# Topics that are fine to teach but warrant a heightened caveat.
ELEVATED_TOPIC_PATTERNS: List[str] = [
    r"\bx-?ray\b", r"\bct\b", r"\bmri\b", r"\bradiograph\b", r"\bscan\b",
    r"\bpneumonia\b", r"\bnodule\b", r"\bfracture\b", r"\beffusion\b",
    r"\bmalignan\w*\b", r"\bdifferential\b",
]


@dataclass
class SafetyVerdict:
    """The result of running a message past the guardrails."""

    allowed: bool
    risk_level: RiskLevel
    reasons: List[str] = field(default_factory=list)
    redacted_text: str = ""
    refusal_message: Optional[str] = None

    @property
    def blocked(self) -> bool:
        return not self.allowed


def _matches(text: str, patterns: List[Tuple[str, str]]) -> List[str]:
    found: List[str] = []
    for pattern, label in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            found.append(label)
    return found


def redact(text: str) -> str:
    """Strip anything identifier-shaped before it is stored or forwarded."""
    cleaned = text
    for pattern, _ in PHI_PATTERNS:
        cleaned = re.sub(pattern, "[redacted]", cleaned, flags=re.IGNORECASE)
    return cleaned


def classify_risk(text: str) -> RiskLevel:
    """How much harm could a wrong answer to this do?"""
    if _matches(text, CLINICAL_DIRECTIVE_PATTERNS) or _matches(text, PHI_PATTERNS):
        return RiskLevel.HIGH
    for pattern in ELEVATED_TOPIC_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return RiskLevel.MEDIUM
    if text.strip():
        return RiskLevel.LOW
    return RiskLevel.NONE


def screen_message(text: str) -> SafetyVerdict:
    """Rules 1 and 2. Run before anything is sent to a model."""
    phi = _matches(text, PHI_PATTERNS)
    clinical = _matches(text, CLINICAL_DIRECTIVE_PATTERNS)
    risk = classify_risk(text)

    if phi:
        return SafetyVerdict(
            allowed=False,
            risk_level=RiskLevel.HIGH,
            reasons=phi,
            redacted_text=redact(text),
            refusal_message=(
                "That message looks like it contains patient identifiers, so I have not "
                "processed it. Identifiable data must never be sent to an AI service. "
                "Rewrite the question with the details removed and I will help."
            ),
        )

    if clinical:
        return SafetyVerdict(
            allowed=False,
            risk_level=RiskLevel.HIGH,
            reasons=clinical,
            redacted_text=redact(text),
            refusal_message=(
                "I am a teaching assistant, not a clinical decision tool, so I will not "
                "answer that as asked. I can explain the reasoning, the evidence, or how "
                "a clinician would work through it. Ask me the concept and I will teach it."
            ),
        )

    return SafetyVerdict(
        allowed=True,
        risk_level=risk,
        reasons=[],
        redacted_text=redact(text),
    )


# The caveat that goes under every AI answer, authored per locale. Ending a
# Russian answer with an English disclaimer would undo the localisation in the
# last line of every single response.
#
# `settings.disclaimer` remains the English text and remains configurable; a
# deployment that overrides it gets its own wording in English and the
# authored translations elsewhere, which is the honest behaviour — this module
# cannot translate an arbitrary operator-supplied string on the hot path.
_DISCLAIMER_BY_LANG = {
    "ru": "Это учебный материал, а не медицинская рекомендация.",
    "uz": "Bu oʻquv materiali, tibbiy maslahat emas.",
}
_VERIFY_BY_LANG = {
    "en": "**Verify before you rely on this.**",
    "ru": "**Проверьте, прежде чем полагаться на это.**",
    "uz": "**Bunga tayanishdan oldin tekshiring.**",
}


def disclaimer_for(lang: str) -> str:
    return _DISCLAIMER_BY_LANG.get(lang, settings.disclaimer)


def apply_disclaimer(answer: str, risk: RiskLevel, lang: str = "en") -> str:
    """Rule 3. Every output carries a caveat; higher risk gets a louder one."""
    text = disclaimer_for(lang)
    if risk in (RiskLevel.HIGH, RiskLevel.MEDIUM):
        return f"{answer}\n\n---\n{_VERIFY_BY_LANG.get(lang, _VERIFY_BY_LANG['en'])} {text}"
    return f"{answer}\n\n---\n_{text}_"


def evaluate_confidence(confidences: List[float]) -> Tuple[float, bool, bool]:
    """Rule 4. Returns (mean confidence, uncertain, needs human review).

    A model that is unsure must say so. Anything under the configured threshold
    is flagged, and is routed to an instructor rather than shown as a result.
    """
    if not confidences:
        return 0.0, True, True
    mean = sum(confidences) / len(confidences)
    lowest = min(confidences)
    uncertain = lowest < settings.low_confidence_threshold
    needs_review = mean < settings.low_confidence_threshold
    return round(mean, 4), uncertain, needs_review


# --------------------------------------------------------------------------
# The standard, published so the frontend can render it and judges can read it.
# --------------------------------------------------------------------------

SAFETY_STANDARD = [
    {
        "id": "S1",
        "title": "Scope limitation",
        "rule": "AI assistance is for education. It must never issue a diagnosis, "
                "a treatment plan or a dose for a real patient.",
        "enforced_by": "safety.screen_message - clinical directives are refused",
    },
    {
        "id": "S2",
        "title": "No identifiable data",
        "rule": "Patient identifiers must never be transmitted to a model. "
                "Suspected identifiers are refused and redacted before storage.",
        "enforced_by": "safety.screen_message + safety.redact",
    },
    {
        "id": "S3",
        "title": "Mandatory disclosure",
        "rule": "Every AI output is labelled as AI-generated and carries a "
                "limitations notice. There is no setting that turns this off.",
        "enforced_by": "safety.apply_disclaimer - applied in the service layer",
    },
    {
        "id": "S4",
        "title": "Calibrated confidence",
        "rule": "Model confidence is always shown. Output below the confidence "
                "threshold is flagged as uncertain and escalated for review.",
        "enforced_by": "safety.evaluate_confidence + AnalysisJob.requires_review",
    },
    {
        "id": "S5",
        "title": "Human accountability",
        "rule": "A named human records their own read before the model is "
                "revealed, and every interaction is written to an audit log.",
        "enforced_by": "AnalysisJob.student_finding + the audit_events table",
    },
    {
        "id": "S6",
        "title": "Order of reading",
        "rule": "The model runs only after the student has recorded their own "
                "interpretation. Seeing the AI first is impossible, not discouraged.",
        "enforced_by": "analysis.analyze — HTTP 409 without a prior reading",
    },
]
