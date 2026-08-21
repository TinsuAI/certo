"""hub.catalog_discovery(client) — the anti-join discovery function
(#34, ADR-0001). Replaces the stored catalog_candidates queue: pending
is computed from BCCT + BOM + BQD, anti-joined against materials and
the suppression table.

Covers what the old refresh/richness/collapse test files locked, now
as function output: the 4 BCCT classification cases, anti-join,
suppression, the three source streams, stat enrichment, and the
collapse of unaffiliated multi-kind codes.
"""
from __future__ import annotations

import pytest

from hub.app.database import connect


CLIENT = "_test_discovery"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name, customs_code_placeholders) "
            "values (%s, 'discovery test', '{\".\"}') "
            "on conflict (client_id) do update set customs_code_placeholders='{\".\"}'",
            (CLIENT,),
        )
        for tbl in ("bcct_nb_codes", "catalog_rejections", "bcct_rows",
                    "materials", "client_parser_rules", "code_mappings",
                    "bom_edges", "bom_artifacts"):
            if tbl == "bom_edges":
                cur.execute(
                    "delete from hub.bom_edges where artifact_id in "
                    "(select artifact_id from hub.bom_artifacts where client_id=%s)",
                    (CLIENT,),
                )
            else:
                cur.execute(f"delete from hub.{tbl} where client_id=%s", (CLIENT,))
        cur.execute(
            "insert into hub.client_parser_rules "
            "(client_id, output_field, priority, pattern, source_field, "
            " match_group, match_action, no_match_action, enabled, created_by) "
            "values (%s, 'internal_code', 10, '\\(([\\d\\.\\w\\-]+)\\)', "
            " 'goods_name', 1, 'capture', 'next_rule', true, 'test')",
            (CLIENT,),
        )
    from hub.app.parsers.client_parser_rules import clear_rules_cache
    clear_rules_cache()
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.bom_edges where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (CLIENT,),
        )
        for tbl in ("bcct_nb_codes", "catalog_rejections", "bcct_rows",
                    "materials", "client_parser_rules", "code_mappings",
                    "bom_artifacts"):
            cur.execute(f"delete from hub.{tbl} where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))
    clear_rules_cache()


def _seed_bcct(txn, customs, goods, *, line="1", direction="import",
               decl=None, hs=None, unit=None, origin=None,
               regdate="2026-04-01"):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.bcct_rows
              (client_id, transaction_key, line_no, declaration_no,
               declaration_type, direction, registration_date,
               customs_code, goods_name, hs_code, unit, origin, payload)
            values (%s, %s, %s, %s, 'E11', %s, %s, %s, %s, %s, %s, %s,
                    '{}'::jsonb)
            """,
            (CLIENT, txn, line, decl or txn, direction, regdate,
             customs, goods, hs, unit, origin),
        )


def _rebuild():
    from hub.app.stores.bcct_nb_codes import rebuild_for_client
    rebuild_for_client(CLIENT)


def _rows(status="pending"):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select * from hub.catalog_discovery(%s) where status = %s",
            (CLIENT, status),
        )
        cols = [d[0] for d in cur.description]
        return {(r[cols.index("code")], r[cols.index("code_kind")]):
                dict(zip(cols, r)) for r in cur.fetchall()}


# ── Schema: the three homes ───────────────────────────────────────────────


def test_candidates_table_is_gone_and_homes_exist():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from information_schema.tables "
            "where table_schema='hub' and table_name='catalog_candidates'",
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            "select count(*) from information_schema.tables "
            "where table_schema='hub' and table_name='catalog_rejections'",
        )
        assert cur.fetchone()[0] == 1
        cur.execute(
            "select count(*) from pg_proc p join pg_namespace n "
            "on n.oid = p.pronamespace "
            "where n.nspname='hub' and p.proname='catalog_discovery'",
        )
        assert cur.fetchone()[0] == 1


# ── The 4 BCCT classification cases ──────────────────────────────────────


def test_bcct_dual_row_emits_hq_and_nb():
    _seed_bcct("TX1", "DAUNOI", "DAUNOI#&Đầu nối (019.X)")
    _rebuild()
    rows = _rows()
    assert ("DAUNOI", "hq") in rows
    assert ("019.X", "nb") in rows


def test_bcct_unified_row_emits_single_unified():
    """NB==HQ on the row → one 'unified' candidate, no separate nb/hq."""
    _seed_bcct("TX1", "PV01.Z", "BIENTAN#&Bộ biến tần (PV01.Z)")
    _rebuild()
    rows = _rows()
    assert ("PV01.Z", "unified") in rows
    assert ("PV01.Z", "hq") not in rows
    assert ("PV01.Z", "nb") not in rows


def test_bcct_placeholder_row_emits_nb_only():
    _seed_bcct("TX1", ".", "forklift part (019.M)")
    _rebuild()
    rows = _rows()
    assert ("019.M", "nb") in rows
    assert not any(code == "." for code, _ in rows)


def test_single_system_client_emits_unified():
    """No rules, no mappings → customs_code is 'unified'."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.client_parser_rules where client_id=%s", (CLIENT,),
        )
    from hub.app.parsers.client_parser_rules import clear_rules_cache
    clear_rules_cache()
    _seed_bcct("TX1", "1000527370", "1000527370#&Tấm đỡ")
    rows = _rows()
    assert ("1000527370", "unified") in rows


