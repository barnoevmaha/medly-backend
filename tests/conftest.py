from __future__ import annotations

import os
import tempfile
from typing import Iterator

import pytest

os.environ.setdefault("MEDLY_SECRET_KEY", "test-secret")
_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.environ["MEDLY_DATABASE_URL"] = f"sqlite:///{_db_path}"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import DEMO_PASSWORD, run as seed_run  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    init_db()
    seed_run()
    yield
    os.close(_db_fd)
    os.unlink(_db_path)


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _token(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/auth/login", data={"username": email, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
def student_headers(client: TestClient) -> dict:
    return {"Authorization": f"Bearer {_token(client, 'student@medly.dev')}"}


@pytest.fixture
def premium_headers(client: TestClient) -> dict:
    return {"Authorization": f"Bearer {_token(client, 'premium@medly.dev')}"}


@pytest.fixture
def instructor_headers(client: TestClient) -> dict:
    return {"Authorization": f"Bearer {_token(client, 'instructor@medly.dev')}"}
