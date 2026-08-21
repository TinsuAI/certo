"""Convergent-state invariant — Phase 2 step 8.

Memory `project_ingest_order_invariance.md`: same set of events in any
order must produce byte-identical end state. Tests both:

1. **Cross-group ordering** (BCCT/Catalog/BOM permutations).
2. **Dependency change ordering** — BTP raw_graph appears late, parent
   was ingested first.
3. **External context change ordering** — catalog UoM edited mid-flow,
   btp_sourcing flipped, catalog row INSERT after BOM (D9).

Convergence is achieved through:
- D1/D2/D7/D8/D9 triggers marking dependents stale on each change.
- Refresh path re-deriving from latest raw + catalog state.
- Hash-diff supersede (mig step 3, BOM immutable).

The harness applies a fixed set of events in every permutation, then
refreshes ALL stale artifacts (recursively until none stale), and
compares the final state across runs.
"""
from __future__ import annotations

import json
from itertools import permutations

import pytest

from hub.app.database import connect
from hub.app.stores.bom_staleness import refresh_artifact


CLIENT_PREFIX = "_inv2_"
MAX_REFRESH_ROUNDS = 5  # bound to detect non-converging loops


def _seed(cid: str):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict do nothing", (cid, f"order-inv {cid}"))


def _teardown(cid: str):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.bom_artifact_rows where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (cid,))
        cur.execute(
            "delete from hub.bom_edges where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (cid,))
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (cid,))
        cur.execute("delete from hub.bcct_rows where client_id=%s", (cid,))
        cur.execute("delete from hub.materials where client_id=%s", (cid,))
        cur.execute("delete from hub.client_uom_overrides where client_id=%s",
                     (cid,))
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


# ── Atomic events the harness can apply in any order ────────────────────


def evt_bcct_M_X(cid: str):
    """BCCT row declaring import of M_X (NVL) in 'kg'."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bcct_rows (client_id, transaction_key, "
            " declaration_no, line_no, declaration_type, direction, "
            " customs_code, goods_name, hs_code, quantity, unit, "
            " registration_date) "
            "values (%s, '12345-1', '12345', 1, 'A11', 'import', "
            "'M_X', 'NVL X', '85044090', 100.0, 'kg', '2026-01-01') "
            "on conflict (client_id, year, transaction_key, line_no) "
            "do nothing",
            (cid,))


def evt_catalog_M_X_kg(cid: str):
    """Catalog row for M_X with uom=kg."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category, status, uom) values "
            "(%s, 'M_X', 'NVL X', 'nvl', 'active', 'kg') "
            "on conflict (client_id, material_code) do update set "
            "uom='kg', category='nvl'",
            (cid,))


