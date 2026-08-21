"""Track D Phase D — UI badges + API exposure for stale BOM artifacts.

API: GET /api/v1/products/{product_code}/bom?artifact_id=<id> response
includes is_stale + stale_reasons in artifact dict.

UI: bom_artifacts.html row + bom_artifact_detail.html section render
a "stale" badge when is_stale=true.

Spec: `.ai/features/2026-05-11-bom-staleness-track-d/brief.md`,
"UI surface" + "API surface (BCQT/CO consumer)" sections.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from hub.app.auth.session import create_session, hash_password, SESSION_COOKIE
from hub.app.database import connect
from hub.app.main import app


CLIENT = "track_d_uiapi_test"
USER_ID = "test_track_d_uiapi_user"
USER_EMAIL = "track_d_uiapi@test.local"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (CLIENT, "Track D ui+api test"),
        )
        cur.execute(
            "insert into hub.users (user_id, email, display_name, "
            "password_hash, role, status) values (%s, %s, 'tester', %s, "
            "'admin', 'active') on conflict (user_id) do update set "
            "role='admin', status='active'",
            (USER_ID, USER_EMAIL, hash_password("test-password")),
        )
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.bom_artifact_rows where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (CLIENT,),
        )
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.sessions where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.users where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


@pytest.fixture
def http():
    sid = create_session(USER_ID)
    c = TestClient(app, follow_redirects=False)
    c.cookies.set(SESSION_COOKIE, sid)
    return c


def _insert_stale(artifact_id: str, *, is_stale: bool = True,
                   product_code: str = "P_UI") -> None:
    reasons = [{"dim": "catalog_category",
                 "source_table": "hub.materials",
                 "source_pk": f"{CLIENT}/M-X",
                 "observed_at": "2026-05-11T00:00:00Z"}]
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            "product_code, artifact_no, status, actor, intent, "
            "context, normalized_hash, row_count, source_bom_kind, "
            "flatten_status, flatten_strategy, source_channel, "
            "bom_variant_id, lineage, flatten_method, "
            "flatten_method_version, published_at, is_stale, "
            "stale_reasons) values (%s, %s, %s, 1, 'published', "
            "'agency_staff', 'asserted_technical', '{}', %s, 0, "
            "'technical_flattened', 'flattened', 'technical_exploded', "
            "'staff_form', 'default', '{}', 'as_provided', 'v1', "
            "now(), %s, %s::jsonb)",
            (artifact_id, CLIENT, product_code, f"h_{artifact_id}",
             is_stale, json.dumps(reasons if is_stale else [])),
        )
        conn.commit()


# ────────────────────────────────────────────────────────────────────
# API: artifact endpoint exposes is_stale + stale_reasons.
# ────────────────────────────────────────────────────────────────────


def _bearer_token() -> str:
    from hub.app import jwt_issuer
    return jwt_issuer.make_token(
        user_id=USER_ID, email=USER_EMAIL, role="admin",
        display_name="API tester",
    )["access_token"]


def test_api_artifact_endpoint_includes_is_stale(http):
    aid = "ba_api_stale"
    _insert_stale(aid, is_stale=True)
    token = _bearer_token()

    r = http.get(
        f"/v1/hub/products/P_UI/bom?client_id={CLIENT}&artifact_id={aid}",
        headers={"authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    artifact = body["artifact"]
    assert artifact["is_stale"] is True, (
        f"Artifact dict must expose is_stale; keys={list(artifact.keys())}"
    )
    assert "stale_reasons" in artifact
    assert isinstance(artifact["stale_reasons"], list)
    assert len(artifact["stale_reasons"]) == 1
    assert artifact["stale_reasons"][0]["dim"] == "catalog_category"


def test_api_artifact_endpoint_is_stale_false_when_fresh(http):
    aid = "ba_api_fresh"
    _insert_stale(aid, is_stale=False)
    token = _bearer_token()

    r = http.get(
        f"/v1/hub/products/P_UI/bom?client_id={CLIENT}&artifact_id={aid}",
        headers={"authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    artifact = r.json()["artifact"]
    assert artifact["is_stale"] is False
    assert artifact["stale_reasons"] == []


def test_api_list_artifacts_includes_uom_drift_fields(http):
    aid_drift = "ba_list_uom_drift"
    aid_clean = "ba_list_uom_clean"
    _insert_stale(aid_drift, is_stale=False, product_code="P_LIST_UOM")
    _insert_stale(aid_clean, is_stale=False, product_code="P_LIST_UOM")
    drift_reason = [{"dim": "materials_uom",
                     "source_table": "hub.materials",
                     "source_pk": f"{CLIENT}/M-X",
                     "material_code": "M-X",
                     "observed_at": "2026-05-12T00:00:00Z"}]
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.bom_artifacts set has_uom_drift=true, "
            "uom_drift_reasons=%s::jsonb, uom_drift_first_at=now() "
            "where artifact_id=%s",
            (json.dumps(drift_reason), aid_drift),
        )
        conn.commit()
    token = _bearer_token()

    r = http.get(
        f"/v1/hub/products/P_LIST_UOM/bom/artifacts?client_id={CLIENT}",
        headers={"authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    items = {it["artifact_id"]: it for it in r.json()["items"]}
    assert aid_drift in items and aid_clean in items
    assert items[aid_drift]["has_uom_drift"] is True, (
        "List endpoint must expose has_uom_drift; "
        f"keys={list(items[aid_drift].keys())}"
    )
    assert items[aid_drift]["uom_drift_reasons"][0]["dim"] == "materials_uom"
    assert items[aid_clean]["has_uom_drift"] is False
    assert items[aid_clean]["uom_drift_reasons"] == []


# ────────────────────────────────────────────────────────────────────
# UI: stale badge appears in bom_artifact_detail page.
# ────────────────────────────────────────────────────────────────────


def test_artifact_detail_renders_stale_badge_when_stale(http):
    aid = "ba_ui_stale"
    _insert_stale(aid, is_stale=True)

    r = http.get(f"/clients/{CLIENT}/bom/artifact/{aid}")
    assert r.status_code == 200, r.text
    body = r.text
    # Use the stable i18n key for the badge so the test doesn't break
    # on copy edits.
    assert 'data-stale-badge="1"' in body, (
        "Detail page must render a stale badge (look for "
        "data-stale-badge=\"1\" element). HTML lacks the marker."
    )
    # Refresh button should be present.
    assert "refresh" in body.lower(), (
        "Detail page must offer a refresh button when artifact is stale."
    )


def test_artifact_detail_no_stale_badge_when_fresh(http):
    aid = "ba_ui_fresh"
    _insert_stale(aid, is_stale=False)

    r = http.get(f"/clients/{CLIENT}/bom/artifact/{aid}")
    assert r.status_code == 200
    assert 'data-stale-badge="1"' not in r.text


def test_artifacts_list_renders_per_row_stale_marker(http):
    aid_stale = "ba_list_stale"
    aid_fresh = "ba_list_fresh"
    _insert_stale(aid_stale, is_stale=True, product_code="P_LIST")
    _insert_stale(aid_fresh, is_stale=False, product_code="P_LIST")

    r = http.get(f"/clients/{CLIENT}/bom/P_LIST/artifacts")
    assert r.status_code == 200, r.text
    # Stable marker on the stale row only.
    assert 'data-stale-row="ba_list_stale"' in r.text
    assert 'data-stale-row="ba_list_fresh"' not in r.text


# ─── _primary_action: manual_flat refresh fix (audit 2026-05-27) ───────


def test_primary_action_manual_flat_uom_drift_uses_refresh():
    """manual_flat sources CAN be refreshed (re-applies uom conversion via
    _rederive_manual_flat, mig 057). UI must surface 'refresh' button, not
    'reupload'. Bug from initial Phase 2 ship: source+uom_drift hardcoded
    to reupload regardless of kind."""
    from hub.app.routes.bom import _primary_action
    assert _primary_action({"uom_drift"}, is_source=True,
                            source_bom_kind="manual_flat") == "refresh"


def test_primary_action_technical_raw_uom_drift_uses_reupload():
    """raw_graph edges are immutable; refresh path returns
    skipped='source_artifact'. Reupload is the only way to clear."""
    from hub.app.routes.bom import _primary_action
    assert _primary_action({"uom_drift"}, is_source=True,
                            source_bom_kind="technical_raw") == "reupload"


def test_primary_action_derived_dependency_uses_refresh():
    from hub.app.routes.bom import _primary_action
    assert _primary_action({"dependency"}, is_source=False) == "refresh"


def test_primary_action_derived_uom_drift_uses_fix_uom():
    from hub.app.routes.bom import _primary_action
    assert _primary_action({"uom_drift"}, is_source=False) == "fix_uom"


# ─── New /needs-action + /audit-log routes (audit 2026-05-27) ─────────


def test_needs_action_renders_clusters(http):
    """Cluster page groups artifacts by (cause, related_code)."""
    # Pre-seed: 2 artifacts flagged with same cause+material → one cluster.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category, status, uom) values (%s, %s, %s, 'nvl', 'active', 'kg') "
            "on conflict do nothing",
            (CLIENT, "M_NA1", "Mã thử"))
        for aid in ("ba_na1", "ba_na2"):
            cur.execute(
                "insert into hub.bom_artifacts (artifact_id, client_id, "
                "product_code, artifact_no, status, actor, intent, "
                "context, normalized_hash, row_count, source_bom_kind, "
                "flatten_status, flatten_strategy, source_channel, "
                "bom_variant_id, lineage, flatten_method, "
                "flatten_method_version, published_at, is_stale, "
                "stale_reasons) values (%s, %s, %s, 1, 'published', "
                "'agency_staff', 'asserted_technical', '{}', %s, 0, "
                "'technical_flattened', 'flattened', 'technical_exploded', "
                "'staff_form', 'default', '{}', 'as_provided', 'v1', "
                "now(), true, %s::jsonb)",
                (aid, CLIENT, f"P_{aid}", f"h_{aid}",
                 json.dumps([{"dim": "materials_uom",
                               "material_code": "M_NA1",
                               "source_table": "hub.materials",
                               "source_pk": f"{CLIENT}/M_NA1",
                               "observed_at": "2026-05-27T00:00:00Z"}])))
            cur.execute(
                "insert into hub.bom_artifact_rows (artifact_id, row_index, "
                "material_code, qty_per_unit, uom) values "
                "(%s, 0, 'M_NA1', 1.0, 'EA')", (aid,))
    r = http.get(f"/clients/{CLIENT}/bom/needs-action")
    assert r.status_code == 200, r.text
    # One cluster row covering M_NA1 with 2 BOMs.
    assert "M_NA1" in r.text
    assert "2" in r.text  # cluster size
    # Friendly cause label rendered (not raw dim).
    assert "Đơn vị trong danh mục đã đổi" in r.text


def test_audit_log_renders(http):
    """Audit log lists same events as forensic history."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            "product_code, artifact_no, status, actor, intent, "
            "context, normalized_hash, row_count, source_bom_kind, "
            "flatten_status, flatten_strategy, source_channel, "
            "bom_variant_id, lineage, flatten_method, "
            "flatten_method_version, published_at, is_stale, "
            "stale_reasons) values ('ba_al', %s, 'P_AL', 1, 'published', "
            "'agency_staff', 'asserted_technical', '{}', 'h_al', 0, "
            "'technical_flattened', 'flattened', 'technical_exploded', "
            "'staff_form', 'default', '{}', 'as_provided', 'v1', "
            "now(), true, %s::jsonb)",
            (CLIENT,
             json.dumps([{"dim": "catalog_category",
                           "source_table": "hub.materials",
                           "source_pk": f"{CLIENT}/M_AL",
                           "observed_at": "2026-05-27T10:00:00Z"}])))
    r = http.get(f"/clients/{CLIENT}/bom/audit-log")
    assert r.status_code == 200, r.text
    assert "Phân loại trong danh mục đã đổi" in r.text


