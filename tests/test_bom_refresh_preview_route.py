"""Phase 3 G — GET /clients/{cid}/bom/artifact/{aid}/refresh/preview.

Renders the would-be conversion plan from `plan_refresh` so staff
can inspect per-row factor + source + target before confirming.

Spec: `.ai/features/2026-05-13-bom-refresh-preview/brief.md` scope item 2.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.auth.session import create_session, hash_password, SESSION_COOKIE
from app.database import connect
from app.main import app


CLIENT = "_preview_route_test"
USER_ID = "_preview_route_user"
USER_EMAIL = "preview_route@test.local"


def _seed_client(cur):
    cur.execute(
        "insert into hub.clients (client_id, name) values (%s, %s) "
        "on conflict (client_id) do nothing",
        (CLIENT, "preview-route test"),
    )


def _seed_material(cur, code: str, *, category: str = "nvl",
                    uom: str = "KG"):
    cur.execute(
        "insert into hub.materials (client_id, material_code, name, "
        "category, status, uom) values (%s, %s, %s, %s, 'active', %s) "
        "on conflict (client_id, material_code) do update set "
        "uom=excluded.uom",
        (CLIENT, code, code, category, uom),
    )


def _insert_raw_artifact(cur, artifact_id: str, product_code: str,
                          edges: list[tuple[str, str, float, str]]) -> None:
    cur.execute(
        "insert into hub.bom_artifacts (artifact_id, client_id, "
        "product_code, artifact_no, status, actor, intent, "
        "context, normalized_hash, row_count, source_bom_kind, "
        "flatten_status, flatten_strategy, source_channel, "
        "bom_variant_id, lineage, flatten_method, "
        "flatten_method_version, published_at) "
        "values (%s, %s, %s, 1, 'published', 'agency_staff', "
        "'asserted_technical', '{}', %s, %s, 'technical_raw', "
        "'non_flattened', 'no_strategy', 'agency_upload', "
        "'default', '{}', 'as_provided', 'v1', now())",
        (artifact_id, CLIENT, product_code, f"h_{artifact_id}", len(edges)),
    )
    for idx, (parent, child, qty, uom) in enumerate(edges):
        cur.execute(
            "insert into hub.bom_edges (artifact_id, row_index, root_code, "
            "parent_code, child_code, qty_per_parent, uom) "
            "values (%s, %s, %s, %s, %s, %s, %s)",
            (artifact_id, idx, product_code, parent, child, qty, uom),
        )


def _insert_derived_stale(cur, artifact_id: str, product_code: str) -> None:
    reasons = [{"dim": "catalog_category", "source_table": "hub.materials",
                "source_pk": f"{CLIENT}/seed",
                "observed_at": "2026-05-12T00:00:00Z"}]
    cur.execute(
        "insert into hub.bom_artifacts (artifact_id, client_id, "
        "product_code, artifact_no, status, actor, intent, "
        "context, normalized_hash, row_count, source_bom_kind, "
        "flatten_status, flatten_strategy, source_channel, "
        "bom_variant_id, lineage, flatten_method, "
        "flatten_method_version, published_at, is_stale, "
        "stale_reasons, stale_first_at) "
        "values (%s, %s, %s, 1, 'published', 'agency_staff', "
        "'derived', '{}', %s, 0, 'technical_flattened', "
        "'flattened', 'technical_exploded', 'migration', 'default', "
        "'{}', 'recursive_sql', '1', now(), true, %s::jsonb, now())",
        (artifact_id, CLIENT, product_code, f"h_{artifact_id}",
         json.dumps(reasons)),
    )


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        _seed_client(cur)
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
            (CLIENT,))
        cur.execute(
            "delete from hub.bom_edges where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (CLIENT,))
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.client_uom_overrides where client_id=%s",
                    (CLIENT,))
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.sessions where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.users where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


@pytest.fixture
def http():
    sid = create_session(USER_ID)
    c = TestClient(app, follow_redirects=False)
    c.cookies.set(SESSION_COOKIE, sid)
    return c


def test_preview_route_renders_plan_with_blocked_row(http):
    """Tier-B fixture → preview shows the row's source UoM, target UoM,
    and a `blocked_no_factor` status marker."""
    raw_id = "ba_route_raw_b"
    derived_id = "ba_route_der_b"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_RB", category="tp", uom="KG")
        _seed_material(cur, "M_RB", category="nvl", uom="KG")
        _insert_raw_artifact(cur, raw_id, "TP_RB",
                              edges=[("TP_RB", "M_RB", 7.0, "EA")])
        _insert_derived_stale(cur, derived_id, "TP_RB")

    r = http.get(
        f"/clients/{CLIENT}/bom/artifact/{derived_id}/refresh/preview")
    assert r.status_code == 200, r.text
    body = r.text
    assert "M_RB" in body, "row material_code must appear"
    assert "EA" in body and "KG" in body, "source + target UoM must appear"
    assert 'data-plan-row-status="blocked_no_factor"' in body, (
        "status badge marker missing — need stable selector for tests"
    )


def test_preview_route_404_unknown_artifact(http):
    r = http.get(
        f"/clients/{CLIENT}/bom/artifact/ba_does_not_exist/refresh/preview")
    assert r.status_code == 404


def test_preview_route_404_cross_tenant(http):
    raw_id = "ba_route_xtenant_raw"
    derived_id = "ba_route_xtenant_der"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_X", category="tp", uom="kg")
        _seed_material(cur, "M_X", category="nvl", uom="kg")
        _insert_raw_artifact(cur, raw_id, "TP_X",
                              edges=[("TP_X", "M_X", 1.0, "kg")])
        _insert_derived_stale(cur, derived_id, "TP_X")

    r = http.get(
        f"/clients/a_different_client/bom/artifact/{derived_id}/refresh/preview")
    # Either 403 (forbidden — not member) or 404 (not in this client's
    # tree). Both are acceptable; the contract is "do not leak data
    # cross-tenant".
    assert r.status_code in (403, 404)
