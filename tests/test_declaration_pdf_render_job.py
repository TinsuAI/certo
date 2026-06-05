"""Test the "Render PDF còn thiếu" button → background job wiring.

The declarations page button POSTs to `/clients/{cid}/jobs/start` with
`kind=declaration_pdf_render`, which spawns the backfill script via the
shared `_job_runner` infra. We monkeypatch `subprocess.Popen` so the test
verifies the wiring (recipe → job row → spawned command) without running
LibreOffice. The script itself is covered by the backfill smoke + the
download.pdf provider tests.
"""
from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from app import jobs
from app.database import connect
from app.main import app
from app.routes import jobs as jobs_route


def _client() -> TestClient:
    return TestClient(app)


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
    c = "pdfjob-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s,%s)",
            (c, "PDF job test"),
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


def test_button_starts_pdf_render_job(cid, captured_popen):
    c = _client()
    _login(c)
    r = c.post(
        f"/clients/{cid}/jobs/start",
        data={"kind": "declaration_pdf_render"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    assert r.headers["location"].startswith("/jobs/")

    # A job row was created for this client with the right kind.
    job = jobs.latest(cid, "declaration_pdf_render")
    assert job is not None
    assert job.is_active

    # The spawned command runs the backfill script scoped to this client.
    assert len(captured_popen) == 1
    cmd = " ".join(captured_popen[0])
    assert "scripts/backfill_declaration_pdfs.py" in cmd
    assert "--client" in captured_popen[0]
    assert cid in captured_popen[0]


def test_second_click_dedups_to_active_job(cid, captured_popen):
    c = _client()
    _login(c)
    first = c.post(
        f"/clients/{cid}/jobs/start",
        data={"kind": "declaration_pdf_render"},
        follow_redirects=False,
    )
    job = jobs.latest(cid, "declaration_pdf_render")
    # Second click while the first is still active → redirect to the
    # existing job, no second spawn.
    second = c.post(
        f"/clients/{cid}/jobs/start",
        data={"kind": "declaration_pdf_render"},
        follow_redirects=False,
    )
    assert second.status_code == 303
    assert second.headers["location"] == f"/jobs/{job.id}"
    assert len(captured_popen) == 1  # only the first click spawned


def test_render_button_present_on_declarations_page(cid):
    c = _client()
    _login(c)
    r = c.get(f"/clients/{cid}/declarations")
    assert r.status_code == 200
    assert 'value="declaration_pdf_render"' in r.text
    assert "Render PDF còn thiếu" in r.text