def test_refresh_cluster_route_accepts_artifact_ids(http):
    """POST /refresh-cluster with comma-separated artifact_ids → redirect."""
    aid = "ba_rc"
    _insert_stale(aid, is_stale=True)
    r = http.post(
        f"/clients/{CLIENT}/bom/refresh-cluster",
        data={"artifact_ids": aid},
    )
    assert r.status_code == 303
    assert "/bom/needs-action" in r.headers["location"]


def test_api_artifact_endpoint_includes_state(http):
    """Mig 068 + sister-app contract: API exposes `state` field
    (clean / needs_refresh / needs_input / broken) additively. Existing
    is_stale + stale_reasons remain for backward compat."""
    aid = "ba_api_state"
    _insert_stale(aid, is_stale=True)
    token = _bearer_token()
    r = http.get(
        f"/v1/hub/products/P_UI/bom?client_id={CLIENT}&artifact_id={aid}",
        headers={"authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    artifact = r.json()["artifact"]
    assert "state" in artifact, (
        f"API must expose state; keys={list(artifact.keys())}"
    )
    # The seeded artifact has is_stale=true with dim=catalog_category
    # → needs_refresh (no needs_input dims present).
    assert artifact["state"] == "needs_refresh"
    # Backward-compat fields preserved.
    assert artifact["is_stale"] is True


def test_api_list_artifacts_includes_state(http):
    aid = "ba_api_st_list"
    _insert_stale(aid, is_stale=True, product_code="P_LIST_STATE")
    token = _bearer_token()
    r = http.get(
        f"/v1/hub/products/P_LIST_STATE/bom/artifacts?client_id={CLIENT}",
        headers={"authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items
    assert "state" in items[0]
    assert items[0]["state"] in {"clean", "needs_refresh", "needs_input",
                                  "broken"}
