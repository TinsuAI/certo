"""Pytest bootstrap: apply migrations once per session.

Tests that drive the app via TestClient pick up migrations through the
lifespan startup. Tests that hit `connect()` directly in fixtures
don't — they need the schema to exist before the first cursor opens.
This session-scoped autouse fixture closes that gap so the test
suite works against a fresh database (e.g. the postgres service
container in CI)."""
from __future__ import annotations

import pytest

from app.database import apply_migrations


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_schema():
    apply_migrations()
    yield