# ── Anti-join + suppression ──────────────────────────────────────────────


def test_materials_anti_join_hides_code():
    _seed_bcct("TX1", "DAUNOI", "DAUNOI#&x (019.X)")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            " category, status, source) "
            "values (%s, 'DAUNOI', 'Đầu nối', 'nvl', 'active', 'bcct_observed')",
            (CLIENT,),
        )
    _rebuild()
    rows = _rows()
    assert not any(code == "DAUNOI" for code, _ in rows)
    assert ("019.X", "nb") in rows


def test_rejected_code_leaves_pending_but_stays_visible():
    _seed_bcct("TX1", "NOISE", "NOISE#&rác")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.catalog_rejections "
            "(client_id, code, code_kind, reason, rejected_by) "
            "values (%s, 'NOISE', 'hq', 'junk', 'tester')",
            (CLIENT,),
        )
    pending = _rows("pending")
    rejected = _rows("rejected")
    assert not any(code == "NOISE" for code, _ in pending)
    assert ("NOISE", "hq") in rejected
    assert rejected[("NOISE", "hq")]["decision_reason"] == "junk"
    assert rejected[("NOISE", "hq")]["decided_by"] == "tester"


def test_rejection_survives_data_growth():
    """The old queue kept decisions sticky across refreshes; suppression
    is a table, so new source rows cannot resurrect a rejected code."""
    _seed_bcct("TX1", "NOISE", "NOISE#&rác")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.catalog_rejections "
            "(client_id, code, rejected_by) values (%s, 'NOISE', 'tester')",
            (CLIENT,),
        )
    _seed_bcct("TX2", "NOISE", "NOISE#&more rác")
    _rebuild()
    assert not any(code == "NOISE" for code, _ in _rows("pending"))


# ── Stats: counts, dates, enrichment ─────────────────────────────────────


def test_observed_and_direction_counts():
    _seed_bcct("TX1", "DOV", "a", decl="D1", regdate="2026-01-10")
    _seed_bcct("TX2", "DOV", "b", decl="D2", regdate="2026-03-15",
               direction="export")
    row = _rows()[("DOV", "hq")]
    assert row["observed_count"] == 2
    assert row["import_count"] == 1
    assert row["export_count"] == 1
    assert row["decl_count"] == 2
    assert str(row["first_seen"]) == "2026-01-10"
    assert str(row["last_seen"]) == "2026-03-15"
    assert row["multi_direction"] is True
    assert row["suggested_category"] == "nvl"       # import wins
    assert row["inferred_production_source"] == "mixed"


def test_richness_hs_uom_origin():
    _seed_bcct("TX1", "DOV", "a", hs="85044090", unit="PIECES", origin="CN")
    _seed_bcct("TX2", "DOV", "b", hs="85044090", unit="PCS", origin="CN")
    _seed_bcct("TX3", "DOV", "c", hs="85334000", unit="ST", origin="VN")
    row = _rows()[("DOV", "hq")]
    assert row["hs_code"] == "85044090"
    assert row["hs_alternates_count"] == 1          # one alternate HS
    assert row["uom"] == "pcs"                      # aliases normalized
    assert row["origin"] == "CN"


def test_export_only_suggests_tp():
    _seed_bcct("TX1", "SP01", "sp", direction="export")
    row = _rows()[("SP01", "hq")]
    assert row["suggested_category"] == "tp"
    assert row["inferred_production_source"] == "sx"


