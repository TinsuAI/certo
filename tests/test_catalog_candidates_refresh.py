"""Refresh logic — scan BCCT + BOM + code_mappings, anti-join materials,
UPSERT into catalog_candidates. Status is sticky across refresh; observation
stats rebuild from truth.

Brief: D1 + sources 1-4.
"""
from __future__ import annotations

import datetime as dt

import pytest

from app.database import connect


CLIENT_DUAL = "_test_refresh_dual"     # Has parser rules → embed-shape
CLIENT_UNIF = "_test_refresh_unified"  # No rules, no mappings → unified
CLIENT_BQD  = "_test_refresh_bqd"      # Has mappings only → BQD-only


@pytest.fixture(autouse=True)
def setup_clients():
    """Three test clients covering 3 shapes. Cleanup after each test."""
    with connect() as conn, conn.cursor() as cur:
        for cid in (CLIENT_DUAL, CLIENT_UNIF, CLIENT_BQD):
            cur.execute(
                "insert into hub.clients (client_id, name) values (%s, %s) "
                "on conflict do nothing",
                (cid, f"refresh test {cid}"),
            )
            # Clean residue
            cur.execute("delete from hub.catalog_candidates where client_id=%s", (cid,))
            cur.execute("delete from hub.bcct_rows where client_id=%s", (cid,))
            cur.execute("delete from hub.materials where client_id=%s", (cid,))
            cur.execute("delete from hub.bom_edges where artifact_id in "
                        "(select artifact_id from hub.bom_artifacts where client_id=%s)",
                        (cid,))
            cur.execute("delete from hub.bom_artifacts where client_id=%s", (cid,))
            cur.execute("delete from hub.code_mappings where client_id=%s", (cid,))
            cur.execute("delete from hub.client_parser_rules where client_id=%s", (cid,))

        # Seed parser rule for DUAL client (paren-extract)
        cur.execute(
            "insert into hub.client_parser_rules "
            "(client_id, output_field, priority, pattern, source_field, "
            " match_group, match_action, no_match_action, enabled, created_by) "
            "values (%s, 'internal_code', 10, '\\(([\\d\\.\\w\\-]+)\\)', "
            " 'goods_name', 1, 'capture', 'next_rule', true, 'test') "
            "on conflict do nothing",
            (CLIENT_DUAL,),
        )
        # Seed code_mappings for BQD client (PK = client_id+internal_code+customs_code)
        cur.execute(
            "insert into hub.code_mappings (client_id, internal_code, customs_code) "
            "values (%s, '03.02.01.065', 'KEO B') on conflict do nothing",
            (CLIENT_BQD,),
        )

    # Clear rules cache so freshly-seeded rule is loaded
    from app.parsers.client_parser_rules import clear_rules_cache
    clear_rules_cache()

    yield

    with connect() as conn, conn.cursor() as cur:
        for cid in (CLIENT_DUAL, CLIENT_UNIF, CLIENT_BQD):
            cur.execute("delete from hub.catalog_candidates where client_id=%s", (cid,))
            cur.execute("delete from hub.bcct_rows where client_id=%s", (cid,))
            cur.execute("delete from hub.materials where client_id=%s", (cid,))
            cur.execute("delete from hub.bom_edges where artifact_id in "
                        "(select artifact_id from hub.bom_artifacts where client_id=%s)",
                        (cid,))
            cur.execute("delete from hub.bom_artifacts where client_id=%s", (cid,))
            cur.execute("delete from hub.code_mappings where client_id=%s", (cid,))
            cur.execute("delete from hub.client_parser_rules where client_id=%s", (cid,))
            cur.execute("delete from hub.clients where client_id=%s", (cid,))

    from app.parsers.client_parser_rules import clear_rules_cache
    clear_rules_cache()


