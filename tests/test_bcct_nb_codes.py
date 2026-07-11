"""hub.bcct_nb_codes — persisted BCCT paren extraction (#33, BACKLOG A.5).

Covers: the rebuild store (parity with candidates_from_bcct_row), the
rebuilt v_material_roles (NB-in-parens codes get observations), the
placeholder-only machinery marking in v_material_classification, and
the rebuild triggers (BCCT apply, parser-rule edit).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.session import SESSION_COOKIE, create_session, hash_password
from app.database import connect
from app.main import app


CLIENT = "_test_nb_codes"
USER_ID = "u_nb_codes_test"
USER_EMAIL = "nbcodes@test.local"

PAREN_PATTERN = r"\(([\d\.\w\-]+)\)"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name, customs_code_placeholders) "
            "values (%s, 'nb codes test', '{\".\"}') "
            "on conflict (client_id) do update set customs_code_placeholders='{\".\"}'",
            (CLIENT,),
        )
        cur.execute(
            "insert into hub.users (user_id, email, display_name, password_hash, "
            " role, status) values (%s, %s, 'NB Tester', %s, 'admin', 'active') "
            "on conflict (user_id) do update set role='admin', status='active'",
            (USER_ID, USER_EMAIL, hash_password("test-password")),
        )
        for tbl in ("bcct_nb_codes", "catalog_candidates", "bcct_rows",
                    "materials", "client_parser_rules"):
            cur.execute(f"delete from hub.{tbl} where client_id=%s", (CLIENT,))
        cur.execute(
            "insert into hub.client_parser_rules "
            "(client_id, output_field, priority, pattern, source_field, "
            " match_group, match_action, no_match_action, enabled, created_by) "
            "values (%s, 'internal_code', 10, %s, "
            " 'goods_name', 1, 'capture', 'next_rule', true, 'test')",
            (CLIENT, PAREN_PATTERN),
        )
    from app.parsers.client_parser_rules import clear_rules_cache
    clear_rules_cache()
    yield
    with connect() as conn, conn.cursor() as cur:
        for tbl in ("bcct_nb_codes", "catalog_candidates", "bcct_rows",
                    "materials", "client_parser_rules"):
            cur.execute(f"delete from hub.{tbl} where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.sessions where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.users where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))
    clear_rules_cache()


def _seed_bcct(txn, line, customs, goods, *, direction="import",
               decl=None, decl_type="E11", regdate="2026-04-01"):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.bcct_rows
              (client_id, transaction_key, line_no, declaration_no,
               declaration_type, direction, registration_date,
               customs_code, goods_name, payload)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, '{}'::jsonb)
            """,
            (CLIENT, txn, line, decl or txn, decl_type, direction,
             regdate, customs, goods),
        )


def _nb_rows():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select transaction_key, line_no, nb_code from hub.bcct_nb_codes "
            "where client_id=%s order by transaction_key, line_no, nb_code",
            (CLIENT,),
        )
        return cur.fetchall()


# ── Rebuild store ─────────────────────────────────────────────────────────


def test_rebuild_extracts_nb_codes():
    _seed_bcct("TX1", "1", "DAUNOI", "DAUNOI#&Đầu nối (019.X)")
    _seed_bcct("TX1", "2", ".", "forklift part (019.M)")
    _seed_bcct("TX2", "1", "DOV", "no parens here")
    from app.stores.bcct_nb_codes import rebuild_for_client
    n = rebuild_for_client(CLIENT)
    assert n == 2
    assert _nb_rows() == [("TX1", "1", "019.X"), ("TX1", "2", "019.M")]


