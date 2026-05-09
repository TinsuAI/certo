"""compute_observations — generic per-client (rules-driven), no
Growatt special-casing.

Workaround until v_material_roles becomes paren-aware (BACKLOG item).
"""
from __future__ import annotations

import pytest

from app.database import connect


CLIENT_DUAL = "_test_obs_dual"
CLIENT_UNIF = "_test_obs_unified"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        for cid in (CLIENT_DUAL, CLIENT_UNIF):
            cur.execute(
                "insert into hub.clients (client_id, name) values (%s, %s) "
                "on conflict do nothing",
                (cid, "obs test"),
            )
            cur.execute("delete from hub.bcct_rows where client_id=%s", (cid,))
            cur.execute(
                "delete from hub.client_parser_rules where client_id=%s", (cid,)
            )
        cur.execute(
            "insert into hub.client_parser_rules "
            "(client_id, output_field, priority, pattern, source_field, "
            " match_group, match_action, no_match_action, enabled, created_by) "
            "values (%s, 'internal_code', 10, '\\(([\\d\\.\\w\\-]+)\\)', "
            " 'goods_name', 1, 'capture', 'next_rule', true, 'test') "
            "on conflict do nothing",
            (CLIENT_DUAL,),
        )
    from app.parsers.client_parser_rules import clear_rules_cache
    clear_rules_cache()
    yield
    with connect() as conn, conn.cursor() as cur:
        for cid in (CLIENT_DUAL, CLIENT_UNIF):
            cur.execute("delete from hub.bcct_rows where client_id=%s", (cid,))
            cur.execute(
                "delete from hub.client_parser_rules where client_id=%s", (cid,)
            )
            cur.execute("delete from hub.clients where client_id=%s", (cid,))
    clear_rules_cache()


def _seed(client_id, rows):
    """rows: list of (decl, customs_code, goods_name, direction, regdate)."""
    with connect() as conn, conn.cursor() as cur:
        for i, (decl, cc, gn, dr, regdate) in enumerate(rows):
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no,
                   declaration_type, direction, registration_date,
                   customs_code, goods_name, payload)
                values (%s, %s, '1', %s, 'E11', %s, %s, %s, %s, '{}'::jsonb)
                """,
                (client_id, f"TX_{decl}_{i}", decl, dr, regdate, cc, gn),
            )


def test_observations_via_paren_extract_dual_system():
    """NB code lives in goods_name parens, not in customs_code."""
    import datetime as dt
    from app.stores.material_observations import compute_observations
    _seed(CLIENT_DUAL, [
        ("D1", "DAUNOI", "DAUNOI#&item (019.X)", "import", dt.date(2026, 4, 1)),
        ("D2", "DAUNOI", "DAUNOI#&item (019.X)", "import", dt.date(2026, 5, 1)),
    ])
    obs = compute_observations(CLIENT_DUAL, "019.X")
    assert obs.has_imports is True
    assert obs.has_exports is False
    assert obs.observed_count == 2
    assert obs.observed_first_at == dt.date(2026, 4, 1)
    assert obs.observed_last_at == dt.date(2026, 5, 1)
    assert obs.observed_directions == ["import"]


def test_observations_via_customs_code_unified():
    """Single-system client (no rules) — match by customs_code only."""
    import datetime as dt
    from app.stores.material_observations import compute_observations
    _seed(CLIENT_UNIF, [
        ("J1", "1000527370", "1000527370#&Tấm đỡ", "import", dt.date(2026, 3, 1)),
    ])
    obs = compute_observations(CLIENT_UNIF, "1000527370")
    assert obs.has_imports is True
    assert obs.observed_count == 1


def test_observations_distinct_decl_count():
    """Same code on multiple LINES of same declaration → 1 distinct decl."""
    import datetime as dt
    from app.stores.material_observations import compute_observations
    _seed(CLIENT_DUAL, [
        ("D1", "X", "X (019.X)", "import", dt.date(2026, 4, 1)),
        ("D1", "X", "X (019.X)", "import", dt.date(2026, 4, 1)),  # same decl
        ("D2", "X", "X (019.X)", "import", dt.date(2026, 4, 2)),
    ])
    obs = compute_observations(CLIENT_DUAL, "019.X")
    assert obs.observed_count == 2  # 2 distinct decls


def test_observations_both_directions():
    import datetime as dt
    from app.stores.material_observations import compute_observations
    _seed(CLIENT_DUAL, [
        ("D1", "X", "X (Y)", "import", dt.date(2026, 4, 1)),
        ("D2", "X", "X (Y)", "export", dt.date(2026, 4, 2)),
    ])
    obs = compute_observations(CLIENT_DUAL, "Y")
    assert obs.has_imports and obs.has_exports
    assert sorted(obs.observed_directions) == ["export", "import"]


def test_observations_empty_when_no_match():
    from app.stores.material_observations import compute_observations
    obs = compute_observations(CLIENT_DUAL, "DOES_NOT_EXIST")
    assert obs.observed_count == 0
    assert obs.has_imports is False
    assert obs.has_exports is False