def _seed_bcct(client_id, rows):
    """rows: list of (decl, line, customs_code, goods_name, direction, regdate)."""
    with connect() as conn, conn.cursor() as cur:
        for decl, line, cc, gn, dirn, regdate in rows:
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no,
                   declaration_type, direction, registration_date,
                   customs_code, goods_name, payload)
                values (%s, %s, %s, %s, 'E11', %s, %s, %s, %s, '{}'::jsonb)
                """,
                (client_id, f"TX_{decl}_{line}", line, decl, dirn, regdate, cc, gn),
            )


def _candidates(client_id):
    """Read all candidates for client_id."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select code, code_kind, sources, observed_count, status, "
            "       suggested_category, multi_direction "
            "from hub.catalog_candidates where client_id=%s "
            "order by code, code_kind",
            (client_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


# ── Refresh: BCCT source ──────────────────────────────────────────────────


def test_refresh_dual_bcct_extracts_hq_and_nb():
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct(CLIENT_DUAL, [
        ("D1", "1", "DAUNOI", "DAUNOI#&Đầu nối (019.0023800)",
         "import", dt.date(2026, 4, 1)),
    ])
    refresh_candidates(CLIENT_DUAL)
    cs = _candidates(CLIENT_DUAL)
    by_code = {(c["code"], c["code_kind"]): c for c in cs}
    assert ("DAUNOI", "hq") in by_code
    assert ("019.0023800", "nb") in by_code
    for c in cs:
        assert c["status"] == "pending"
        assert "bcct" in c["sources"]


def test_refresh_unified_client_kind_unified():
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct(CLIENT_UNIF, [
        ("J1", "1", "1000527370", "1000527370#&Tấm đỡ",
         "import", dt.date(2026, 3, 1)),
    ])
    refresh_candidates(CLIENT_UNIF)
    cs = _candidates(CLIENT_UNIF)
    assert len(cs) == 1
    assert cs[0]["code"] == "1000527370"
    assert cs[0]["code_kind"] == "unified"


def test_refresh_skips_codes_already_in_materials():
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct(CLIENT_DUAL, [
        ("D1", "1", "DAUNOI", "DAUNOI (019.X)", "import", dt.date(2026, 4, 1)),
    ])
    # Pre-existing material — should not appear as candidate
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category, status, source, code_kind) values "
            "(%s, 'DAUNOI', 'existing', 'nvl', 'active', 'client_declared', 'hq')",
            (CLIENT_DUAL,),
        )
    refresh_candidates(CLIENT_DUAL)
    cs = _candidates(CLIENT_DUAL)
    codes = {(c["code"], c["code_kind"]) for c in cs}
    assert ("DAUNOI", "hq") not in codes  # already in materials
    assert ("019.X", "nb") in codes


def test_refresh_aggregates_observed_count_across_rows():
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct(CLIENT_DUAL, [
        ("D1", "1", "IC", "IC#&chip (007.X)", "import", dt.date(2026, 4, 1)),
        ("D2", "1", "IC", "IC#&chip (007.X)", "import", dt.date(2026, 4, 5)),
        ("D3", "1", "IC", "IC#&chip (007.X)", "import", dt.date(2026, 3, 1)),
    ])
    refresh_candidates(CLIENT_DUAL)
    cs = _candidates(CLIENT_DUAL)
    ic_hq = next(c for c in cs if c["code"] == "IC" and c["code_kind"] == "hq")
    assert ic_hq["observed_count"] == 3


def test_refresh_first_seen_last_seen_dates():
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct(CLIENT_DUAL, [
        ("D1", "1", "IC", "IC (007.X)", "import", dt.date(2026, 1, 15)),
        ("D2", "1", "IC", "IC (007.X)", "import", dt.date(2026, 5, 1)),
        ("D3", "1", "IC", "IC (007.X)", "import", dt.date(2026, 3, 10)),
    ])
    refresh_candidates(CLIENT_DUAL)
    cs = _candidates(CLIENT_DUAL)
    ic = next(c for c in cs if c["code"] == "IC")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select first_seen, last_seen from hub.catalog_candidates "
            "where client_id=%s and code='IC'", (CLIENT_DUAL,),
        )
        first, last = cur.fetchone()
    assert first == dt.date(2026, 1, 15)
    assert last == dt.date(2026, 5, 1)


# ── Refresh: BOM source ───────────────────────────────────────────────────


def test_refresh_bom_emits_nb_candidates():
    from app.stores.catalog_candidates import refresh_candidates
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, product_code, "
            " artifact_no, status, actor, intent, normalized_hash, "
            " source_bom_kind, flatten_status, flatten_strategy, source_channel, "
            " flatten_method, flatten_method_version) "
            "values ('ba_test_p', %s, 'P', 1, 'published', 'system', "
            " 'asserted_technical', 'h_test_p', 'technical_raw', "
            " 'flattened', 'technical_exploded', 'migration', "
            " 'identity', 1) "
            "on conflict do nothing",
            (CLIENT_DUAL,),
        )
        cur.execute(
            "insert into hub.bom_edges (artifact_id, row_index, root_code, "
            " parent_code, child_code, qty_per_parent) values "
            " ('ba_test_p', 1, 'P', 'P', 'Q', 1), "
            " ('ba_test_p', 2, 'P', 'Q', 'R', 2)",
        )
    refresh_candidates(CLIENT_DUAL)
    cs = _candidates(CLIENT_DUAL)
    bom_codes = {c["code"] for c in cs if "bom" in c["sources"]}
    assert bom_codes == {"P", "Q", "R"}
    for c in cs:
        if "bom" in c["sources"]:
            assert c["code_kind"] == "nb"


# ── Refresh: code_mappings (BQD) source ───────────────────────────────────


