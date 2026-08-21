"""Catalog phase 5 — bulk approval (#35).

Covers the filter-as-rule predicate, the batched accept (materials +
one audit event + rejection lift + automap), and the mig-093 batching
of the D9 staleness trigger: the per-row trigger is suppressed via the
hub.bulk_load GUC and hub.materials_propagate_bulk marks the same
artifact sets once. A parity test locks the batched path to the
per-row path.
"""
from __future__ import annotations

import pytest

from hub.app.database import connect
from hub.app.routes.catalog_discovery import _filter_pending
from hub.app.stores.catalog_discovery import (
    accept_code,
    bulk_accept_codes,
    reject_code,
)


CLIENT = "_test_bulk_accept"


@pytest.fixture(autouse=True)
def setup():
    _cleanup()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, 'bulk test') "
            "on conflict do nothing",
            (CLIENT,),
        )
    yield
    _cleanup()


def _cleanup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bom_artifact_rows bar using hub.bom_artifacts a "
                    "where bar.artifact_id=a.artifact_id and a.client_id=%s", (CLIENT,))
        cur.execute("delete from hub.bom_edges e using hub.bom_artifacts a "
                    "where e.artifact_id=a.artifact_id and a.client_id=%s", (CLIENT,))
        for tbl in ("bom_artifacts", "catalog_rejections", "bcct_nb_codes",
                    "code_mappings", "bcct_rows", "materials"):
            cur.execute(f"delete from hub.{tbl} where client_id=%s", (CLIENT,))
        cur.execute(
            "delete from hub.bom_audit_events where client_id=%s "
            "and event_type in ('catalog_bulk_accept','catalog_candidate_decision')",
            (CLIENT,),
        )
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


# ── Row builder for the pure-predicate + store tests ────────────────────

def _row(code, *, kind="nb", suggested="nvl", leaf=True, sources=("bom",),
         observed=5, sample="hàng mẫu", relevance=None, status="pending",
         psource=None, uom="pcs"):
    return {
        "code": code, "code_kind": kind, "suggested_category": suggested,
        "leaf_in_flattened_bom": leaf, "sources": list(sources),
        "observed_count": observed, "sample_text": sample,
        "customs_relevance": relevance, "status": status,
        "inferred_production_source": psource, "uom": uom,
    }


# ── Filter predicate (the rule) — pure, no DB ───────────────────────────

def test_filter_excludes_machinery_by_default():
    rows = [_row("A"), _row("M", relevance="excluded_non_material")]
    out = [r["code"] for r in _filter_pending(rows)]
    assert out == ["A"]


def test_filter_show_machinery_includes_it():
    rows = [_row("A"), _row("M", relevance="excluded_non_material")]
    out = {r["code"] for r in _filter_pending(rows, show_machinery=True)}
    assert out == {"A", "M"}


def test_filter_leaf_only():
    rows = [_row("A", leaf=True), _row("B", leaf=False)]
    out = [r["code"] for r in _filter_pending(rows, leaf=True)]
    assert out == ["A"]


def test_filter_min_observed_threshold():
    rows = [_row("A", observed=10), _row("B", observed=2)]
    out = [r["code"] for r in _filter_pending(rows, min_observed=5)]
    assert out == ["A"]


def test_filter_skips_non_pending():
    rows = [_row("A"), _row("R", status="rejected")]
    out = [r["code"] for r in _filter_pending(rows)]
    assert out == ["A"]


# ── bulk_accept_codes — materials + audit ───────────────────────────────

def _materials():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select material_code, status, source, category, code_kind, uom "
            "from hub.materials where client_id=%s order by material_code",
            (CLIENT,),
        )
        return cur.fetchall()


def _bulk_events():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select actor, product_code, details from hub.bom_audit_events "
            "where client_id=%s and event_type='catalog_bulk_accept'",
            (CLIENT,),
        )
        return cur.fetchall()


def test_bulk_accept_creates_active_materials_by_stream_source():
    rows = [_row("019.A", sources=("bcct", "bom")),
            _row("019.B", sources=("bom",)),
            _row("019.C", sources=("bqd",))]
    result = bulk_accept_codes(CLIENT, rows=rows, actor="op@x", predicate={})
    assert result["accepted"] == 3
    mats = {m[0]: m for m in _materials()}
    assert mats["019.A"][1:4] == ("active", "bcct_observed", "nvl")
    assert mats["019.B"][2] == "bom_observed"
    assert mats["019.C"][2] == "client_declared"