def test_rebuild_parity_with_parser(setup):
    """The issue's oracle: table content == candidates_from_bcct_row NB
    output, row by row, zero diffs."""
    _seed_bcct("TX1", "1", "DAUNOI", "combo (019.X) and (019.Y)")
    _seed_bcct("TX1", "2", "PV01.Z", "unified (PV01.Z)")   # NB==HQ: no NB row
    _seed_bcct("TX2", "1", "", "bare (019.W)")
    _seed_bcct("TX2", "2", "DOV", "nothing extractable")
    from app.stores.bcct_nb_codes import rebuild_for_client
    rebuild_for_client(CLIENT)

    from app.parsers.catalog_candidates import candidates_from_bcct_row
    from app.parsers.client_parser_rules import load_rules
    rules = load_rules(client_id=CLIENT, output_field="internal_code")
    expected = set()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select transaction_key, line_no, customs_code, goods_name "
            "from hub.bcct_rows where client_id=%s", (CLIENT,),
        )
        for txn, line, cc, gn in cur.fetchall():
            cands = candidates_from_bcct_row(
                {"customs_code": cc, "goods_name": gn},
                rules=rules, has_dual_system=True, placeholders=(".",),
            )
            for code, kind in cands:
                if kind == "nb":
                    expected.add((txn, line, code))
    assert set(_nb_rows()) == expected
    assert ("TX1", "2", "PV01.Z") not in expected  # unified stays out


