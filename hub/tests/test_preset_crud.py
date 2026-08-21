"""Phase 3b · BOM preset CRUD endpoints.

Endpoints (all under /v1/hub/):
- POST /presets
- GET /clients/{c}/products/{p:path}/presets
- PATCH /presets/{preset_id}
- POST /presets/{preset_id}/tombstone

Auth: user JWT (not service). ID prefix `bp_*`. Tombstone is the
retraction mechanism — no DELETE per BOM-immutability principle.
"""
from __future__ import annotations

import pytest
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

from hub.app import jwt_issuer
from hub.app.database import connect
from hub.app.main import app


CLIENT = "preset_crud_test"
PRODUCT = "TP_PRESET"


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
            (CLIENT, "preset crud test"),
        )
        cur.execute(
            "insert into hub.users (user_id, email, password_hash, role, display_name) "
            "values ('u_pre', 'p@e', '', 'admin', 'P') on conflict do nothing"
        )
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, product_code, "
            "artifact_no, actor, intent, normalized_hash, source_bom_kind, "
            "flatten_status, flatten_strategy, source_channel, flatten_method, "
            "flatten_method_version, status, published_at) "
            "values ('ba_preset_target', %s, %s, 1, 'agency_staff', "
            "'asserted_technical', 'h', 'technical_flattened', 'flattened', "
            "'technical_exploded', 'agency_upload', 'manual', '0.1', "
            "'published', now()) "
            "on conflict do nothing",
            (CLIENT, PRODUCT),
        )
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bom_presets where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.users where user_id='u_pre'")


def _bearer():
    out = jwt_issuer.make_token(
        user_id="u_pre", email="p@e", role="admin", display_name="P",
    )
    return {"authorization": f"Bearer {out['access_token']}"}


def _http():
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────────
# CREATE
# ─────────────────────────────────────────────────────────────────────


def test_create_preset_returns_bp_prefix_id():
    r = _http().post(
        "/v1/hub/presets",
        headers=_bearer(),
        json={
            "client_id": CLIENT, "product_code": PRODUCT,
            "artifact_id": "ba_preset_target", "name": "default",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["preset_id"].startswith("bp_"), body
    assert body["name"] == "default"
    assert body["artifact_id"] == "ba_preset_target"


def test_create_preset_404_on_unknown_artifact():
    r = _http().post(
        "/v1/hub/presets",
        headers=_bearer(),
        json={
            "client_id": CLIENT, "product_code": PRODUCT,
            "artifact_id": "ba_does_not_exist", "name": "x",
        },
    )
    assert r.status_code == 404


def test_create_preset_409_on_artifact_scope_mismatch():
    """artifact_id must belong to (client_id, product_code)."""
    r = _http().post(
        "/v1/hub/presets",
        headers=_bearer(),
        json={
            "client_id": "wrong_client", "product_code": PRODUCT,
            "artifact_id": "ba_preset_target", "name": "x",
        },
    )
    assert r.status_code == 409


def test_create_preset_409_on_duplicate_name():
    """Name must be unique per (client, product) among alive presets."""
    c = _http()
    body = {"client_id": CLIENT, "product_code": PRODUCT,
            "artifact_id": "ba_preset_target", "name": "default"}
    r1 = c.post("/v1/hub/presets", headers=_bearer(), json=body)
    assert r1.status_code == 201
    r2 = c.post("/v1/hub/presets", headers=_bearer(), json=body)
    assert r2.status_code == 409


# ─────────────────────────────────────────────────────────────────────
# LIST
# ─────────────────────────────────────────────────────────────────────


def test_list_presets_empty_returns_200_with_empty_array():
    r = _http().get(
        f"/v1/hub/clients/{CLIENT}/products/{PRODUCT}/presets",
        headers=_bearer(),
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"items": []}


def test_list_presets_returns_alive_only():
    c = _http()
    a = c.post("/v1/hub/presets", headers=_bearer(),
               json={"client_id": CLIENT, "product_code": PRODUCT,
                     "artifact_id": "ba_preset_target", "name": "alive"})
    b = c.post("/v1/hub/presets", headers=_bearer(),
               json={"client_id": CLIENT, "product_code": PRODUCT,
                     "artifact_id": "ba_preset_target", "name": "to_tomb"})
    assert a.status_code == 201 and b.status_code == 201
    pid = b.json()["preset_id"]
    rt = c.post(f"/v1/hub/presets/{pid}/tombstone", headers=_bearer(),
                json={"reason": "oops"})
    assert rt.status_code == 200, rt.text

    r = c.get(
        f"/v1/hub/clients/{CLIENT}/products/{PRODUCT}/presets",
        headers=_bearer(),
    )
    assert r.status_code == 200
    items = r.json()["items"]
    names = {it["name"] for it in items}
    assert names == {"alive"}


# ─────────────────────────────────────────────────────────────────────
# PATCH
# ─────────────────────────────────────────────────────────────────────


def test_patch_preset_updates_fields():
    c = _http()
    r = c.post("/v1/hub/presets", headers=_bearer(),
               json={"client_id": CLIENT, "product_code": PRODUCT,
                     "artifact_id": "ba_preset_target", "name": "v0"})
    pid = r.json()["preset_id"]
    p = c.patch(
        f"/v1/hub/presets/{pid}", headers=_bearer(),
        json={"notes": "manually verified", "name": "v0_renamed"},
    )
    assert p.status_code == 200, p.text
    body = p.json()
    assert body["name"] == "v0_renamed"
    assert body["notes"] == "manually verified"


def test_patch_preset_404_on_unknown():
    p = _http().patch(
        "/v1/hub/presets/bp_does_not_exist", headers=_bearer(),
        json={"notes": "x"},
    )
    assert p.status_code == 404


# ─────────────────────────────────────────────────────────────────────
# TOMBSTONE
# ─────────────────────────────────────────────────────────────────────


def test_tombstone_marks_preset_retracted():
    c = _http()
    r = c.post("/v1/hub/presets", headers=_bearer(),
               json={"client_id": CLIENT, "product_code": PRODUCT,
                     "artifact_id": "ba_preset_target", "name": "tomb_me"})
    pid = r.json()["preset_id"]
    rt = c.post(f"/v1/hub/presets/{pid}/tombstone", headers=_bearer(),
                json={"reason": "wrong artifact"})
    assert rt.status_code == 200, rt.text
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select tombstoned_at, tombstone_reason from hub.bom_presets "
            "where preset_id=%s", (pid,),
        )
        ts, reason = cur.fetchone()
    assert ts is not None
    assert reason == "wrong artifact"


def test_tombstone_404_on_unknown():
    rt = _http().post(
        "/v1/hub/presets/bp_does_not_exist/tombstone", headers=_bearer(),
        json={"reason": "x"},
    )
    assert rt.status_code == 404