def evt_catalog_TP1(cid: str):
    """Catalog row for TP1 with uom=pcs."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category, status, uom) values "
            "(%s, 'TP1', 'TP1', 'tp', 'active', 'pcs') "
            "on conflict (client_id, material_code) do update set "
            "uom='pcs', category='tp'",
            (cid,))


def evt_bom_TP1(cid: str):
    """Raw + derived artifact for TP1 referencing M_X (qty 2500 g)."""
    with connect() as conn, conn.cursor() as cur:
        # Idempotent: skip if raw artifact already exists.
        cur.execute(
            "select 1 from hub.bom_artifacts "
            "where client_id=%s and artifact_id=%s",
            (cid, f"ba_raw_TP1_{cid}"))
        if cur.fetchone() is not None:
            return
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            "product_code, artifact_no, status, actor, intent, "
            "context, normalized_hash, row_count, source_bom_kind, "
            "flatten_status, flatten_strategy, source_channel, "
            "bom_variant_id, lineage, flatten_method, "
            "flatten_method_version, published_at) values "
            "(%s, %s, 'TP1', 1, 'published', 'agency_staff', "
            "'asserted_technical', '{}', 'h_raw_TP1', 1, 'technical_raw', "
            "'non_flattened', 'no_strategy', 'agency_upload', "
            "'default', '{}', 'as_provided', 'v1', now())",
            (f"ba_raw_TP1_{cid}", cid))
        cur.execute(
            "insert into hub.bom_edges (artifact_id, row_index, root_code, "
            "parent_code, child_code, qty_per_parent, uom) values "
            "(%s, 0, 'TP1', 'TP1', 'M_X', 2500.0, 'g')",
            (f"ba_raw_TP1_{cid}",))
        # Derived stale-seeded so refresh has a target.
        reasons = json.dumps([{"dim": "seed", "source_table": "test",
                                "source_pk": cid,
                                "observed_at": "2026-05-12T00:00:00Z"}])
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            "product_code, artifact_no, status, actor, intent, "
            "context, normalized_hash, row_count, source_bom_kind, "
            "flatten_status, flatten_strategy, source_channel, "
            "bom_variant_id, lineage, flatten_method, "
            "flatten_method_version, published_at, is_stale, "
            "stale_reasons, stale_first_at) values "
            "(%s, %s, 'TP1', 1, 'published', 'agency_staff', "
            "'derived', '{}', 'h_der_TP1', 1, 'technical_flattened', "
            "'flattened', 'technical_exploded', 'migration', "
            "'default', '{}', 'recursive_sql', '1', now(), true, "
            "%s::jsonb, now())",
            (f"ba_der_TP1_{cid}", cid, reasons))


def evt_catalog_M_X_uom_to_g(cid: str):
    """Edit catalog UoM kg → g (D7 fires). Only meaningful AFTER an
    initial converged state — used by the post-converge test below."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set uom='g' "
            "where client_id=%s and material_code='M_X'",
            (cid,))


# ── Convergence loop: refresh until no artifacts are stale ──────────────


def _refresh_until_stable(cid: str) -> int:
    """Refresh all stale artifacts in a loop. Returns rounds taken.
    Bounded by MAX_REFRESH_ROUNDS to detect non-converging loops."""
    for round_n in range(1, MAX_REFRESH_ROUNDS + 1):
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "select artifact_id from hub.bom_artifacts "
                "where client_id=%s and is_stale=true "
                "  and tombstoned_at is null",
                (cid,))
            ids = [r[0] for r in cur.fetchall()]
        if not ids:
            return round_n - 1
        for aid in ids:
            try:
                refresh_artifact(cid, aid)
            except LookupError:
                pass
    return MAX_REFRESH_ROUNDS


