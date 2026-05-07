"""Vocab rename pass: schema + URL alias guarantees.

Locks in the canonical rename (mig 031, 2026-05-07):
- bom_versions → bom_artifacts
- bom_resolution_profiles → bom_presets
- column renames per .ai/GLOSSARY.md
- Old URL paths 308-redirect to new paths for one release (D10).

These tests are the safety net for the alias-removal milestone tracked
in .ai/BACKLOG.md "Drop BOM vocab v1 aliases" — when the aliases are
removed, the redirect tests should be deleted (not fixed). The schema
tests stay forever.
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


CLIENT = "vocab_rename_test"


@pytest.fixture(autouse=True)
def isolated_keys_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DATA_HUB_KEYS_DIR", d)
        yield Path(d)


@pytest.fixture(autouse=True)
def setup_client():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (CLIENT, "vocab rename test"),
        )
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id = %s", (CLIENT,))


def _bearer():
    out = jwt_issuer.make_token(
        user_id="u_vocab", email="v@e", role="admin", display_name="V",
    )
    return {"authorization": f"Bearer {out['access_token']}"}


# ─────────────────────────────────────────────────────────────────────
# Schema — new names exist, old names don't
# ─────────────────────────────────────────────────────────────────────


def test_bom_artifacts_table_exists_with_new_columns():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema='hub' and table_name='bom_artifacts'"
        )
        cols = {r[0] for r in cur.fetchall()}
    assert "artifact_id" in cols
    assert "artifact_no" in cols
    assert "parent_artifact_id" in cols
    # Old names gone
    assert "version_id" not in cols
    assert "version_no" not in cols
    assert "parent_version_id" not in cols


def test_bom_presets_table_exists_with_renamed_columns():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema='hub' and table_name='bom_presets'"
        )
        cols = {r[0] for r in cur.fetchall()}
    assert cols, "bom_presets table missing"
    assert "preset_id" in cols
    assert "artifact_id" in cols
    assert "profile_id" not in cols
    assert "bom_version_id" not in cols


def test_old_table_names_dropped():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema='hub' and table_name in "
            "('bom_versions', 'bom_version_rows', 'bom_resolution_profiles')"
        )
        survivors = [r[0] for r in cur.fetchall()]
    assert survivors == [], f"old table names still in schema: {survivors}"


def test_bcct_rows_artifact_id_column():
    """bcct_rows.bom_version_id renamed to artifact_id (mig 031 §9b)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema='hub' and table_name='bcct_rows' "
            "and column_name in ('artifact_id', 'bom_version_id')"
        )
        names = {r[0] for r in cur.fetchall()}
    assert "artifact_id" in names
    assert "bom_version_id" not in names


# ─────────────────────────────────────────────────────────────────────
# URL alias — 308 redirect, one-release grace (D10)
# ─────────────────────────────────────────────────────────────────────
# Auth is required on the destination route, but the redirect itself
# should fire before auth check on the alias path. We use a plain
# unauthenticated client and assert 308 + Location.


def test_old_bom_artifacts_list_url_redirects_308():
    c = TestClient(app, follow_redirects=False)
    r = c.get(f"/clients/{CLIENT}/bom/INV-3000/versions")
    assert r.status_code == 308
    assert r.headers["location"].endswith(
        f"/clients/{CLIENT}/bom/INV-3000/artifacts"
    )


def test_old_bom_artifact_detail_url_redirects_308():
    c = TestClient(app, follow_redirects=False)
    r = c.get(f"/clients/{CLIENT}/bom/version/ba_some_id")
    assert r.status_code == 308
    assert r.headers["location"].endswith(
        f"/clients/{CLIENT}/bom/artifact/ba_some_id"
    )


def test_old_api_bom_versions_url_redirects_308():
    c = TestClient(app, follow_redirects=False)
    r = c.get(
        f"/v1/hub/products/INV-3000/bom/versions?client_id={CLIENT}",
        headers=_bearer(),
    )
    assert r.status_code == 308
    assert "/v1/hub/products/INV-3000/bom/artifacts" in r.headers["location"]


# ─────────────────────────────────────────────────────────────────────
# ID prefix — new artifacts mint with ba_ (D8)
# ─────────────────────────────────────────────────────────────────────


def test_new_artifact_ids_use_ba_prefix():
    """Forward-only: existing bv_* ids untouched, new rows minted ba_*."""
    from app.stores import bom as bom_store
    bom_store.create_artifact(
        client_id=CLIENT, product_code="VOCAB_PROD",
        rows=[{"material_code": "MAT_X", "qty_per_unit": 1, "uom": "kg"}],
        actor="agency_staff", intent="asserted_technical",
        parent_artifact_id=None, context={}, source_upload_id=None,
        source_bom_kind="technical_flattened",
        flatten_status="flattened",
        flatten_strategy="technical_exploded",
    )
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select artifact_id from hub.bom_artifacts "
            "where client_id=%s and product_code=%s",
            (CLIENT, "VOCAB_PROD"),
        )
        ids = [r[0] for r in cur.fetchall()]
    assert ids, "no artifact created"
    assert all(i.startswith("ba_") for i in ids), ids