def test_refresh_bqd_only_emits_hq_and_nb():
    from app.stores.catalog_candidates import refresh_candidates
    refresh_candidates(CLIENT_BQD)
    cs = _candidates(CLIENT_BQD)
    by_code = {(c["code"], c["code_kind"]): c for c in cs}
    assert ("KEO B", "hq") in by_code
    assert ("03.02.01.065", "nb") in by_code
    for c in cs:
        assert "bqd" in c["sources"]


# ── Status sticky ─────────────────────────────────────────────────────────


def test_refresh_status_sticky_pending_stays_pending():
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct(CLIENT_DUAL, [
        ("D1", "1", "X", "X (019.X)", "import", dt.date(2026, 4, 1)),
    ])
    refresh_candidates(CLIENT_DUAL)
    refresh_candidates(CLIENT_DUAL)  # idempotent
    cs = _candidates(CLIENT_DUAL)
    assert all(c["status"] == "pending" for c in cs)
    assert {(c["code"], c["code_kind"]) for c in cs} == {
        ("X", "hq"), ("019.X", "nb"),
    }


def test_refresh_status_sticky_rejected_stays_rejected():
    """Rejected candidate must not flip back to pending on refresh."""
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct(CLIENT_DUAL, [
        ("D1", "1", "X", "X (019.X)", "import", dt.date(2026, 4, 1)),
    ])
    refresh_candidates(CLIENT_DUAL)
    # Reject one
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.catalog_candidates set status='rejected', "
            "decided_at=now(), decided_by='test@example.com' "
            "where client_id=%s and code='X' and code_kind='hq'",
            (CLIENT_DUAL,),
        )
    refresh_candidates(CLIENT_DUAL)  # status must stay rejected
    cs = _candidates(CLIENT_DUAL)
    x_hq = next(c for c in cs if c["code"] == "X" and c["code_kind"] == "hq")
    assert x_hq["status"] == "rejected"


def test_refresh_observed_count_rebuilds_from_truth():
    """If BCCT row deleted between refreshes, observed_count must drop."""
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct(CLIENT_DUAL, [
        ("D1", "1", "Y", "Y (019.X)", "import", dt.date(2026, 4, 1)),
        ("D2", "1", "Y", "Y (019.X)", "import", dt.date(2026, 4, 2)),
    ])
    refresh_candidates(CLIENT_DUAL)
    cs1 = _candidates(CLIENT_DUAL)
    y_hq = next(c for c in cs1 if c["code"] == "Y" and c["code_kind"] == "hq")
    assert y_hq["observed_count"] == 2

    # Delete one BCCT row
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bcct_rows "
                    "where client_id=%s and declaration_no='D2'",
                    (CLIENT_DUAL,))
    refresh_candidates(CLIENT_DUAL)
    cs2 = _candidates(CLIENT_DUAL)
    y_hq2 = next(c for c in cs2 if c["code"] == "Y" and c["code_kind"] == "hq")
    assert y_hq2["observed_count"] == 1  # rebuilt, not incremented


# ── Suggested category logic ──────────────────────────────────────────────


def test_suggested_category_import_only_is_nvl():
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct(CLIENT_DUAL, [
        ("D1", "1", "DIENTRO", "DIENTRO (001.X)", "import", dt.date(2026, 4, 1)),
        ("D2", "1", "DIENTRO", "DIENTRO (001.Y)", "import", dt.date(2026, 4, 2)),
    ])
    refresh_candidates(CLIENT_DUAL)
    cs = _candidates(CLIENT_DUAL)
    dientro = next(c for c in cs if c["code"] == "DIENTRO")
    assert dientro["suggested_category"] == "nvl"
    assert dientro["multi_direction"] is False


def test_suggested_category_export_only_is_tp():
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct(CLIENT_DUAL, [
        ("D1", "1", "BIENTAN", "BIENTAN (PV01.X)", "export", dt.date(2026, 4, 1)),
    ])
    refresh_candidates(CLIENT_DUAL)
    cs = _candidates(CLIENT_DUAL)
    bt = next(c for c in cs if c["code"] == "BIENTAN")
    assert bt["suggested_category"] == "tp"


def test_suggested_category_both_directions_is_nvl_with_badge():
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct(CLIENT_DUAL, [
        ("D1", "1", "DUAL", "DUAL (019.X)", "import", dt.date(2026, 4, 1)),
        ("D2", "1", "DUAL", "DUAL (019.X)", "export", dt.date(2026, 4, 5)),
    ])
    refresh_candidates(CLIENT_DUAL)
    cs = _candidates(CLIENT_DUAL)
    d = next(c for c in cs if c["code"] == "DUAL")
    assert d["suggested_category"] == "nvl"
    assert d["multi_direction"] is True
