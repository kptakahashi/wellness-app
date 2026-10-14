"""Test harness: isolated SQLite in a temp dir, rules backend, no network, no .env surprises.

Environment must be set before `app` is imported because Settings and the DB engine are built at import time.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="wellness-test-")
os.environ.update(
    {
        "DATA_DIR": _TMP,
        "DATABASE_URL": "",
        "INFERENCE_BACKEND": "rules",
        "APP_TOKEN": "test-token",
        "POI_SOURCE": "none",
        "DEMO_MODE": "false",
        "CALENDAR_ICS_URLS": "",
        "TIMEZONE": "Asia/Tokyo",
        "RAW_EVENT_RETENTION_DAYS": "90",
    }
)

from sqlmodel import Session  # noqa: E402

from app.core.db import engine, init_db  # noqa: E402
from app.services.retention import delete_everything  # noqa: E402

TOKEN = os.environ["APP_TOKEN"]


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    init_db()


@pytest.fixture
def session() -> Iterator[Session]:
    with Session(engine) as s:
        delete_everything(s)
        yield s
        delete_everything(s)


@pytest.fixture
def client(session: Session):
    """FastAPI test client. Not a context manager on purpose: the lifespan (scheduler) must not start."""
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app, headers={"X-Api-Token": TOKEN})