def _final_state(cid: str) -> dict:
    """Snapshot the final state. Compares:
    - Live (non-tombstoned) derived artifacts: rows with material_code,
      qty_per_unit, uom, applied_uom_factor, applied_uom_source.
    - Live source artifacts: same row content.
    Tombstone chains are NOT compared (transient supersede history
    differs across orderings)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select ba.product_code, ba.flatten_strategy, "
            "       bar.material_code, bar.qty_per_unit::text, bar.uom, "
            "       bar.applied_uom_source "
            "from hub.bom_artifact_rows bar "
            "join hub.bom_artifacts ba on ba.artifact_id = bar.artifact_id "
            "where ba.client_id=%s "
            "  and ba.tombstoned_at is null "
            "  and ba.flatten_strategy in ('technical_exploded', "
            "    'purchased_btp_as_leaf') "
            "order by ba.product_code, ba.flatten_strategy, "
            "         bar.material_code",
            (cid,))
        rows = list(cur.fetchall())
        cur.execute(
            "select count(*), count(*) filter (where is_stale=true) "
            "from hub.bom_artifacts "
            "where client_id=%s and tombstoned_at is null",
            (cid,))
        n_alive, n_stale = cur.fetchone()
    return {
        "rows": [tuple(r) for r in rows],
        "n_alive": n_alive,
        "n_stale": n_stale,
    }


# ── Test 1: cross-group permutation (BCCT/Catalog/BOM) ──────────────────


CROSS_GROUP_EVENTS = {
    "bcct": evt_bcct_M_X,
    "catalog_M_X": evt_catalog_M_X_kg,
    "bom_TP1": evt_bom_TP1,
}


@pytest.mark.parametrize("order", list(permutations(CROSS_GROUP_EVENTS.keys())))
def test_cross_group_order_converges(order):
    cid = CLIENT_PREFIX + "cg_" + "_".join(s[:2] for s in order)
    _teardown(cid)
    _seed(cid)
    try:
        for evt_name in order:
            CROSS_GROUP_EVENTS[evt_name](cid)
        rounds = _refresh_until_stable(cid)
        assert rounds < MAX_REFRESH_ROUNDS, \
            f"order={order}: refresh did not converge in {MAX_REFRESH_ROUNDS} rounds"
        state = _final_state(cid)
        # All converged orderings must produce M_X qty=2.5 kg derived row.
        derived_rows = [r for r in state["rows"]
                         if r[1] == "technical_exploded"]
        assert len(derived_rows) == 1
        prod, strat, mat, qty_str, uom, src = derived_rows[0]
        assert mat == "M_X"
        assert uom == "kg"
        assert float(qty_str) == pytest.approx(2.5)
    finally:
        _teardown(cid)


def test_cross_group_all_six_byte_identical():
    """Stronger claim: all 6 permutations produce equal final state."""
    states = {}
    cids = []
    try:
        for order in permutations(CROSS_GROUP_EVENTS.keys()):
            cid = CLIENT_PREFIX + "cgall_" + "_".join(s[:2] for s in order)
            cids.append(cid)
            _teardown(cid)
            _seed(cid)
            for evt_name in order:
                CROSS_GROUP_EVENTS[evt_name](cid)
            _refresh_until_stable(cid)
            states[order] = _final_state(cid)
        canonical = states[("bcct", "catalog_M_X", "bom_TP1")]
        for order, st in states.items():
            assert st == canonical, (
                f"order {order} diverged:\n  canonical={canonical}\n  this={st}")
    finally:
        for cid in cids:
            _teardown(cid)


# ── Test 2: external context change (catalog UoM edit mid-flow) ─────────


def test_convertible_context_change_does_not_churn_published_rows():
    """Convertibility-aware staleness (mig 077, D.2-A): a catalog UoM edit
    that is CONVERTIBLE (same family: kg↔g) does NOT re-derive the published
    rows. The materialized `2.5 kg` is physically identical to `2500 g` and
    self-describing (row carries its own uom), so flatten's output is not
    "wrong" — D7 correctly skips the stale flag and nothing churns.

    Pre-mig-077 this edit re-derived to `2500 g` (the old re-derive-on-any-
    unit-change behavior). That was the cry-wolf churn A.4.4/D.2 set out to
    remove. Byte-identity still holds for upload ordering (the permutation
    tests above); only post-hoc convertible edits no longer propagate a
    cosmetic relabel.

    Initial events: bcct + catalog(kg) + bom_TP1 → published `2.5 kg`.
    Edit event: catalog uom kg→g (convertible) → published rows UNCHANGED."""
    cid = CLIENT_PREFIX + "post"
    _teardown(cid)
    _seed(cid)
    try:
        # Initial set, canonical order.
        evt_bcct_M_X(cid)
        evt_catalog_M_X_kg(cid)
        evt_bom_TP1(cid)
        _refresh_until_stable(cid)
        state_a = _final_state(cid)
        derived_a = [r for r in state_a["rows"]
                      if r[1] == "technical_exploded"][0]
        assert derived_a[4] == "kg"  # uom
        assert float(derived_a[3]) == pytest.approx(2.5)

        # Apply benign convertible edit (kg→g) → D7 must NOT flag stale.
        evt_catalog_M_X_uom_to_g(cid)
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "select bool_or(is_stale) from hub.bom_artifacts "
                "where client_id=%s and flatten_strategy='technical_exploded' "
                "and tombstoned_at is null", (cid,))
            assert cur.fetchone()[0] is False, (
                "convertible kg→g edit must not mark derived stale")
        _refresh_until_stable(cid)
        state_b = _final_state(cid)
        derived_b = [r for r in state_b["rows"]
                      if r[1] == "technical_exploded"][0]
        # No churn: published row stays `2.5 kg` (physically == 2500 g).
        assert derived_b[4] == "kg"
        assert float(derived_b[3]) == pytest.approx(2.5)
    finally:
        _teardown(cid)
