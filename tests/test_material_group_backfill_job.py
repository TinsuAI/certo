"""The "chạy lại backfill" button on the material-group-map page → background
job wiring. POSTs to /clients/{cid}/jobs/start with kind=material_group_backfill,
spawning scripts/backfill_johnson_material_group.py --exclusions-only --apply via
the shared _job_runner. subprocess.Popen is monkeypatched so the test verifies
the recipe → job row → spawned command without running the backfill.
"""
from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from app import jobs
from app.database import connect
from app.main import app
from app.routes import jobs as jobs_route


def _login(c: TestClient) -> None:
    r = c.post(
        "/login",
        data={"email": "admin@data-hub.local", "password": "admin123",
              "next": "/clients"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text


@pytest.fixture
def cid():
    c = "mgjob-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s,%s)",
            (c, "MG backfill job test"),
        )
    yield c
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.background_jobs where client_id=%s", (c,))
        cur.execute("delete from hub.clients where client_id=%s", (c,))


@pytest.fixture
def captured_popen(monkeypatch):
    calls: list[list[str]] = []

    class _FakeProc:
        pid = 4242

    def _fake_popen(cmd, *a, **kw):
        calls.append(list(cmd))
        return _FakeProc()

    monkeypatch.setattr(jobs_route.subprocess, "Popen", _fake_popen)
    return calls


def test_button_starts_material_group_backfill_job(cid, captured_popen):
    c = TestClient(app)
    _login(c)
    r = c.post(
        f"/clients/{cid}/jobs/start",
        data={"kind": "material_group_backfill"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    assert r.headers["location"].startswith("/jobs/")

    job = jobs.latest(cid, "material_group_backfill")
    assert job is not None
    assert job.is_active

    # Spawns the backfill script in exclusions-only + apply mode, scoped to
    # this client (the job runner passes --client <cid>).
    assert len(captured_popen) == 1
    cmd = captured_popen[0]
    assert "scripts/backfill_johnson_material_group.py" in " ".join(cmd)
    assert "--client" in cmd and cid in cmd
    assert "--exclusions-only" in cmd
    assert "--apply" in cmd
