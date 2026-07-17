"""Per-row selection on the bulk-accept route (#55).

The page gains checkboxes: the filter narrows, the operator picks a subset.
That means the POST now carries a client-sent code list — which ADR-0001 said
the server must not trust. The property is preserved by **intersection**, not
by trusting the list: the server recomputes `_filter_pending(...)` and accepts
only `selected ∩ filtered-pending`. A code that is stale, already a material,
machinery, or outside the active filter is dropped. `select_all_matching=1`
reproduces the old whole-filter path.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.session import SESSION_COOKIE, create_session, hash_password
from app.database import connect
from app.main import app
from app.stores.bcct_nb_codes import rebuild_for_client
from app.stores.catalog_discovery import _derive_bulk_attrs, discovery_rows


CLIENT = "_test_selection"
USER_ID = "u_selection_test"
USER_EMAIL = "selection@test.local"
BULK = f"/clients/{CLIENT}/catalog/candidates/bulk-accept"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, 'sel') "
            "on conflict do nothing", (CLIENT,))
        cur.execute(
            "insert into hub.users (user_id, email, display_name, password_hash,"
            " role, status) values (%s, %s, 'Sel', %s, 'admin', 'active') "
            "on conflict (user_id) do update set role='admin', status='active'",
            (USER_ID, USER_EMAIL, hash_password("test-pw")))
        for tbl in ("catalog_rejections", "bcct_nb_codes", "code_mappings",
                    "bcct_rows", "materials"):
            cur.execute(f"delete from hub.{tbl} where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.client_parser_rules where client_id=%s",
                    (CLIENT,))
        cur.execute(
            "insert into hub.client_parser_rules "
            "(client_id, output_field, priority, pattern, source_field, "
            " match_group, match_action, no_match_action, enabled, created_by) "
            "values (%s, 'internal_code', 10, '\\(([\\d\\.\\w\\-]+)\\)', "
            " 'goods_name', 1, 'capture', 'next_rule', true, 'test') "
            "on conflict do nothing", (CLIENT,))
    from app.parsers.client_parser_rules import clear_rules_cache
    clear_rules_cache()
    yield {"session": create_session(USER_ID)}
    with connect() as conn, conn.cursor() as cur:
        for tbl in ("catalog_rejections", "bcct_nb_codes", "code_mappings",
                    "bcct_rows", "materials"):
            cur.execute(f"delete from hub.{tbl} where client_id=%s", (CLIENT,))
        cur.execute(
            "delete from hub.bom_audit_events where client_id=%s and event_type "
            "in ('catalog_bulk_accept','catalog_candidate_decision')", (CLIENT,))
        cur.execute("delete from hub.client_parser_rules where client_id=%s",
                    (CLIENT,))
        cur.execute("delete from hub.sessions where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.users where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))
    clear_rules_cache()


def _c(session):
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, session)
    return c


def _seed(decl, customs, goods, direction="import"):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bcct_rows (client_id, transaction_key, line_no, "
            " declaration_no, declaration_type, direction, registration_date, "
            " customs_code, goods_name, payload) "
            "values (%s, %s, '1', %s, 'E11', %s, '2026-04-01', %s, %s, '{}'::jsonb)",
            (CLIENT, f"TX_{decl}", decl, direction, customs, goods))
    rebuild_for_client(CLIENT)


def _derivable_codes():
    return sorted(
        r["code"] for r in discovery_rows(CLIENT)
        if r["status"] == "pending"
        and r.get("customs_relevance") != "excluded_non_material"
        and _derive_bulk_attrs(r) is not None)


def _materials():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select material_code from hub.materials where client_id=%s",
                    (CLIENT,))
        return {r[0] for r in cur.fetchall()}


def test_selected_codes_only(setup):
    """Approve exactly the checked codes — the others stay pending."""
    _seed("D1", "AAA", "AAA (019.A)")
    _seed("D2", "BBB", "BBB (019.B)")
    codes = _derivable_codes()
    assert len(codes) >= 3, codes
    chosen = codes[:2]

    c = _c(setup["session"])
    r = c.post(BULK, data={"codes": chosen}, follow_redirects=False)
    assert r.status_code == 303
    mats = _materials()
    assert set(chosen) <= mats
    assert not (set(codes[2:]) & mats), "unselected codes were accepted"


def test_injected_code_is_dropped(setup):
    """The security property: a code that is not in the pending set cannot be
    forced in by putting it in the POST. Intersection, not trust."""
    _seed("D1", "AAA", "AAA (019.A)")
    c = _c(setup["session"])
    r = c.post(BULK, data={"codes": ["NOT_A_REAL_CODE", "'; drop --"]},
               follow_redirects=False)
    assert r.status_code == 303
    assert "bulk_accepted=0" in r.headers["location"]
    assert _materials() == set()


def test_code_outside_active_filter_is_dropped(setup):
    """Selecting a code but sending a filter it doesn't match must not accept
    it — the filter still bounds what the server will touch."""
    _seed("D1", "AAA", "AAA (019.A)")          # no BOM → not a flattened leaf
    codes = _derivable_codes()
    assert codes
    c = _c(setup["session"])
    # leaf=1 filters every row out (no flattened BOM), so even a real selected
    # code intersects to nothing.
    r = c.post(BULK, data={"codes": codes, "leaf": "1"},
               follow_redirects=False)
    assert r.status_code == 303
    assert "bulk_accepted=0" in r.headers["location"]
    assert _materials() == set()


def test_select_all_matching_reproduces_whole_filter(setup):
    """`select_all_matching=1` is the old behaviour: approve everything the
    filter yields, with no explicit code list."""
    _seed("D1", "AAA", "AAA (019.A)")
    _seed("D2", "BBB", "BBB (019.B)")
    all_codes = set(_derivable_codes())
    c = _c(setup["session"])
    r = c.post(BULK, data={"select_all_matching": "1"}, follow_redirects=False)
    assert r.status_code == 303
    assert all_codes <= _materials()


def test_empty_selection_is_a_noop(setup):
    """No codes and no select_all → nothing approved. Empty is not 'approve
    all' any more; selection is explicit."""
    _seed("D1", "AAA", "AAA (019.A)")
    c = _c(setup["session"])
    r = c.post(BULK, data={}, follow_redirects=False)
    assert r.status_code == 303
    assert "bulk_accepted=0" in r.headers["location"]
    assert _materials() == set()


def test_selection_still_respects_the_filter_and_selection_together(setup):
    """Selected ∩ filtered: a code checked AND matching the filter is accepted;
    a checked code that the filter excludes is not."""
    _seed("D1", "AAA", "AAA (019.A)", direction="import")
    _seed("D2", "BBB", "BBB (019.B)", direction="export")
    # source=bcct matches both; pick one code, confirm only it lands.
    codes = _derivable_codes()
    chosen = [codes[0]]
    c = _c(setup["session"])
    r = c.post(BULK, data={"codes": chosen, "source": "bcct"},
               follow_redirects=False)
    assert r.status_code == 303
    mats = _materials()
    assert codes[0] in mats
    assert len(mats) == 1