def test_bulk_accept_leaf_without_suggestion_defaults_nvl():
    rows = [_row("L1", suggested=None, leaf=True)]
    result = bulk_accept_codes(CLIENT, rows=rows, actor="op@x", predicate={})
    assert result["accepted"] == 1
    assert _materials()[0][3] == "nvl"


def test_bulk_accept_skips_uncategorizable():
    rows = [_row("OK", suggested="nvl"),
            _row("SKIP", suggested=None, leaf=False)]
    result = bulk_accept_codes(CLIENT, rows=rows, actor="op@x", predicate={})
    assert result["accepted"] == 1
    assert result["skipped"] == 1
    assert [m[0] for m in _materials()] == ["OK"]


def test_bulk_accept_writes_one_audit_event_with_predicate_and_codes():
    rows = [_row("P1"), _row("P2")]
    bulk_accept_codes(CLIENT, rows=rows, actor="op@x",
                      predicate={"leaf": True, "min_observed": 3})
    events = _bulk_events()
    assert len(events) == 1
    actor, product_code, details = events[0]
    assert actor == "op@x"
    assert product_code is None
    assert details["count"] == 2
    assert set(details["codes"]) == {"P1", "P2"}
    assert details["predicate"] == {"leaf": True, "min_observed": 3}


def test_bulk_accept_lifts_prior_rejection():
    reject_code(CLIENT, code="RJ", code_kind="nb", actor="op@x", reason="meh")
    bulk_accept_codes(CLIENT, rows=[_row("RJ")], actor="op@x", predicate={})
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select count(*) from hub.catalog_rejections "
                    "where client_id=%s and code='RJ'", (CLIENT,))
        assert cur.fetchone()[0] == 0


def test_bulk_accept_skips_codes_already_in_catalog():
    accept_code(CLIENT, code="EXIST", code_kind="nb", actor="op@x",
                name="x", category="nvl", sources=["bom"])
    result = bulk_accept_codes(
        CLIENT, rows=[_row("EXIST"), _row("NEW")], actor="op@x", predicate={})
    assert result["accepted"] == 1
    assert set(result["codes"]) == {"NEW"}


def test_bulk_accept_empty_is_noop():
    result = bulk_accept_codes(CLIENT, rows=[], actor="op@x", predicate={})
    assert result == {"accepted": 0, "skipped": 0, "codes": []}
    assert _bulk_events() == []


# ── Automap parity: _bulk_automap must match per-item _auto_map ──────────

def _seed_link(txn, customs, nb):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bcct_rows (client_id, transaction_key, line_no, "
            " declaration_no, customs_code, goods_name, registration_date, "
            " payload) values (%s, %s, '1', %s, %s, %s, '2026-04-01', "
            " '{}'::jsonb)",
            (CLIENT, txn, txn, customs, f"{customs} ({nb})"),
        )
        cur.execute(
            "insert into hub.bcct_nb_codes (client_id, transaction_key, "
            " line_no, nb_code) values (%s, %s, '1', %s) on conflict do nothing",
            (CLIENT, txn, nb),
        )


def _seed_hq_material(code):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            " category, status, source, code_kind) "
            "values (%s, %s, 'b', 'nvl', 'active', 'bcct_observed', 'hq')",
            (CLIENT, code),
        )


def _mappings():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select internal_code, customs_code from hub.code_mappings "
                    "where client_id=%s order by 1, 2", (CLIENT,))
        return cur.fetchall()


def test_bulk_automap_matches_per_item_automap():
    """The batched NB↔HQ mapping must produce the same rows the per-item
    accept_code path would (the two SQL bodies are near-verbatim)."""
    _seed_link("TXA", "BUCKET", "019.A")
    _seed_hq_material("BUCKET")

    # Per-item accept forms the mapping.
    accept_code(CLIENT, code="019.A", code_kind="nb", actor="op@x",
                name="a", category="nvl", sources=["bcct"])
    per_item = _mappings()

    # Reset the nb material + mappings, keep the link + hq material.
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.code_mappings where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.materials where client_id=%s "
                    "and material_code='019.A'", (CLIENT,))

    # Bulk accept forms the same mapping.
    bulk_accept_codes(CLIENT, rows=[_row("019.A", kind="nb", sources=("bcct",))],
                      actor="op@x", predicate={})
    bulk = _mappings()

    assert per_item == bulk == [("019.A", "BUCKET")]