# ── BOM + BQD streams ────────────────────────────────────────────────────


def _seed_bom(product, edges):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            " product_code, artifact_no, actor, intent, normalized_hash, "
            " source_bom_kind, flatten_status, flatten_strategy, "
            " source_channel, flatten_method, flatten_method_version, "
            " lineage_root_id) "
            "values ('ba_disc_' || %s, %s, %s, 1, 'agency_staff', "
            " 'asserted_technical', 'h_' || %s, 'manual_flat', "
            " 'not_applicable', 'manual_flat_as_provided', "
            " 'agency_upload', 'none', 1, 'ba_disc_' || %s) "
            "returning artifact_id",
            (product, CLIENT, product, product, product),
        )
        (aid,) = cur.fetchone()
        for i, (parent, child, uom) in enumerate(edges):
            cur.execute(
                "insert into hub.bom_edges (artifact_id, row_index, "
                " root_code, parent_code, child_code, qty_per_parent, uom, "
                " level) values (%s, %s, %s, %s, %s, 1, %s, 1)",
                (aid, i, product, parent, child, uom),
            )


def test_bom_stream_roles_and_sample():
    _seed_bom("PROD1", [("PROD1", "MID1", "pcs"), ("MID1", "LEAF1", "kg")])
    rows = _rows()
    assert rows[("MID1", "nb")]["bom_role"] == "btp_sx"
    assert rows[("LEAF1", "nb")]["bom_role"] == "nvl_leaf"
    assert rows[("LEAF1", "nb")]["sources"] == ["bom"]
    assert rows[("LEAF1", "nb")]["uom"] == "kg"
    assert rows[("PROD1", "nb")]["bom_role"] == "tp_root"
    assert rows[("PROD1", "nb")]["suggested_category"] == "tp"


def test_bqd_stream_emits_pairs():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.code_mappings (client_id, internal_code, "
            " customs_code) values (%s, '019.B', 'BUCKET')",
            (CLIENT,),
        )
    rows = _rows()
    assert rows[("BUCKET", "hq")]["sources"] == ["bqd"]
    assert rows[("019.B", "nb")]["sources"] == ["bqd"]


def test_sources_merge_across_streams():
    _seed_bcct("TX1", "DAUNOI", "DAUNOI#&x (019.X)")
    _seed_bom("PROD1", [("PROD1", "019.X", "pcs")])
    _rebuild()
    row = _rows()[("019.X", "nb")]
    assert row["sources"] == ["bcct", "bom"]
    # observed = 1 BCCT row + 1 BOM edge appearance
    assert row["observed_count"] == 2


# ── Collapse (ADR-0001: whole-corpus property, in SQL) ───────────────────


def test_multi_kind_unaffiliated_collapses_to_unified():
    """Same string as BCCT hq (no parens pairing) + BOM nb → one
    'unified' row with merged stats."""
    _seed_bcct("TX1", "SHARED", "no parens here")
    _seed_bom("PROD1", [("PROD1", "SHARED", "pcs")])
    _rebuild()
    rows = _rows()
    assert ("SHARED", "unified") in rows
    assert ("SHARED", "hq") not in rows
    assert ("SHARED", "nb") not in rows
    merged = rows[("SHARED", "unified")]
    assert set(merged["sources"]) == {"bcct", "bom"}
    assert merged["observed_count"] == 2   # 1 BCCT row + 1 edge


def test_affiliated_multi_kind_does_not_collapse():
    """A code paired with a DIFFERENT string on a BCCT row keeps its
    kinds separate."""
    _seed_bcct("TX1", "BUCKET", "BUCKET#&x (BUCKET.CHILD)")
    _seed_bom("PROD1", [("PROD1", "BUCKET", "pcs")])
    _rebuild()
    rows = _rows()
    assert ("BUCKET", "hq") in rows
    assert ("BUCKET", "nb") in rows
    assert ("BUCKET", "unified") not in rows


def test_machinery_marking_flows_into_discovery():
    """A placeholder-only NB code carries customs_relevance so #35 can
    filter it out of bulk approval."""
    _seed_bcct("TX1", ".", "forklift (019.M)")
    _rebuild()
    row = _rows()[("019.M", "nb")]
    assert row["customs_relevance"] == "excluded_non_material"
