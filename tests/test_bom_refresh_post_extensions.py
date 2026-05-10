"""Phase 3 G — POST /clients/{cid}/bom/artifact/{aid}/refresh extensions.

New form fields:
- `skip=1`: skip refresh + log refresh.skipped audit event (no state change).
- `confirm=1`: explicit confirmation from preview page.
- `inline_factor_<i>_<field>`: optional inline factor edits, applied
  to client_uom_overrides BEFORE the commit re-plans.

Spec: `.ai/features/2026-05-13-bom-refresh-preview/brief.md` scope item 3.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.auth.session import create_session, hash_password, SESSION_COOKIE
from app.database import connect
from app.main import app


CLIENT = "_post_ext_test"
USER_ID = "_post_ext_user"
USER_EMAIL = "post_ext@test.local"


def _seed_client(cur):
    cur.execute(
        "insert into hub.clients (client_id, name) values (%s, %s) "
        "on conflict (client_id) do nothing",
        (CLIENT, "post-ext test"),
    )


def _seed_material(cur, code, *, category="nvl", uom="KG"):
    cur.execute(
        "insert into hub.materials (client_id, material_code, name, "
        "category, status, uom) values (%s, %s, %s, %s, 'active', %s) "
        "on conflict (client_id, material_code) do update set uom=excluded.uom",
        (CLIENT, code, code, category, uom),
    )


def _insert_raw(cur, aid, product_code, edges):
    cur.execute(
        "insert into hub.bom_artifacts (artifact_id, client_id, "
        "product_code, artifact_no, status, actor, intent, context, "
        "normalized_hash, row_count, source_bom_kind, flatten_status, "
        "flatten_strategy, source_channel, bom_variant_id, lineage, "
        "flatten_method, flatten_method_version, published_at) "
        "values (%s, %s, %s, 1, 'published', 'agency_staff', "
        "'asserted_technical', '{}', %s, %s, 'technical_raw', "
        "'non_flattened', 'no_strategy', 'agency_upload', 'default', "
        "'{}', 'as_provided', 'v1', now())",
        (aid, CLIENT, product_code, f"h_{aid}", len(edges)),
    )
    for idx, (parent, child, qty, uom) in enumerate(edges):
        cur.execute(
            "insert into hub.bom_edges (artifact_id, row_index, root_code, "
            "parent_code, child_code, qty_per_parent, uom) "
            "values (%s, %s, %s, %s, %s, %s, %s)",
            (aid, idx, product_code, parent, child, qty, uom),
        )


def _insert_derived_stale(cur, aid, product_code):
    reasons = [{"dim": "catalog_category", "source_table": "hub.materials",
                "source_pk": f"{CLIENT}/seed",
                "observed_at": "2026-05-12T00:00:00Z"}]
    cur.execute(
        "insert into hub.bom_artifacts (artifact_id, client_id, "
        "product_code, artifact_no, status, actor, intent, context, "
        "normalized_hash, row_count, source_bom_kind, flatten_status, "
        "flatten_strategy, source_channel, bom_variant_id, lineage, "
        "flatten_method, flatten_method_version, published_at, "
        "is_stale, stale_reasons, stale_first_at) "
        "values (%s, %s, %s, 1, 'published', 'agency_staff', "
        "'derived', '{}', %s, 0, 'technical_flattened', 'flattened', "
        "'technical_exploded', 'migration', 'default', '{}', "
        "'recursive_sql', '1', now(), true, %s::jsonb, now())",
        (aid, CLIENT, product_code, f"h_{aid}", json.dumps(reasons)),
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
        cur.execute("delete from hub.bom_audit_events where client_id=%s",
                    (CLIENT,))
        cur.execute("delete from hub.sessions where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.users where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


@pytest.fixture
def http():
    sid = create_session(USER_ID)
    c = TestClient(app, follow_redirects=False)
    c.cookies.set(SESSION_COOKIE, sid)
    return c


def test_post_skip_writes_audit_no_state_change(http):
    raw_id = "ba_post_skip_raw"
    derived_id = "ba_post_skip_der"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_PS", category="tp", uom="KG")
        _seed_material(cur, "M_PS", category="nvl", uom="KG")
        _insert_raw(cur, raw_id, "TP_PS",
                     edges=[("TP_PS", "M_PS", 5.0, "EA")])
        _insert_derived_stale(cur, derived_id, "TP_PS")

    r = http.post(
        f"/clients/{CLIENT}/bom/artifact/{derived_id}/refresh",
        data={"skip": "1"},
    )
    assert r.status_code in (303, 302), r.text

    with connect() as conn, conn.cursor() as cur:
        cur.execute("select is_stale from hub.bom_artifacts "
                    "where artifact_id=%s", (derived_id,))
        assert cur.fetchone()[0] is True
        cur.execute(
            "select count(*) from hub.bom_audit_events "
            "where client_id=%s and event_type='refresh.skipped' "
            "  and artifact_id=%s",
            (CLIENT, derived_id))
        assert cur.fetchone()[0] == 1


def test_post_inline_factor_persists_then_refreshes(http):
    raw_id = "ba_post_inl_raw"
    derived_id = "ba_post_inl_der"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_IN", category="tp", uom="KG")
        _seed_material(cur, "M_IN", category="nvl", uom="KG")
        _insert_raw(cur, raw_id, "TP_IN",
                     edges=[("TP_IN", "M_IN", 100.0, "EA")])
        _insert_derived_stale(cur, derived_id, "TP_IN")

    r = http.post(
        f"/clients/{CLIENT}/bom/artifact/{derived_id}/refresh",
        data={
            "confirm": "1",
            "inline_factor_0_material_code": "M_IN",
            "inline_factor_0_from_uom": "EA",
            "inline_factor_0_to_uom": "KG",
            "inline_factor_0_factor": "0.25",
        },
    )
    assert r.status_code in (303, 302), r.text

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select factor from hub.client_uom_overrides "
            "where client_id=%s and material_code='M_IN' "
            "  and from_uom='EA' and to_uom='KG'",
            (CLIENT,))
        row = cur.fetchone()
        assert row is not None, "inline factor must persist"
        assert float(row[0]) == pytest.approx(0.25)


def test_post_no_extra_params_still_works(http):
    """Existing direct-POST contract preserved (no preview)."""
    raw_id = "ba_post_back_raw"
    derived_id = "ba_post_back_der"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_BC", category="tp", uom="kg")
        _seed_material(cur, "M_BC", category="nvl", uom="kg")
        _insert_raw(cur, raw_id, "TP_BC",
                     edges=[("TP_BC", "M_BC", 2500.0, "g")])
        _insert_derived_stale(cur, derived_id, "TP_BC")

    r = http.post(
        f"/clients/{CLIENT}/bom/artifact/{derived_id}/refresh")
    assert r.status_code in (303, 302), r.text
    # Old artifact tombstoned (hash diff because of g→kg conversion).
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select tombstoned_at from hub.bom_artifacts where artifact_id=%s",
            (derived_id,))
        assert cur.fetchone()[0] is not None