# ── Staleness batching: seed clean BOM artifacts, prove parity ──────────

def _seed_artifact(cur, artifact_id, strategy, leaf_codes,
                   flatten_status="flattened", row_uom="EA"):
    cur.execute(
        """
        insert into hub.bom_artifacts
          (artifact_id, client_id, product_code, artifact_no, actor, intent,
           normalized_hash, source_bom_kind, flatten_status, flatten_strategy,
           source_channel, flatten_method, flatten_method_version,
           lineage_root_id)
        values (%s, %s, 'ROOT', 1, 'system', 'derived', %s, 'technical_raw',
                %s, %s, 'migration', 'm', 'v1', %s)
        """,
        (artifact_id, CLIENT, artifact_id, flatten_status, strategy,
         artifact_id),
    )
    for i, code in enumerate(leaf_codes):
        cur.execute(
            "insert into hub.bom_artifact_rows "
            "(artifact_id, row_index, material_code, qty_per_unit, uom) "
            "values (%s, %s, %s, 1, %s)",
            (artifact_id, i, code, row_uom),
        )


def _flags():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select artifact_id, is_stale, has_uom_drift from hub.bom_artifacts "
            "where client_id=%s order by artifact_id", (CLIENT,))
        return cur.fetchall()


def _reset_flags_and_materials():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute(
            "update hub.bom_artifacts set is_stale=false, stale_reasons='[]', "
            "stale_first_at=null, stale_resolved_at=null, has_uom_drift=false, "
            "uom_drift_reasons='[]', uom_drift_first_at=null, "
            "uom_drift_resolved_at=null where client_id=%s", (CLIENT,))


# Leaf rows carry uom=EA; the accepted material carries a cross-family
# uom (KILO-GRAMMES) so has_drift_remaining is true → the mig-071 trigger
# actually marks. That makes the suppression + parity checks non-vacuous.
_MAT_UOM = "KILO-GRAMMES"


def _seed_two_arms():
    """A derived artifact (staleness arm) and a source artifact (drift
    arm), both referencing leaf code X with a UoM that will drift."""
    with connect() as conn, conn.cursor() as cur:
        _seed_artifact(cur, "ART_DERIVED", "technical_exploded", ["X"])
        _seed_artifact(cur, "ART_SOURCE", "manual_flat_as_provided", ["X"])


def test_guc_suppresses_per_row_trigger():
    """With hub.bulk_load='on', inserting a material whose UoM WOULD drift
    the referencing BOM rows marks nothing — the D9 trigger no-ops."""
    _seed_two_arms()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("set local hub.bulk_load='on'")
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category, status, source, code_kind, uom) "
            "values (%s, 'X', 'x', 'nvl', 'active', 'bom_observed', 'nb', %s)",
            (CLIENT, _MAT_UOM),
        )
        cur.execute("select bool_or(is_stale), bool_or(has_uom_drift) "
                    "from hub.bom_artifacts where client_id=%s", (CLIENT,))
        assert cur.fetchone() == (False, False)
        conn.rollback()


def test_batched_propagation_matches_per_row_trigger():
    _seed_two_arms()

    # Arm A: per-row trigger (normal accept, GUC off).
    accept_code(CLIENT, code="X", code_kind="nb", actor="op@x",
                name="x", category="nvl", uom=_MAT_UOM, sources=["bom"])
    arm_a = _flags()

    _reset_flags_and_materials()

    # Arm B: bulk path (GUC-suppressed insert + materials_propagate_bulk).
    bulk_accept_codes(CLIENT, rows=[_row("X", uom=_MAT_UOM)], actor="op@x",
                      predicate={})
    arm_b = _flags()

    assert arm_a == arm_b
    # And the effect is real (not both empty): derived stale, source drifts.
    flags = {a: (s, d) for a, s, d in arm_b}
    assert flags["ART_DERIVED"] == (True, False)
    assert flags["ART_SOURCE"] == (False, True)
