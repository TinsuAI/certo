"""Phase 3b · GET /v1/hub/products/{p}/bom wired to resolver.

The endpoint accepts ?preset_id, ?case_id, ?shape (precedence per
resolver). Returns the artifact + resolution_trail. Errors map to
4xx via _raise_resolver_http.
"""
from __future__ import annotations

import pytest
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

from hub.app import jwt_issuer
from hub.app.database import connect
from hub.app.main import app


CLIENT = "endpoint_resolver_test"
PRODUCT = "TP_ENDR"
ARTIFACT = "ba_endpoint_resolver_target"


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
            (CLIENT, "endpoint resolver"),
        )
        cur.execute(
            "insert into hub.users (user_id, email, password_hash, role, display_name) "
            "values ('u_endr', 'e@e', '', 'admin', 'E') on conflict do nothing"
        )
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, product_code, "
            "artifact_no, actor, intent, normalized_hash, source_bom_kind, "
            "flatten_status, flatten_strategy, source_channel, flatten_method, "
            "flatten_method_version, status, published_at) "
            "values (%s, %s, %s, 1, 'agency_staff', "
            "'asserted_technical', 'h_endr', 'technical_flattened', 'flattened', "
            "'technical_exploded', 'agency_upload', 'manual', '0.1', "
            "'published', now()) "
            "on conflict do nothing",
            (ARTIFACT, CLIENT, PRODUCT),
        )
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bom_presets where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.users where user_id='u_endr'")


def _bearer():
    out = jwt_issuer.make_token(
        user_id="u_endr", email="e@e", role="admin", display_name="E",
    )
    return {"authorization": f"Bearer {out['access_token']}"}


def _http():
    return TestClient(app)


def _create_preset(name="default"):
    r = _http().post(
        "/v1/hub/presets", headers=_bearer(),
        json={"client_id": CLIENT, "product_code": PRODUCT,
              "artifact_id": ARTIFACT, "name": name},
    )
    assert r.status_code == 201, r.text
    return r.json()["preset_id"]


def test_endpoint_with_preset_returns_artifact_and_trail():
    pid = _create_preset()
    r = _http().get(
        f"/v1/hub/products/{PRODUCT}/bom?client_id={CLIENT}&preset_id={pid}",
        headers=_bearer(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["artifact"]["artifact_id"] == ARTIFACT
    assert "resolution_trail" in body
    assert any("preset" in s for s in body["resolution_trail"])


def test_endpoint_with_shape_filter_returns_artifact():
    r = _http().get(
        f"/v1/hub/products/{PRODUCT}/bom?client_id={CLIENT}&shape=full_flat",
        headers=_bearer(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["artifact"]["artifact_id"] == ARTIFACT
    assert body["shape"] == "full_flat"


def test_endpoint_with_unknown_preset_404():
    r = _http().get(
        f"/v1/hub/products/{PRODUCT}/bom?client_id={CLIENT}&preset_id=bp_missing",
        headers=_bearer(),
    )
    assert r.status_code == 404
    body = r.json()
    assert body["detail"]["error"] == "preset_not_found"


def test_endpoint_with_no_match_for_shape_404():
    r = _http().get(
        f"/v1/hub/products/{PRODUCT}/bom?client_id={CLIENT}&shape=raw_graph",
        headers=_bearer(),
    )
    assert r.status_code == 404
    body = r.json()
    assert body["detail"]["error"] == "no_artifact_for_shape"


def test_endpoint_artifact_id_pin_still_works():
    """Backward-compat: existing ?artifact_id= path unchanged."""
    r = _http().get(
        f"/v1/hub/products/{PRODUCT}/bom?client_id={CLIENT}&artifact_id={ARTIFACT}",
        headers=_bearer(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["artifact"]["artifact_id"] == ARTIFACT
    # No resolution_trail when raw artifact_id pin (no resolver invoked)
    assert "resolution_trail" not in body
