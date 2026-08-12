"""End-to-end localisation: what a student actually reads in each language.

The translator is replaced with a deterministic marker so these tests assert
on wiring rather than on the quality of a network call — "did this endpoint
translate the field at all", "did it cache it", "did switching language keep
the run alive". Quality is `test_medical_translate.py`'s job.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import localize, medical_translate, safety, scope


@pytest.fixture(autouse=True)
def offline_translator(monkeypatch):
    """Deterministic stand-in: «ru» Cough.

    Marked rather than really translated, so a test can tell "this came back
    translated" from "this came back English" without needing a model, and so
    the marker is obvious in a failure message.
    """
    calls: list[tuple[int, str]] = []

    def fake(texts, target, source="en"):
        calls.append((len(texts), target))
        return [f"«{target}» {t}" for t in texts]

    monkeypatch.setattr(medical_translate, "translate_batch", fake)
    monkeypatch.setattr(localize.medical_translate, "translate_batch", fake)
    return calls


@pytest.fixture(autouse=True)
def no_gemini(monkeypatch):
    """No narration, so a stage's patient line is the stored authored text."""
    from app.config import settings

    monkeypatch.setattr(settings, "vp_gemini_api_key", "", raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", "", raising=False)


def _headers(base: dict, lang: str) -> dict:
    return {**base, "X-Medly-Lang": lang}


# --------------------------------------------------------------------------
# Virtual Patient — the case in the screenshot
# --------------------------------------------------------------------------

def test_case_list_is_english_by_default(client: TestClient, student_headers: dict) -> None:
    cases = client.get("/api/virtual-patient/cases", headers=student_headers).json()
    assert cases, "the demo case should be seeded"
    assert not cases[0]["title"].startswith("«")


@pytest.mark.parametrize("lang", ["ru", "uz"])
def test_case_list_is_translated(client: TestClient, student_headers: dict, lang: str) -> None:
    """The bug this whole change exists for: a Russian UI over English cases."""
    response = client.get(
        "/api/virtual-patient/cases", headers=_headers(student_headers, lang)
    )
    assert response.status_code == 200, response.text
    case = response.json()[0]
    for field in ("title", "summary", "presenting_complaint"):
        assert case[field].startswith(f"«{lang}»"), f"{field} was not localized: {case[field]!r}"


def test_a_translation_is_cached_not_repeated(
    client: TestClient, student_headers: dict, offline_translator
) -> None:
    """Requirement: no translation call on every page load."""
    client.get("/api/virtual-patient/cases", headers=_headers(student_headers, "ru"))
    offline_translator.clear()

    client.get("/api/virtual-patient/cases", headers=_headers(student_headers, "ru"))
    assert offline_translator == [], "a second view must not translate again"


def test_the_whole_run_is_localized(client: TestClient, student_headers: dict) -> None:
    started = client.post(
        "/api/virtual-patient/cases/cap-sepsis-elderly/start",
        headers=_headers(student_headers, "ru"),
    )
    assert started.status_code == 200, started.text
    body = started.json()
    stage = body["stage"]

    assert body["disclaimer"].startswith("Смоделированный"), "disclaimer not localized"
    for field in ("title", "narrative", "prompt"):
        if stage[field]:
            assert stage[field].startswith("«ru»"), f"stage.{field}: {stage[field]!r}"
    for option in stage["options"]:
        assert option["label"].startswith("«ru»"), f"option: {option['label']!r}"

    client.post(
        f"/api/virtual-patient/sessions/{body['session_id']}/abandon",
        headers=student_headers,
    )


def test_decision_feedback_is_localized(client: TestClient, student_headers: dict) -> None:
    started = client.post(
        "/api/virtual-patient/cases/cap-sepsis-elderly/start",
        headers=_headers(student_headers, "uz"),
    ).json()
    stage = started["stage"]
    if not stage["options"]:
        pytest.skip("the opening stage of this case asks nothing")

    result = client.post(
        f"/api/virtual-patient/sessions/{started['session_id']}/decision",
        json={"stage_key": stage["key"], "option_key": stage["options"][0]["key"]},
        headers=_headers(student_headers, "uz"),
    )
    assert result.status_code == 200, result.text
    assert result.json()["feedback"].startswith("«uz»")

    client.post(
        f"/api/virtual-patient/sessions/{started['session_id']}/abandon",
        headers=student_headers,
    )


def test_switching_language_keeps_the_run(client: TestClient, student_headers: dict) -> None:
    """Requirement: changing language must not restart a case."""
    started = client.post(
        "/api/virtual-patient/cases/cap-sepsis-elderly/start",
        headers=_headers(student_headers, "ru"),
    ).json()
    session_id = started["session_id"]
    stage_key = started["stage"]["key"]
    score = started["score"]

    switched = client.get(
        f"/api/virtual-patient/sessions/{session_id}",
        headers=_headers(student_headers, "uz"),
    )
    assert switched.status_code == 200, switched.text
    after = switched.json()

    assert after["session_id"] == session_id, "the run must survive a language change"
    assert after["stage"]["key"] == stage_key, "the student must not lose their place"
    assert after["score"] == score
    assert after["stage"]["title"].startswith("«uz»"), "content did not follow the switch"

    client.post(
        f"/api/virtual-patient/sessions/{session_id}/abandon", headers=student_headers
    )


def test_numbers_in_a_case_are_never_altered(
    client: TestClient, student_headers: dict, monkeypatch
) -> None:
    """The marker prefix must not disturb the clinical values in the text."""
    english = client.get("/api/virtual-patient/cases", headers=student_headers).json()[0]
    russian = client.get(
        "/api/virtual-patient/cases", headers=_headers(student_headers, "ru")
    ).json()[0]

    assert russian["patient_age"] == english["patient_age"]
    assert medical_translate.digit_signature(
        english["summary"]
    ) == medical_translate.digit_signature(russian["summary"])


# --------------------------------------------------------------------------
# Curriculum
# --------------------------------------------------------------------------

def test_courses_are_localized(client: TestClient, student_headers: dict) -> None:
    courses = client.get("/api/courses", headers=_headers(student_headers, "ru")).json()
    assert courses, "courses should be seeded"
    assert courses[0]["title"].startswith("«ru»")


def test_a_quiz_and_its_choices_are_localized(
    client: TestClient, student_headers: dict
) -> None:
    courses = client.get("/api/courses", headers=student_headers).json()
    quizzes = client.get(
        f"/api/quizzes/course/{courses[0]['slug']}",
        headers=_headers(student_headers, "uz"),
    ).json()
    if not quizzes:
        pytest.skip("no quiz seeded for the first course")

    quiz = quizzes[0]
    assert quiz["title"].startswith("«uz»")
    for question in quiz["questions"]:
        assert question["prompt"].startswith("«uz»")
        for choice in question["choices"]:
            assert choice["text"].startswith("«uz»")


# --------------------------------------------------------------------------
# The assistant
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "lang, opening",
    [("en", "I'm Medly AI"), ("ru", "Я Medly AI"), ("uz", "Men Medly AI")],
)
def test_the_refusal_arrives_in_the_reader_language(
    client: TestClient, premium_headers: dict, lang: str, opening: str
) -> None:
    """The one reply guaranteed to be shown must not be guaranteed English."""
    response = client.post(
        "/api/assistant/chat",
        json={"message": "Write me a Python script to sort a list"},
        headers=_headers(premium_headers, lang),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["blocked"] is True
    assert body["reply"].startswith(opening), body["reply"][:80]


def test_the_disclaimer_follows_the_language() -> None:
    from app.models.enums import RiskLevel

    assert "учебный материал" in safety.apply_disclaimer("Ответ", RiskLevel.LOW, "ru")
    assert "oʻquv materiali" in safety.apply_disclaimer("Javob", RiskLevel.LOW, "uz")
    # The English wording still comes from settings, so it stays configurable.
    assert safety.disclaimer_for("en") == safety.settings.disclaimer


def test_every_supported_locale_has_an_authored_refusal() -> None:
    from app.lang import SUPPORTED_LANGS

    assert set(scope.REFUSAL_BY_LANG) == SUPPORTED_LANGS


def test_an_unknown_locale_falls_back_to_english() -> None:
    assert scope.refusal_for("de") == scope.REFUSAL
    assert safety.disclaimer_for("de") == safety.settings.disclaimer


# --------------------------------------------------------------------------
# Structural invariants
# --------------------------------------------------------------------------

def test_the_engine_does_not_import_the_model_at_module_scope() -> None:
    """The deterministic engine must stay deterministic.

    `stage_view` reads translations through `localize`, which reaches the
    translator, which reaches Gemini. All of those imports are deferred into
    the functions that need them; a module-scope import would give the module
    that decides clinical outcomes a load-time dependency on a language model.
    """
    import ast
    import pathlib

    source = pathlib.Path("app/services/virtual_patient_engine.py").read_text()
    tree = ast.parse(source)
    top_level = [
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in ([node.module] if isinstance(node, ast.ImportFrom) else node.names)
        for alias in [alias if isinstance(alias, str) else alias.name]
    ]
    assert not any("gemini" in (name or "") for name in top_level), top_level
    assert not any("medical_translate" in (name or "") for name in top_level), top_level