def test_rebuild_no_rules_client_is_empty():
    """Johnson-shape: no parser rules → empty half, rebuild is a no-op."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.client_parser_rules where client_id=%s", (CLIENT,),
        )
    from app.parsers.client_parser_rules import clear_rules_cache
    clear_rules_cache()
    _seed_bcct("TX1", "1", "1000527370", "1000527370#&Tấm đỡ (1000527371)")
    from app.stores.bcct_nb_codes import rebuild_for_client
    assert rebuild_for_client(CLIENT) == 0
    assert _nb_rows() == []


def test_rebuild_is_delete_and_rebuild():
    _seed_bcct("TX1", "1", "DAUNOI", "x (019.X)")
    from app.stores.bcct_nb_codes import rebuild_for_client
    rebuild_for_client(CLIENT)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bcct_rows where client_id=%s", (CLIENT,))
    _seed_bcct("TX9", "1", "DAUNOI", "y (019.Z)")
    rebuild_for_client(CLIENT)
    assert _nb_rows() == [("TX9", "1", "019.Z")]


# ── v_material_roles (6th definition) ─────────────────────────────────────


def _add_material(code, category="nvl"):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            " category, status, source) values (%s, %s, %s, %s, 'active', "
            " 'bcct_observed')",
            (CLIENT, code, code, category),
        )


def _roles_row(code):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select observed_count, has_imports, has_exports, "
            "       observed_directions from hub.v_material_roles "
            "where client_id=%s and material_code=%s",
            (CLIENT, code),
        )
        return cur.fetchone()


def test_view_sees_paren_only_nb_code():
    """A.5 acceptance: an NB code that never appears as customs_code gets
    observations from the view once the link table is populated."""
    _seed_bcct("TX1", "1", "DAUNOI", "a (019.X)", decl="D1")
    _seed_bcct("TX2", "1", "LK-DAY2", "b (019.X)", decl="D2",
               direction="export", decl_type="E62")
    _add_material("019.X")
    from app.stores.bcct_nb_codes import rebuild_for_client
    rebuild_for_client(CLIENT)
    row = _roles_row("019.X")
    assert row is not None
    observed_count, has_imports, has_exports, directions = row
    assert observed_count == 2
    assert has_imports is True
    assert has_exports is True
    assert sorted(directions) == ["export", "import"]


def test_view_customs_code_only_unchanged():
    """Johnson-shape signals (customs_code join) keep working untouched."""
    _seed_bcct("TX1", "1", "MAT-1", "plain goods", decl="D1")
    _add_material("MAT-1")
    row = _roles_row("MAT-1")
    assert row is not None
    assert row[0] == 1 and row[1] is True


def test_view_no_double_count_when_code_is_both():
    """A code as customs_code AND in its own parens on the same line
    counts each declaration once."""
    _seed_bcct("TX1", "1", "PV01.Z", "unified (PV01.Z)", decl="D1")
    _add_material("PV01.Z")
    from app.stores.bcct_nb_codes import rebuild_for_client
    rebuild_for_client(CLIENT)
    row = _roles_row("PV01.Z")
    assert row[0] == 1


# ── Machinery marking (v_material_classification) ─────────────────────────


def _relevance(code):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select customs_relevance from hub.v_material_classification "
            "where client_id=%s and material_code=%s",
            (CLIENT, code),
        )
        r = cur.fetchone()
        return r[0] if r else None


def test_placeholder_only_code_marked_excluded():
    """Observed ONLY on placeholder lines → excluded_non_material."""
    _seed_bcct("TX1", "1", ".", "forklift part (019.M)", decl_type="E13")
    _seed_bcct("TX2", "1", ".", "rack part (019.M)", decl_type="E13")
    _add_material("019.M")
    from app.stores.bcct_nb_codes import rebuild_for_client
    rebuild_for_client(CLIENT)
    assert _relevance("019.M") == "excluded_non_material"


def test_shared_code_not_marked():
    """Appears on a placeholder line AND a production line → NOT marked."""
    _seed_bcct("TX1", "1", ".", "forklift part (019.S)", decl_type="E13")
    _seed_bcct("TX2", "1", "DAUNOI", "production use (019.S)")
    _add_material("019.S")
    from app.stores.bcct_nb_codes import rebuild_for_client
    rebuild_for_client(CLIENT)
    assert _relevance("019.S") != "excluded_non_material"


def test_code_that_is_own_customs_code_not_marked():
    """A code that also appears as a customs_code is on a production line
    by definition — never marked."""
    _seed_bcct("TX1", "1", ".", "part (019.B)", decl_type="E13")
    _seed_bcct("TX2", "1", "019.B", "declared directly")
    _add_material("019.B")
    from app.stores.bcct_nb_codes import rebuild_for_client
    rebuild_for_client(CLIENT)
    assert _relevance("019.B") != "excluded_non_material"


# ── Rebuild triggers ──────────────────────────────────────────────────────


def test_bcct_apply_rebuilds_nb_codes():
    from app.routes.bcct import _apply_bcct_rows
    from app.routes.clients import get_client
    client = get_client(CLIENT)
    row = {
        "transaction_key": "TX_H", "line_no": "1", "declaration_no": "DH",
        "declaration_type": "E11", "direction": "import",
        "registration_date": "2026-04-01",
        "customs_code": "DAUNOI", "goods_name": "hook (019.HK)",
    }
    _apply_bcct_rows(client_id=CLIENT, rows=[row], upload_id=None,
                     client=client, orphans_to_delete=[], user_id=None)
    assert ("TX_H", "1", "019.HK") in set(_nb_rows())


def test_rule_edit_rebuilds_nb_codes():
    """Disabling the extraction rule via the UI route empties the half."""
    _seed_bcct("TX1", "1", "DAUNOI", "x (019.X)")
    from app.stores.bcct_nb_codes import rebuild_for_client
    rebuild_for_client(CLIENT)
    assert _nb_rows() != []
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select rule_id from hub.client_parser_rules where client_id=%s",
            (CLIENT,),
        )
        (rule_id,) = cur.fetchone()
        # Rule editing is dev-only (can_edit_client_technical); use the
        # seeded single dev user (mig 008 invariant) rather than a second.
        cur.execute("select user_id from hub.users where role='dev' limit 1")
        (dev_id,) = cur.fetchone()
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, create_session(dev_id))
    r = c.post(f"/clients/{CLIENT}/parser-rules/{rule_id}/disable",
               follow_redirects=False)
    assert r.status_code == 303
    assert _nb_rows() == []


# ── Backfill ──────────────────────────────────────────────────────────────


def test_backfill_if_empty_fills_then_skips():
    _seed_bcct("TX1", "1", "DAUNOI", "x (019.X)")
    from app.stores.bcct_nb_codes import backfill_if_empty
    filled = backfill_if_empty()
    assert CLIENT in filled
    # Second call: table non-empty for this client → skipped.
    assert CLIENT not in backfill_if_empty()
