"""API: default alive-only status filter on /v1/hub/materials (issue #31).

Default predicate is `status not in ('tombstoned','inactive')` — NOT
`status='active'`: approval is `source` promotion plus the candidates queue,
so `under_review` and `deprecated` mark live, observed materials that CO's
roster and name resolution depend on. An explicit `?status=` opts into any
single status on both routes.

Spec: .ai/features/2026-07-10-catalog-candidates-merge/brief.md
"""
from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from app.database import connect
from app.main import app

STATUSES = ("active", "under_review", "deprecated", "inactive", "tombstoned")


@pytest.fixture(autouse=True)
def auth_disabled(monkeypatch):
    monkeypatch.setenv("DATA_HUB_API_AUTH_DISABLED", "1")


@pytest.fixture
def cid_all_statuses():
    """One material per status; material_code = MAT_<STATUS>."""
    cid = "matstatus-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (cid, "materials status filter test"),
        )
        for status in STATUSES:
            cur.execute(
                "insert into hub.materials (client_id, material_code, "
                "name, category, status) values (%s, %s, %s, 'nvl', %s)",
                (cid, f"MAT_{status.upper()}", f"Material {status}", status),
            )
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.materials where client_id=%s", (cid,))
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


def _client():
    return TestClient(app)


def _list_codes(cid, **params):
    r = _client().get("/v1/hub/materials", params={"client_id": cid, **params})
    assert r.status_code == 200, r.text
    return {it["material_code"] for it in r.json()["items"]}


def test_default_list_serves_live_statuses_only(cid_all_statuses):
    codes = _list_codes(cid_all_statuses)
    # Positive pin: live statuses are present, not just "dead ones absent".
    assert codes == {"MAT_ACTIVE", "MAT_UNDER_REVIEW", "MAT_DEPRECATED"}


def test_explicit_status_param_opts_into_dead_rows(cid_all_statuses):
    assert _list_codes(cid_all_statuses, status="tombstoned") == {"MAT_TOMBSTONED"}
    assert _list_codes(cid_all_statuses, status="inactive") == {"MAT_INACTIVE"}


def _get(cid, code, **params):
    return _client().get(
        f"/v1/hub/materials/{code}", params={"client_id": cid, **params}
    )


def test_get_by_code_404s_on_dead_material_by_default(cid_all_statuses):
    # CO degrades gracefully on 404 (data_hub_client.get_material → {}).
    assert _get(cid_all_statuses, "MAT_TOMBSTONED").status_code == 404
    assert _get(cid_all_statuses, "MAT_INACTIVE").status_code == 404


def test_get_by_code_serves_live_statuses_by_default(cid_all_statuses):
    for code in ("MAT_ACTIVE", "MAT_UNDER_REVIEW", "MAT_DEPRECATED"):
        r = _get(cid_all_statuses, code)
        assert r.status_code == 200, (code, r.text)
        assert r.json()["material_code"] == code


def test_get_by_code_explicit_status_opts_into_dead_row(cid_all_statuses):
    r = _get(cid_all_statuses, "MAT_TOMBSTONED", status="tombstoned")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "tombstoned"
    # An explicit status is a single-status filter, not a bypass.
    assert _get(cid_all_statuses, "MAT_TOMBSTONED", status="active").status_code == 404
