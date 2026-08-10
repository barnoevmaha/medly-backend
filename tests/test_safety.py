"""The guardrails are the product, so they get the most tests."""
from __future__ import annotations

import pytest

from app.models.enums import RiskLevel
from app.services import safety


@pytest.mark.parametrize(
    "message",
    [
        "My patient has chest pain, what is the diagnosis?",
        "Should I prescribe amoxicillin?",
        "What dose of heparin do I give?",
        "Is this malignant?",
        "Can I discharge them now?",
    ],
)
def test_clinical_directives_are_refused(message: str) -> None:
    verdict = safety.screen_message(message)
    assert verdict.blocked
    assert verdict.risk_level is RiskLevel.HIGH
    assert verdict.refusal_message


@pytest.mark.parametrize(
    "message",
    [
        "Patient MRN 4429183 presented today",
        "DOB 04/11/1998, chest film",
        "Email me at someone@example.com",
        "SSN 123-45-6789",
    ],
)
def test_identifiers_are_refused_and_redacted(message: str) -> None:
    verdict = safety.screen_message(message)
    assert verdict.blocked
    assert "[redacted]" in verdict.redacted_text


@pytest.mark.parametrize(
    "message",
    [
        "What is automation bias?",
        "Explain sensitivity versus specificity",
        "How does a CNN classify a chest X-ray?",
        "What is the ALARA principle?",
    ],
)
def test_teaching_questions_are_allowed(message: str) -> None:
    assert safety.screen_message(message).allowed


def test_imaging_topics_are_medium_risk() -> None:
    assert safety.classify_risk("How do I read a chest x-ray?") is RiskLevel.MEDIUM
    assert safety.classify_risk("What is automation bias?") is RiskLevel.LOW


def test_disclaimer_is_always_appended() -> None:
    for risk in RiskLevel:
        assert "Educational use only" in safety.apply_disclaimer("Answer.", risk)


def test_low_confidence_triggers_review() -> None:
    mean, uncertain, review = safety.evaluate_confidence([0.55, 0.60])
    assert uncertain and review and mean < 0.7

    mean, uncertain, review = safety.evaluate_confidence([0.92, 0.88])
    assert not uncertain and not review and mean > 0.85


def test_empty_confidence_is_treated_as_uncertain() -> None:
    mean, uncertain, review = safety.evaluate_confidence([])
    assert mean == 0.0 and uncertain and review
