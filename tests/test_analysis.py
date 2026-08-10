"""The workflow that fights automation bias, and the gate that guards it."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _create_case(client: TestClient, headers: dict, ref: str) -> int:
    response = client.post(
        "/api/analysis/cases", json={"case_ref": ref, "modality": "xray"}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_uncertified_student_cannot_run_analysis(
    client: TestClient, student_headers: dict
) -> None:
    case_id = _create_case(client, student_headers, "CASE-LOCKED")
    client.post(
        f"/api/analysis/{case_id}/my-reading",
        json={"finding": "Possible right basal consolidation"},
        headers=student_headers,
    )
    response = client.post(f"/api/analysis/{case_id}/analyze", headers=student_headers)
    assert response.status_code == 403
    assert "certification" in response.json()["detail"].lower()


def test_analysis_blocked_before_student_reading(
    client: TestClient, certified_headers: dict
) -> None:
    case_id = _create_case(client, certified_headers, "CASE-ORDER")
    response = client.post(f"/api/analysis/{case_id}/analyze", headers=certified_headers)
    assert response.status_code == 409


def test_full_workflow(client: TestClient, certified_headers: dict) -> None:
    case_id = _create_case(client, certified_headers, "CASE-001")

    reading = client.post(
        f"/api/analysis/{case_id}/my-reading",
        json={"finding": "Right lower zone opacity, query consolidation"},
        headers=certified_headers,
    )
    assert reading.status_code == 200
    assert reading.json()["student_finding"]

    analysed = client.post(f"/api/analysis/{case_id}/analyze", headers=certified_headers)
    assert analysed.status_code == 200
    body = analysed.json()
    assert body["findings"]
    assert body["model_version"]
    assert body["known_limitations"], "the model must publish its limitations"
    assert "Educational use only" in body["disclaimer"]
    for finding in body["findings"]:
        assert 0.0 <= finding["confidence"] <= 1.0
        assert len(finding["bbox"]) == 4

    decided = client.post(
        f"/api/analysis/{case_id}/decide",
        json={"final_decision": "I disagree, this is a vascular shadow", "agreed_with_ai": False},
        headers=certified_headers,
    )
    assert decided.status_code == 200
    assert decided.json()["agreed_with_ai"] is False


def test_reading_cannot_be_submitted_twice(client: TestClient, certified_headers: dict) -> None:
    case_id = _create_case(client, certified_headers, "CASE-DUP")
    client.post(
        f"/api/analysis/{case_id}/my-reading", json={"finding": "Normal"}, headers=certified_headers
    )
    again = client.post(
        f"/api/analysis/{case_id}/my-reading", json={"finding": "Changed"}, headers=certified_headers
    )
    assert again.status_code == 400


def test_empty_reading_rejected(client: TestClient, certified_headers: dict) -> None:
    case_id = _create_case(client, certified_headers, "CASE-EMPTY")
    response = client.post(
        f"/api/analysis/{case_id}/my-reading", json={"finding": "   "}, headers=certified_headers
    )
    assert response.status_code == 400


def test_cases_are_private(client: TestClient, certified_headers: dict, student_headers: dict) -> None:
    case_id = _create_case(client, certified_headers, "CASE-PRIVATE")
    response = client.post(
        f"/api/analysis/{case_id}/my-reading", json={"finding": "x"}, headers=student_headers
    )
    assert response.status_code == 404


def test_inference_is_deterministic(client: TestClient, certified_headers: dict) -> None:
    """Same case reference must produce the same result, so demos are repeatable."""
    outputs = []
    for suffix in ("A", "B"):
        case_id = _create_case(client, certified_headers, "CASE-DETERMINISM")
        client.post(
            f"/api/analysis/{case_id}/my-reading",
            json={"finding": f"reading {suffix}"},
            headers=certified_headers,
        )
        body = client.post(f"/api/analysis/{case_id}/analyze", headers=certified_headers).json()
        outputs.append([(f["label"], f["confidence"]) for f in body["findings"]])
    assert outputs[0] == outputs[1]
