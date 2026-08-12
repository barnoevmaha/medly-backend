"""Seed the Virtual Patient scenarios.

The cases themselves are no longer written here. Each one is a JSON file in
`app/data/virtual_patients/`, read and validated by
`app.services.virtual_patient_loader`, so adding a scenario is adding a file.

Seeding stays idempotent: the loader matches by slug and skips anything already
present, in line with every other seeder in this project.
"""
from __future__ import annotations

from sqlmodel import Session

from app.services.virtual_patient_loader import seed_cases


def run(session: Session) -> None:
    """Insert every valid scenario that is not already in the database."""
    seed_cases(session)
