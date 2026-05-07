"""Phase 3a · catalog UI staff override for materials.btp_sourcing.

Endpoint: POST /clients/{client_id}/catalog/{customs_code}/btp_sourcing
Body form: btp_sourcing=<purchased_only|self_produced_only|dual_source|unknown>

Override semantics: classifier output is the default; staff override
takes precedence. Future classifier runs do not overwrite manual
overrides (tracked separately in BACKLOG; for 3a, override is plain
last-write-wins).
"""
from __future__ import annotations

import jwt as pyjwt
import pytest
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

from app import auth, jwt_issuer
from app.database import connect
from app.main import app


CLIENT = "btp_override_test"


@pytest.fixture(autouse=True)
def isolated_keys_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DATA_HUB_KEYS_DIR", d)
        yield Path(d)


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (CLIENT, "btp override test"),
        )
        cur.execute(
            "insert into hub.materials (client_id, customs_code, internal_code, "
            "name, category) values (%s, 'BTP_OV', 'BTP_OV', 'override target', 'btp_sx') "
            "on conflict do nothing",
            (CLIENT,),
        )
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def _session_client(role: str = "admin") -> TestClient:
    """Logged-in TestClient via session-cookie login."""
    c = TestClient(app)
    # admin@data-hub.local seeded by conftest at session start
    r = c.post(
        "/login",
        data={"email": "admin@data-hub.local", "password": "admin123"},
        follow_redirects=False,
    )
    assert r.status_code in (303, 302), r.status_code
    return c


def test_override_sets_btp_sourcing():
    c = _session_client()
    r = c.post(
        f"/clients/{CLIENT}/catalog/BTP_OV/btp_sourcing",
        data={"btp_sourcing": "self_produced_only"},
        follow_redirects=False,
    )
    assert r.status_code in (303, 302), r.text
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select btp_sourcing from hub.materials "
            "where client_id=%s and customs_code='BTP_OV'",
            (CLIENT,),
        )
        assert cur.fetchone()[0] == "self_produced_only"


def test_override_rejects_invalid_value():
    c = _session_client()
    r = c.post(
        f"/clients/{CLIENT}/catalog/BTP_OV/btp_sourcing",
        data={"btp_sourcing": "wrong_value"},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_override_404_on_unknown_material():
    c = _session_client()
    r = c.post(
        f"/clients/{CLIENT}/catalog/UNKNOWN_CODE/btp_sourcing",
        data={"btp_sourcing": "purchased_only"},
        follow_redirects=False,
    )
    assert r.status_code == 404


def test_override_rejects_non_btp_category():
    """Only btp_sx materials carry btp_sourcing; reject for other categories."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, customs_code, internal_code, "
            "name, category) values (%s, 'NVL_OV', 'NVL_OV', 'nvl', 'nvl') "
            "on conflict do nothing",
            (CLIENT,),
        )
    c = _session_client()
    r = c.post(
        f"/clients/{CLIENT}/catalog/NVL_OV/btp_sourcing",
        data={"btp_sourcing": "purchased_only"},
        follow_redirects=False,
    )
    assert r.status_code == 400
