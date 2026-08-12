"""Virtual Patient — the engine decides, the model only narrates.

The assertions that matter most here are the negative ones: that a run works
with Gemini switched off, that a language model is never consulted for a
verdict, and that a client cannot skip a stage or play someone else's session.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services import virtual_patient_service as narration

CASE = "cap-sepsis-elderly"


@pytest.fixture
def no_gemini(monkeypatch):
    """Any outbound Gemini call fails the test.

    The simulation must be fully playable without a model, so every test in
    this file runs with the provider bolted shut unless it says otherwise.
    """
    def forbidden(*args, **kwargs):
        raise AssertionError("Virtual Patient called Gemini for game logic")

    monkeypatch.setattr(httpx.Client, "post", forbidden)
    monkeypatch.setattr(httpx.Client, "stream", forbidden)
    # No key configured -> the service short-circuits before any HTTP.
    monkeypatch.setattr(settings, "vp_gemini_api_key", "", raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", "", raising=False)
    yield


def start(client: TestClient, headers: dict) -> dict:
    response = client.post(f"/api/virtual-patient/cases/{CASE}/start", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def decide(client: TestClient, headers: dict, sid: int, stage: str, option: str):
    return client.post(
        f"/api/virtual-patient/sessions/{sid}/decision",
        json={"stage_key": stage, "option_key": option},
        headers=headers,
    )


# --------------------------------------------------------------------------
# cases
# --------------------------------------------------------------------------

def test_cases_are_listed(client: TestClient, student_headers: dict, no_gemini) -> None:
    response = client.get("/api/virtual-patient/cases", headers=student_headers)
    assert response.status_code == 200
    slugs = [c["slug"] for c in response.json()]
    assert CASE in slugs


def test_case_detail(client: TestClient, student_headers: dict, no_gemini) -> None:
    response = client.get(f"/api/virtual-patient/cases/{CASE}", headers=student_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["patient_name"] == "Robert Iversen"
    assert body["stage_count"] >= 6
    assert body["max_score"] > 0
    # The diagnosis is not handed out before the case is played.
    assert "correct_diagnosis" not in body


def test_unknown_case_is_404(client: TestClient, student_headers: dict, no_gemini) -> None:
    assert client.get(
        "/api/virtual-patient/cases/not-a-case", headers=student_headers
    ).status_code == 404


# --------------------------------------------------------------------------
# sessions
# --------------------------------------------------------------------------

def test_start_opens_a_session_at_the_first_stage(
    client: TestClient, student_headers: dict, no_gemini
) -> None:
    body = start(client, student_headers)
    assert body["status"] == "in_progress"
    assert body["patient_state"] == "stable"
    assert body["stage"]["key"] == "arrival"
    assert body["score"] == 0
    assert body["vitals"]["spo2"] == 89
    assert body["disclaimer"]
    # Options must never carry the answer key.
    for option in body["stage"]["options"]:
        assert set(option) == {"key", "label", "detail"}


def test_start_twice_resumes_rather_than_duplicating(
    client: TestClient, student_headers: dict, no_gemini
) -> None:
    first = start(client, student_headers)
    second = start(client, student_headers)
    assert first["session_id"] == second["session_id"]


def test_session_state_can_be_read_back(
    client: TestClient, student_headers: dict, no_gemini
) -> None:
    sid = start(client, student_headers)["session_id"]
    response = client.get(f"/api/virtual-patient/sessions/{sid}", headers=student_headers)
    assert response.status_code == 200
    assert response.json()["stage"]["key"] == "arrival"


# --------------------------------------------------------------------------
# decisions
# --------------------------------------------------------------------------

def test_correct_decision_scores_and_advances(
    client: TestClient, student_headers: dict, no_gemini
) -> None:
    sid = start(client, student_headers)["session_id"]
    response = decide(client, student_headers, sid, "arrival", "abcde")
    assert response.status_code == 200
    body = response.json()
    assert body["was_correct"] is True
    assert body["score_delta"] == 20
    assert body["score"] == 20
    assert body["next_stage"]["key"] == "history"
    assert body["patient_state_after"] == "stable"


def test_incorrect_decision_scores_less_and_still_advances(
    client: TestClient, student_headers: dict, no_gemini
) -> None:
    sid = start(client, student_headers)["session_id"]
    body = decide(client, student_headers, sid, "arrival", "history_first").json()
    assert body["was_correct"] is False
    assert body["score_delta"] == 5
    assert body["next_stage"]["key"] == "history"


def test_harmful_decision_deteriorates_the_patient(
    client: TestClient, student_headers: dict, no_gemini
) -> None:
    sid = start(client, student_headers)["session_id"]
    body = decide(client, student_headers, sid, "arrival", "wait_bloods").json()
    assert body["was_harmful"] is True
    assert body["patient_state_before"] == "stable"
    assert body["patient_state_after"] == "deteriorating"
    # The observations move with the words describing them.
    assert body["vitals"]["hr"] > 112
    assert body["vitals"]["spo2"] < 89


def test_correct_management_improves_the_patient(
    client: TestClient, student_headers: dict, no_gemini
) -> None:
    sid = start(client, student_headers)["session_id"]
    decide(client, student_headers, sid, "arrival", "abcde")
    decide(client, student_headers, sid, "history", "curb65_3")
    body = decide(client, student_headers, sid, "sepsis_six", "sepsis_six_bundle").json()
    assert body["patient_state_after"] == "improving"
    assert body["vitals"]["spo2"] == 95


def test_a_clean_run_completes_and_passes(
    client: TestClient, student_headers: dict, no_gemini
) -> None:
    sid = start(client, student_headers)["session_id"]
    decide(client, student_headers, sid, "arrival", "abcde")
    decide(client, student_headers, sid, "history", "curb65_3")
    decide(client, student_headers, sid, "sepsis_six", "sepsis_six_bundle")
    final = decide(client, student_headers, sid, "response", "admit_ward").json()

    assert final["finished"] is True
    assert final["outcome"] == "good"
    assert final["next_stage"]["is_terminal"] is True

    state = client.get(
        f"/api/virtual-patient/sessions/{sid}", headers=student_headers
    ).json()
    assert state["status"] == "completed"
    assert state["passed"] is True


def test_the_dangerous_path_can_kill_the_patient(
    client: TestClient, student_headers: dict, no_gemini
) -> None:
    """Discharging a septic patient, then observing, ends the run as failed."""
    sid = start(client, student_headers)["session_id"]
    decide(client, student_headers, sid, "arrival", "abcde")
    decide(client, student_headers, sid, "history", "curb65_1")
    critical = decide(client, student_headers, sid, "sepsis_six", "discharge").json()
    assert critical["patient_state_after"] == "critical"
    assert critical["next_stage"]["key"] == "deterioration"

    dead = decide(client, student_headers, sid, "deterioration", "observe_more").json()
    assert dead["patient_state_after"] == "failed"
    assert dead["finished"] is True

    state = client.get(
        f"/api/virtual-patient/sessions/{sid}", headers=student_headers
    ).json()
    assert state["status"] == "failed"
    assert state["passed"] is False


def test_escalating_after_a_mistake_rescues_the_patient(
    client: TestClient, student_headers: dict, no_gemini
) -> None:
    sid = start(client, student_headers)["session_id"]
    decide(client, student_headers, sid, "arrival", "abcde")
    decide(client, student_headers, sid, "history", "curb65_1")
    decide(client, student_headers, sid, "sepsis_six", "discharge")
    rescued = decide(client, student_headers, sid, "deterioration", "escalate").json()
    assert rescued["patient_state_after"] == "stable"
    assert rescued["next_stage"]["key"] == "response"


# --------------------------------------------------------------------------
# refusals
# --------------------------------------------------------------------------

def test_option_that_does_not_exist_is_rejected(
    client: TestClient, student_headers: dict, no_gemini
) -> None:
    sid = start(client, student_headers)["session_id"]
    response = decide(client, student_headers, sid, "arrival", "give-adrenaline")
    assert response.status_code == 400


def test_answering_a_stage_you_are_not_on_is_rejected(
    client: TestClient, student_headers: dict, no_gemini
) -> None:
    """Otherwise a client could skip the case and jump to the good ending."""
    sid = start(client, student_headers)["session_id"]
    response = decide(client, student_headers, sid, "response", "admit_ward")
    assert response.status_code == 409


def test_a_finished_case_accepts_no_more_decisions(
    client: TestClient, student_headers: dict, no_gemini
) -> None:
    sid = start(client, student_headers)["session_id"]
    decide(client, student_headers, sid, "arrival", "abcde")
    decide(client, student_headers, sid, "history", "curb65_3")
    decide(client, student_headers, sid, "sepsis_six", "sepsis_six_bundle")
    decide(client, student_headers, sid, "response", "admit_ward")

    again = decide(client, student_headers, sid, "response", "admit_ward")
    assert again.status_code == 409


def test_another_users_session_is_not_visible(
    client: TestClient, student_headers: dict, instructor_headers: dict, no_gemini
) -> None:
    sid = start(client, student_headers)["session_id"]
    assert client.get(
        f"/api/virtual-patient/sessions/{sid}", headers=instructor_headers
    ).status_code == 404
    assert decide(client, instructor_headers, sid, "arrival", "abcde").status_code == 404


def test_endpoints_require_authentication(client: TestClient) -> None:
    assert client.get("/api/virtual-patient/cases").status_code == 401
    assert client.post(
        f"/api/virtual-patient/cases/{CASE}/start"
    ).status_code == 401


# --------------------------------------------------------------------------
# result and debrief
# --------------------------------------------------------------------------

def test_result_is_refused_while_the_case_is_running(
    client: TestClient, student_headers: dict, no_gemini
) -> None:
    sid = start(client, student_headers)["session_id"]
    assert client.get(
        f"/api/virtual-patient/sessions/{sid}/result", headers=student_headers
    ).status_code == 409


def test_debrief_falls_back_to_authored_text_without_gemini(
    client: TestClient, student_headers: dict, no_gemini
) -> None:
    sid = start(client, student_headers)["session_id"]
    decide(client, student_headers, sid, "arrival", "abcde")
    decide(client, student_headers, sid, "history", "curb65_3")
    decide(client, student_headers, sid, "sepsis_six", "sepsis_six_bundle")
    decide(client, student_headers, sid, "response", "admit_ward")

    body = client.get(
        f"/api/virtual-patient/sessions/{sid}/result", headers=student_headers
    ).json()
    assert body["passed"] is True
    assert body["debrief_narrated"] is False        # authored text, not the model
    assert "CURB-65" in body["debrief"]
    assert body["correct_diagnosis"].startswith("Community-acquired pneumonia")
    assert len(body["decisions"]) == 4
    assert body["decisions"][0]["was_correct"] is True


# --------------------------------------------------------------------------
# the model is narration only
# --------------------------------------------------------------------------

def test_gemini_failure_does_not_break_narration(monkeypatch) -> None:
    """A provider outage yields the authored line, not an exception."""
    monkeypatch.setattr(settings, "vp_gemini_api_key", "test-key", raising=False)

    def explode(*args, **kwargs):
        raise RuntimeError("provider on fire")

    monkeypatch.setattr(httpx.Client, "post", explode)
    result = narration.patient_says(
        case_brief="brief",
        patient_name="Robert",
        patient_age=74,
        patient_sex="male",
        situation="Arrival",
        authored_line="I can't get my breath.",
    )
    assert result.text == "I can't get my breath."
    assert result.used_model is False


def test_a_whole_case_is_playable_with_gemini_down(
    client: TestClient, student_headers: dict, monkeypatch
) -> None:
    """The core simulation does not depend on the model being reachable."""
    monkeypatch.setattr(settings, "vp_gemini_api_key", "test-key", raising=False)

    def explode(*args, **kwargs):
        raise RuntimeError("provider on fire")

    monkeypatch.setattr(httpx.Client, "post", explode)

    sid = start(client, student_headers)["session_id"]
    decide(client, student_headers, sid, "arrival", "abcde")
    decide(client, student_headers, sid, "history", "curb65_3")
    decide(client, student_headers, sid, "sepsis_six", "sepsis_six_bundle")
    final = decide(client, student_headers, sid, "response", "admit_ward").json()
    assert final["finished"] is True
    assert final["outcome"] == "good"
    # Authored patient line survived the outage.
    assert final["next_stage"]["narrated"] is False
