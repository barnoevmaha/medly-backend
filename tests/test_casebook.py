"""Case references: who may author them, and what a student is allowed to see."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.anonymize import anonymize


def test_students_cannot_create_case_references(
    client: TestClient, student_headers: dict
) -> None:
    permissions = client.get("/api/casebook/permissions", headers=student_headers).json()
    assert permissions["can_author"] is False

    response = client.post(
        "/api/casebook/cases",
        json={"case_ref": "STUDENT-1", "title": "Should not exist"},
        headers=student_headers,
    )
    assert response.status_code == 403


def test_teacher_workflow_case_image_verify_publish(
    client: TestClient, instructor_headers: dict
) -> None:
    created = client.post(
        "/api/casebook/cases",
        json={
            "case_ref": "CXR-TEST-1",
            "title": "Left basal consolidation",
            "modality": "xray",
            "body_region": "Chest",
            "patient_age_band": "50-59",
            "patient_sex": "M",
            "clinical_context": "Cough and fever for three days.",
        },
        headers=instructor_headers,
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    assert created.json()["published"] is False

    # A case with no verified image cannot be published.
    blocked = client.post(f"/api/casebook/cases/{case_id}/publish", headers=instructor_headers)
    assert blocked.status_code == 409

    image = client.post(
        f"/api/casebook/cases/{case_id}/images",
        json={
            "caption": "PA film",
            "view": "PA",
            "metadata": {"PatientName": "Doe^John", "PatientID": "MRN-1", "PatientAge": "055Y"},
            "overlay_text": "Doe, John MRN 12345 01/02/2026",
        },
        headers=instructor_headers,
    )
    assert image.status_code == 201, image.text
    assert image.json()["anonymization_status"] == "auto_redacted"
    assert "PatientName" in image.json()["redacted_fields"]

    # Still not publishable: the automatic pass is a proposal, not a sign-off.
    still_blocked = client.post(
        f"/api/casebook/cases/{case_id}/publish", headers=instructor_headers
    )
    assert still_blocked.status_code == 409

    verified = client.post(
        f"/api/casebook/images/{image.json()['id']}/verify", headers=instructor_headers
    )
    assert verified.status_code == 200
    assert verified.json()["anonymization_status"] == "verified"
    assert verified.json()["verified_by_name"]

    published = client.post(f"/api/casebook/cases/{case_id}/publish", headers=instructor_headers)
    assert published.status_code == 200
    assert published.json()["published"] is True


def test_students_only_see_published_cases(
    client: TestClient, student_headers: dict, instructor_headers: dict
) -> None:
    draft = client.post(
        "/api/casebook/cases",
        json={"case_ref": "CXR-DRAFT-9", "title": "Unpublished draft"},
        headers=instructor_headers,
    ).json()

    listing = client.get("/api/casebook/cases", headers=student_headers).json()
    assert all(item["published"] for item in listing)
    assert all(item["case_ref"] != "CXR-DRAFT-9" for item in listing)

    denied = client.get(f"/api/casebook/cases/{draft['id']}", headers=student_headers)
    assert denied.status_code == 403


def test_anonymize_strips_identifiers_and_refuses_to_self_certify() -> None:
    result = anonymize(
        {
            "PatientName": "Doe^Jane",
            "PatientID": "MRN-99120",
            "PatientBirthDate": "19580214",
            "PatientAge": "068Y",
            "PatientSex": "F",
            "InstitutionName": "St Elsewhere",
            "Modality": "CR",
        },
        overlay_text="Doe, Jane MRN 99120 14/02/2026",
    )

    assert "PatientName" in result["removed_fields"]
    assert "PatientBirthDate" in result["removed_fields"]
    assert "InstitutionName" in result["removed_fields"]
    assert "PatientName" not in result["kept_fields"]
    # Age is coarsened to a band, never carried as a date of birth.
    assert result["kept_fields"]["PatientAge"] == "60-69"
    assert "99120" not in str(result["overlay_text"])
    # The automatic pass never certifies itself.
    assert result["status"] == "auto_redacted"
    assert result["residual_risks"]
