"""API hardening tests for /v1/hub/products/{p}/bom/latest after flatten
shipped. Spec items: 23 (latest is safe — never returns non_flattened or
mixes dual-source variants), 27 (public API contract change tested).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from app import auth, jwt_issuer, settings_store
from app.database import connect
from app.main import app
from app.stores import bom as bom_store


CLIENT = "flat_test_api"


@pytest.fixture(autouse=True)
def isolated_keys_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DATA_HUB_KEYS_DIR", d)
        yield Path(d)


@pytest.fixture(autouse=True)
def setup_client():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.clients (client_id, name)
                values (%s, %s) on conflict (client_id) do nothing
                """,
                (CLIENT, "flatten api test"),
            )
    yield
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.clients where client_id = %s", (CLIENT,))


def _bearer():
    out = jwt_issuer.make_token(
        user_id="u_flat_api", email="t@e", role="admin", display_name="T",
    )
    return {"authorization": f"Bearer {out['access_token']}"}


def _client_http():
    return TestClient(app)


def _make_version(product, *, status, strategy, kind="technical_flattened",
                  rows=None):
    bom_store.create_artifact(
        client_id=CLIENT, product_code=product,
        rows=rows or [{"material_code": "FT_A_X", "qty_per_unit": 1, "uom": "kg"}],
        actor="agency_staff", intent="asserted_technical",
        parent_artifact_id=None, context={}, source_upload_id=None,
        source_bom_kind=kind,
        flatten_status=status,
        flatten_strategy=strategy,
    )


# ── Item 23 — /latest excludes non_flattened ──────────────────────────

def test_latest_excludes_non_flattened():
    _make_version("FT_A_TP", status="non_flattened",
                  strategy="no_strategy", kind="technical_non_flattened")
    r = _client_http().get(
        f"/v1/hub/products/FT_A_TP/bom/latest?client_id={CLIENT}",
        headers=_bearer(),
    )
    assert r.status_code == 404


def test_latest_returns_flattened():
    _make_version("FT_A_FLAT", status="flattened",
                  strategy="technical_exploded")
    r = _client_http().get(
        f"/v1/hub/products/FT_A_FLAT/bom/latest?client_id={CLIENT}",
        headers=_bearer(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["artifact"]["flatten_status"] == "flattened"
    assert body["artifact"]["flatten_strategy"] == "technical_exploded"
    assert body["artifact"]["source_bom_kind"] == "technical_flattened"
    assert body["artifact"]["display_label"]
    assert "unresolved" in body
    assert "decisions" in body


def test_latest_returns_manual_flat_not_applicable():
    """Backward-compat: manual_flat versions backfilled to flatten_status=
    not_applicable still resolve via /latest."""
    _make_version("FT_A_LEGACY", status="not_applicable",
                  strategy="manual_flat_as_provided", kind="manual_flat")
    r = _client_http().get(
        f"/v1/hub/products/FT_A_LEGACY/bom/latest?client_id={CLIENT}",
        headers=_bearer(),
    )
    assert r.status_code == 200
    assert r.json()["artifact"]["flatten_status"] == "not_applicable"


# ── Item 27 — dual-source returns 409 with variant list ──────────────

def test_latest_returns_409_for_dual_source():
    _make_version("FT_A_DUAL", status="flattened",
                  strategy="purchased_btp_as_leaf",
                  rows=[{"material_code": "FT_BTP", "qty_per_unit": 1, "uom": "kg"}])
    _make_version("FT_A_DUAL", status="flattened",
                  strategy="self_produced_btp_exploded",
                  rows=[{"material_code": "FT_NVL", "qty_per_unit": 0.5, "uom": "kg"}])
    r = _client_http().get(
        f"/v1/hub/products/FT_A_DUAL/bom/latest?client_id={CLIENT}",
        headers=_bearer(),
    )
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "dual_source_variants"
    strategies = sorted(v["flatten_strategy"] for v in body["variants"])
    assert strategies == ["purchased_btp_as_leaf", "self_produced_btp_exploded"]
    # Each variant carries an explicit artifact_id the caller must rebind to.
    for v in body["variants"]:
        assert v["artifact_id"]
        assert v["display_label"]


def test_dual_source_pinned_via_artifact_id():
    """Caller binds explicitly via /v1/hub/products/{p}/bom?artifact_id=… —
    that endpoint already exists and works. Verify it returns the picked
    variant unambiguously."""
    _make_version("FT_A_PIN", status="flattened",
                  strategy="purchased_btp_as_leaf",
                  rows=[{"material_code": "FT_PIN_BTP", "qty_per_unit": 1, "uom": "kg"}])
    _make_version("FT_A_PIN", status="flattened",
                  strategy="self_produced_btp_exploded",
                  rows=[{"material_code": "FT_PIN_NVL", "qty_per_unit": 1, "uom": "kg"}])
    r = _client_http().get(
        f"/v1/hub/products/FT_A_PIN/bom/latest?client_id={CLIENT}",
        headers=_bearer(),
    )
    pick = r.json()["variants"][0]
    r2 = _client_http().get(
        f"/v1/hub/products/FT_A_PIN/bom?client_id={CLIENT}&artifact_id={pick['artifact_id']}",
        headers=_bearer(),
    )
    assert r2.status_code == 200
    assert r2.json()["artifact"]["artifact_id"] == pick["artifact_id"]
    assert r2.json()["artifact"]["flatten_strategy"] == pick["flatten_strategy"]
