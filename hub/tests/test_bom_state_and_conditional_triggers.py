"""Mig 068 (state column) + mig 069 (conditional D7/D9 triggers).

Verifies:
- `state` generated column derives correct value across all input
  combinations (clean / needs_refresh / needs_input).
- `hub.is_uom_aligned` returns expected results for case, alias,
  family, and unknown-token cases.
- D7 trigger SKIPS the flag when alias-aligned (the false-positive
  case that prompted the audit: G → EA fix where BOM rows are EA).
- D7 trigger STILL fires when not alias-aligned.
- D9 trigger (catalog insert) honors the same alignment check.
"""
from __future__ import annotations

import pytest

from hub.app.database import connect


CLIENT = "_state_trigger_test"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict do nothing",
            (CLIENT, "state trigger test"))
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
        cur.execute("delete from hub.bom_artifacts where client_id=%s",
                     (CLIENT,))
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def _seed_material(cur, code, uom):
    cur.execute(
        "insert into hub.materials (client_id, material_code, name, "
        "category, status, uom) values (%s, %s, %s, 'nvl', 'active', %s) "
        "on conflict (client_id, material_code) do update set "
        "uom=excluded.uom",
        (CLIENT, code, code, uom))


def _insert_artifact(cur, artifact_id, product_code, strategy, source_kind,
                      rows=()):
    cur.execute(
        "insert into hub.bom_artifacts (artifact_id, client_id, "
        "product_code, artifact_no, status, actor, intent, "
        "context, normalized_hash, row_count, source_bom_kind, "
        "flatten_status, flatten_strategy, source_channel, "
        "bom_variant_id, lineage, flatten_method, "
        "flatten_method_version, published_at) "
        "values (%s, %s, %s, 1, 'published', 'agency_staff', "
        "'asserted_technical', '{}', %s, %s, %s, %s, %s, "
        "'agency_upload', 'default', '{}', 'as_provided', 'v1', now())",
        (artifact_id, CLIENT, product_code, f"h_{artifact_id}",
         len(rows), source_kind,
         "not_applicable" if strategy == "manual_flat_as_provided"
            else ("non_flattened" if source_kind == "technical_raw"
                  else "flattened"),
         strategy))
    for idx, (mat, qty, uom) in enumerate(rows):
        cur.execute(
            "insert into hub.bom_artifact_rows (artifact_id, row_index, "
            "material_code, qty_per_unit, uom) values (%s, %s, %s, %s, %s)",
            (artifact_id, idx, mat, qty, uom))


def _insert_edge(cur, artifact_id, parent, child, qty, uom, row_index=0):
    cur.execute(
        "insert into hub.bom_edges (artifact_id, row_index, root_code, "
        "parent_code, child_code, qty_per_parent, uom) "
        "values (%s, %s, %s, %s, %s, %s, %s)",
        (artifact_id, row_index, parent, parent, child, qty, uom))


def _read_state(cur, aid):
    cur.execute("select state from hub.bom_artifacts where artifact_id=%s",
                 (aid,))
    return cur.fetchone()[0]


# ─── Mig 069 helper: alignment ─────────────────────────────────────────


@pytest.mark.parametrize("a, b, expected", [
    ("kg", "kg", True),                  # case-insensitive equal
    ("KG", "kg", True),
    ("kilogram", "kg", True),            # alias
    ("KILOGRAMS", "kg", True),
    ("pieces", "ea", True),              # both → 'pcs' canonical
    ("EA", "PIECES", True),
    ("ea", "sets", False),               # different families (count vs assembly)
    ("g", "ea", False),                  # mass vs count
    ("kg", "g", False),                  # same family, different canonical
    ("", "ea", False),                   # empty conservative
    (None, "ea", False),                 # NULL conservative
    ("ea", None, False),
    ("UNKNOWN_BLOB", "ea", False),       # unknown alias conservative
])
def test_is_uom_aligned(a, b, expected):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select hub.is_uom_aligned(%s, %s)", (a, b))
        assert cur.fetchone()[0] is expected


# ─── Mig 068: state column derives correctly ─────────────────────────


def test_state_clean_default():
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_CLEAN", uom="kg")
        _insert_artifact(cur, "ba_clean", "P_C", "technical_exploded",
                          source_kind="technical_flattened",
                          rows=[("M_CLEAN", 1.0, "kg")])
        assert _read_state(cur, "ba_clean") == "clean"


def test_state_needs_refresh_on_category_change():
    """Pure dependency-change (no UoM/factor issue) → needs_refresh."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_CAT", uom="kg")
        _insert_artifact(cur, "ba_cat", "P_CAT", "technical_exploded",
                          source_kind="technical_flattened",
                          rows=[("M_CAT", 1.0, "kg")])
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set category='btp_sx' "
            "where client_id=%s and material_code='M_CAT'", (CLIENT,))
        assert _read_state(cur, "ba_cat") == "needs_refresh"


def test_state_needs_input_on_factor_missing_reason():
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_FACT", uom="kg")
        _insert_artifact(cur, "ba_fact", "P_F", "technical_exploded",
                          source_kind="technical_flattened",
                          rows=[("M_FACT", 1.0, "kg")])
        cur.execute(
            "update hub.bom_artifacts "
            "set is_stale=true, "
            "    stale_reasons='[{\"dim\":\"factor_missing\"}]'::jsonb "
            "where artifact_id='ba_fact'")
        assert _read_state(cur, "ba_fact") == "needs_input"


def test_state_needs_input_on_unconfirmed_default():
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_UD", uom="kg")
        _insert_artifact(cur, "ba_ud", "P_UD", "technical_exploded",
                          source_kind="technical_flattened",
                          rows=[("M_UD", 1.0, "kg")])
        cur.execute(
            "update hub.bom_artifacts "
            "set is_stale=true, "
            "    stale_reasons='[{\"dim\":\"unconfirmed_default_1to1\"}]'::jsonb "
            "where artifact_id='ba_ud'")
        assert _read_state(cur, "ba_ud") == "needs_input"


def test_state_needs_input_for_raw_graph_uom_drift():
    """raw_graph + has_uom_drift → needs_input (cannot auto-refresh)."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_RAW", uom="kg")
        _insert_artifact(cur, "ba_raw", "P_RAW", "no_strategy",
                          source_kind="technical_raw")
        cur.execute(
            "update hub.bom_artifacts "
            "set has_uom_drift=true, "
            "    uom_drift_reasons='[{\"dim\":\"materials_uom\"}]'::jsonb "
            "where artifact_id='ba_raw'")
        assert _read_state(cur, "ba_raw") == "needs_input"


def test_state_needs_refresh_for_manual_flat_uom_drift():
    """manual_flat + has_uom_drift + only materials_uom dim →
    needs_refresh (manual_flat_as_provided refresh re-applies convert)."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_MF", uom="kg")
        _insert_artifact(cur, "ba_mf", "P_MF", "manual_flat_as_provided",
                          source_kind="technical_flattened",
                          rows=[("M_MF", 1.0, "kg")])
        cur.execute(
            "update hub.bom_artifacts "
            "set has_uom_drift=true, "
            "    uom_drift_reasons='[{\"dim\":\"materials_uom\"}]'::jsonb "
            "where artifact_id='ba_mf'")
        assert _read_state(cur, "ba_mf") == "needs_refresh"


def test_state_tombstoned_artifact_is_clean():
    """Mig 067 trigger clears flags on tombstone → state derives clean."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_DEAD", uom="kg")
        _insert_artifact(cur, "ba_dead", "P_DEAD", "technical_exploded",
                          source_kind="technical_flattened",
                          rows=[("M_DEAD", 1.0, "kg")])
        cur.execute(
            "update hub.bom_artifacts set is_stale=true, "
            "    stale_reasons='[{\"dim\":\"factor_missing\"}]'::jsonb "
            "where artifact_id='ba_dead'")
        cur.execute(
            "update hub.bom_artifacts set tombstoned_at=now(), "
            "tombstone_reason='dead' where artifact_id='ba_dead'")
        # Mig 067 trigger cleared flags. State derives → clean.
        assert _read_state(cur, "ba_dead") == "clean"


# ─── Mig 069: conditional D7 — alias-aligned skip ────────────────────


def test_d7_skips_flag_when_new_uom_alias_aligned():
    """The audit case: catalog uom changes from G → EA. BOM rows have
    uom=EA. New catalog uom EA alias-aligns with BOM row uom EA →
    trigger must NOT flag stale. Pre-mig-069 would flag → 1,206
    false-positive Johnson rows."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_ALIGN", uom="g")
        _insert_artifact(cur, "ba_align", "P_ALIGN", "technical_exploded",
                          source_kind="technical_flattened",
                          rows=[("M_ALIGN", 1.0, "EA")])  # BOM says EA
    # Change catalog g → EA. BOM has EA. is_uom_aligned(EA, EA) → true.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set uom='EA' "
            "where client_id=%s and material_code='M_ALIGN'", (CLIENT,))
        cur.execute(
            "select is_stale, state from hub.bom_artifacts "
            "where artifact_id='ba_align'")
        is_stale, state = cur.fetchone()
        assert is_stale is False, "alignment check should have prevented flag"
        assert state == "clean"


def test_d7_still_flags_when_uom_not_aligned():
    """Sanity: when NEW.uom truly differs (e.g., EA → KG, cross-family),
    trigger still flags."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_NOALIGN", uom="EA")
        _insert_artifact(cur, "ba_noalign", "P_N", "technical_exploded",
                          source_kind="technical_flattened",
                          rows=[("M_NOALIGN", 1.0, "EA")])
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set uom='kg' "
            "where client_id=%s and material_code='M_NOALIGN'", (CLIENT,))
        cur.execute(
            "select is_stale, state from hub.bom_artifacts "
            "where artifact_id='ba_noalign'")
        is_stale, state = cur.fetchone()
        assert is_stale is True
        assert state == "needs_refresh"


def test_d7_aligned_on_raw_graph_skips_uom_drift_flag():
    """Raw graph: bom_edges has uom=EA. Catalog G → EA.
    has_uom_drift should NOT flip."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_RAW_AL", uom="g")
        _insert_artifact(cur, "ba_raw_al", "P_RAL", "no_strategy",
                          source_kind="technical_raw")
        _insert_edge(cur, "ba_raw_al", "P_RAL", "M_RAW_AL", 1.0, "EA")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set uom='EA' "
            "where client_id=%s and material_code='M_RAW_AL'", (CLIENT,))
        cur.execute(
            "select has_uom_drift, state from hub.bom_artifacts "
            "where artifact_id='ba_raw_al'")
        drift, state = cur.fetchone()
        assert drift is False
        assert state == "clean"


def test_d7_aligned_on_manual_flat_skips_drift():
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_MF_AL", uom="g")
        _insert_artifact(cur, "ba_mf_al", "P_MFAL",
                          "manual_flat_as_provided",
                          source_kind="technical_flattened",
                          rows=[("M_MF_AL", 1.0, "EA")])
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set uom='EA' "
            "where client_id=%s and material_code='M_MF_AL'", (CLIENT,))
        cur.execute(
            "select has_uom_drift, state from hub.bom_artifacts "
            "where artifact_id='ba_mf_al'")
        drift, state = cur.fetchone()
        assert drift is False
        assert state == "clean"


def test_d7_category_change_still_flags_when_uom_aligned():
    """Multi-column update: changing category + uom (aligned) — category
    portion still flags, uom portion is skipped via alignment check."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_MIX", uom="g")
        _insert_artifact(cur, "ba_mix", "P_MIX", "technical_exploded",
                          source_kind="technical_flattened",
                          rows=[("M_MIX", 1.0, "EA")])
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set uom='EA', category='btp_sx' "
            "where client_id=%s and material_code='M_MIX'", (CLIENT,))
        cur.execute(
            "select is_stale, stale_reasons, state from hub.bom_artifacts "
            "where artifact_id='ba_mix'")
        is_stale, reasons, state = cur.fetchone()
        assert is_stale is True  # category dim fired
        dims = {r["dim"] for r in reasons}
        assert "catalog_category" in dims
        assert "materials_uom" not in dims  # alignment skipped uom flag
        assert state == "needs_refresh"


# ─── Mig 069: conditional D9 (catalog insert) ────────────────────────


def test_d9_aligned_catalog_insert_skips_flag():
    """BOM uploaded before catalog (raw_graph with uom=EA), catalog
    INSERT later with uom=PIECES (alias of EA) → D9 must skip flag."""
    with connect() as conn, conn.cursor() as cur:
        # No catalog row yet.
        _insert_artifact(cur, "ba_d9_al", "P_D9_AL", "no_strategy",
                          source_kind="technical_raw")
        _insert_edge(cur, "ba_d9_al", "P_D9_AL", "M_D9_AL", 1.0, "EA")
    # Now INSERT catalog with PIECES (alias).
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_D9_AL", uom="PIECES")
        cur.execute(
            "select has_uom_drift, state from hub.bom_artifacts "
            "where artifact_id='ba_d9_al'")
        drift, state = cur.fetchone()
        assert drift is False
        assert state == "clean"


def test_d9_unaligned_catalog_insert_still_flags():
    with connect() as conn, conn.cursor() as cur:
        _insert_artifact(cur, "ba_d9_no", "P_D9_NO", "no_strategy",
                          source_kind="technical_raw")
        _insert_edge(cur, "ba_d9_no", "P_D9_NO", "M_D9_NO", 1.0, "EA")
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_D9_NO", uom="kg")
        cur.execute(
            "select has_uom_drift, state from hub.bom_artifacts "
            "where artifact_id='ba_d9_no'")
        drift, state = cur.fetchone()
        assert drift is True
        assert state == "needs_input"  # raw + uom_drift → needs_input


# ─── Mig 071: has_drift_remaining (override-aware) ───────────────────


def test_has_drift_remaining_no_bom_uom_returns_false():
    """NULL or empty BOM uom → no drift to compare (conservative)."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_HD_1", uom="kg")
        cur.execute("select hub.has_drift_remaining(%s, %s, NULL)",
                     (CLIENT, "M_HD_1"))
        assert cur.fetchone()[0] is False
        cur.execute("select hub.has_drift_remaining(%s, %s, '')",
                     (CLIENT, "M_HD_1"))
        assert cur.fetchone()[0] is False


def test_has_drift_remaining_no_catalog_uom_returns_false():
    with connect() as conn, conn.cursor() as cur:
        # Insert material with NULL uom.
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category, status, uom) values (%s, %s, %s, 'nvl', 'active', NULL)",
            (CLIENT, "M_NO_UOM", "M_NO_UOM"))
        cur.execute("select hub.has_drift_remaining(%s, %s, 'EA')",
                     (CLIENT, "M_NO_UOM"))
        assert cur.fetchone()[0] is False


def test_has_drift_remaining_alias_aligned_returns_false():
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_HD_AL", uom="PIECES")
        cur.execute("select hub.has_drift_remaining(%s, %s, 'EA')",
                     (CLIENT, "M_HD_AL"))
        assert cur.fetchone()[0] is False


def test_has_drift_remaining_cross_family_no_override_returns_true():
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_HD_XF", uom="kg")
        cur.execute("select hub.has_drift_remaining(%s, %s, 'EA')",
                     (CLIENT, "M_HD_XF"))
        assert cur.fetchone()[0] is True


def test_has_drift_remaining_cross_family_with_override_returns_false():
    """Staff override exists (EA→kg=0.5) → resolved, no drift."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_HD_OV", uom="kg")
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, %s, 'EA', 'kg', 0.5, 'staff_form')",
            (CLIENT, "M_HD_OV"))
        cur.execute("select hub.has_drift_remaining(%s, %s, 'EA')",
                     (CLIENT, "M_HD_OV"))
        assert cur.fetchone()[0] is False


def test_d7_skips_flag_when_override_resolves_drift():
    """Audit case: EA→kg pair flagged as cross-family by alias check,
    but staff override (EA→kg factor=0.5) exists. Trigger v2 (mig 071)
    must skip flagging because has_drift_remaining returns false."""
    with connect() as conn, conn.cursor() as cur:
        # Bootstrap material with an unrelated uom; override targets kg.
        _seed_material(cur, "M_D7_OV", uom="g")  # pre-state mass family
        _insert_artifact(cur, "ba_d7_ov", "P_D7_OV", "technical_exploded",
                          source_kind="technical_flattened",
                          rows=[("M_D7_OV", 1.0, "EA")])  # BOM uses EA
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, %s, 'EA', 'kg', 0.5, 'staff_form') "
            "on conflict do nothing",
            (CLIENT, "M_D7_OV"))
    # Now change catalog uom g → kg. has_drift_remaining(EA, kg) sees
    # the override → returns false → trigger must NOT flag.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set uom='kg' "
            "where client_id=%s and material_code='M_D7_OV'", (CLIENT,))
        cur.execute(
            "select is_stale, state from hub.bom_artifacts "
            "where artifact_id='ba_d7_ov'")
        is_stale, state = cur.fetchone()
        assert is_stale is False
        assert state == "clean"


# ─── A5: reconcile_for_material self-heal helper ─────────────────────


def test_reconcile_clears_flag_when_override_now_resolves_drift():
    """After insert_factor wires reconcile, a pre-existing flagged
    derived artifact should clear once the override fills the gap."""
    from hub.app.stores.bom_staleness import reconcile_for_material
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_REC", uom="kg")
        _insert_artifact(cur, "ba_rec", "P_REC", "technical_exploded",
                          source_kind="technical_flattened",
                          rows=[("M_REC", 1.0, "EA")])
        # Manually flag the artifact (simulating prior trigger fire that
        # has since been resolved by adding an override).
        cur.execute(
            "update hub.bom_artifacts set is_stale=true, "
            "stale_reasons='[{\"dim\":\"materials_uom\"}]'::jsonb "
            "where artifact_id='ba_rec'")
    # Now insert the override that resolves it.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, %s, 'EA', 'kg', 0.5, 'staff_form') "
            "on conflict do nothing",
            (CLIENT, "M_REC"))
    # reconcile should re-derive (refresh_artifact) → new artifact minted
    # with applied factor → clean. Old artifact tombstoned with reasons
    # preserved.
    result = reconcile_for_material(CLIENT, "M_REC")
    # `refreshed` counts artifacts cleared after re-derive. Cap-deferred=0.
    assert result["refreshed"] == 1
    assert result["deferred"] == 0


def test_reconcile_clears_raw_graph_flag_when_alignment_now_holds():
    """raw_graph cannot refresh, but reconcile re-checks alignment via
    has_drift_remaining and clears has_uom_drift if all edges resolved."""
    from hub.app.stores.bom_staleness import reconcile_for_material
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_RAW_REC", uom="kg")
        _insert_artifact(cur, "ba_raw_rec", "P_RAW_REC", "no_strategy",
                          source_kind="technical_raw")
        _insert_edge(cur, "ba_raw_rec", "P_RAW_REC", "M_RAW_REC", 1.0, "EA")
        # Pre-flag (simulating accumulated drift before override added).
        cur.execute(
            "update hub.bom_artifacts set has_uom_drift=true, "
            "uom_drift_reasons='[{\"dim\":\"materials_uom\"}]'::jsonb "
            "where artifact_id='ba_raw_rec'")
    # Add override resolving EA→kg.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, %s, 'EA', 'kg', 0.5, 'staff_form') "
            "on conflict do nothing",
            (CLIENT, "M_RAW_REC"))
    result = reconcile_for_material(CLIENT, "M_RAW_REC")
    assert result["cleared"] == 1
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select has_uom_drift, state from hub.bom_artifacts "
            "where artifact_id='ba_raw_rec'")
        drift, state = cur.fetchone()
        assert drift is False
        assert state == "clean"


def test_reconcile_caps_at_50_defers_rest():
    """When a heavily-referenced material edit would touch >50 artifacts,
    only 50 are refreshed synchronously and the rest are deferred."""
    from hub.app.stores.bom_staleness import reconcile_for_material
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_CAP", uom="kg")
        # Pre-flag 60 artifacts referencing M_CAP.
        for i in range(60):
            aid = f"ba_cap_{i:02d}"
            _insert_artifact(cur, aid, f"P_CAP_{i:02d}", "technical_exploded",
                              source_kind="technical_flattened",
                              rows=[("M_CAP", 1.0, "EA")])
            cur.execute(
                "update hub.bom_artifacts set is_stale=true, "
                "stale_reasons='[{\"dim\":\"materials_uom\"}]'::jsonb "
                "where artifact_id=%s", (aid,))
    result = reconcile_for_material(CLIENT, "M_CAP", cap=50)
    assert result["deferred"] == 10


# ─── Mig 077: has_drift_remaining mirrors classify_uom_relation ──────────
# Same-family base_factor + tier-A now resolve (no drift), so the D7 trigger
# stops re-flagging them on a benign catalog edit. tier-B still flags
# (covered by test_d7_still_flags_when_uom_not_aligned: EA→kg).


def test_d7_skips_flag_when_same_family_base_factor():
    """Catalog g → kg, BOM rows in g. Same mass family → base_factor
    converts → no drift. Pre-mig-077 (alias-only) flagged this."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_SF", uom="g")
        _insert_artifact(cur, "ba_sf", "P_SF", "technical_exploded",
                          source_kind="technical_flattened",
                          rows=[("M_SF", 1.0, "g")])
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set uom='kg' "
            "where client_id=%s and material_code='M_SF'", (CLIENT,))
        cur.execute(
            "select is_stale, state from hub.bom_artifacts "
            "where artifact_id='ba_sf'")
        is_stale, state = cur.fetchone()
        assert is_stale is False
        assert state == "clean"


def test_d7_skips_flag_when_tier_a_cross_family():
    """Catalog SETS → EA, BOM rows in SETS. assembly↔count is tier-A
    (1:1 convertible-by-assumption) → no drift flag on edit."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_TA", uom="SETS")
        _insert_artifact(cur, "ba_ta", "P_TA", "technical_exploded",
                          source_kind="technical_flattened",
                          rows=[("M_TA", 1.0, "SETS")])
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set uom='EA' "
            "where client_id=%s and material_code='M_TA'", (CLIENT,))
        cur.execute(
            "select is_stale, state from hub.bom_artifacts "
            "where artifact_id='ba_ta'")
        is_stale, state = cur.fetchone()
        assert is_stale is False
        assert state == "clean"


def test_reconcile_clears_same_family_false_positive():
    """Backfill spirit at runtime: a raw_graph pre-flagged with materials_uom
    drift clears once has_drift_remaining (widened) sees the same-family
    pair as convertible — no override needed."""
    from hub.app.stores.bom_staleness import reconcile_for_material
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_SF_REC", uom="kg")
        _insert_artifact(cur, "ba_sf_rec", "P_SF_REC", "no_strategy",
                          source_kind="technical_raw")
        _insert_edge(cur, "ba_sf_rec", "P_SF_REC", "M_SF_REC", 1.0, "g")
        cur.execute(
            "update hub.bom_artifacts set has_uom_drift=true, "
            "uom_drift_reasons='[{\"dim\":\"materials_uom\"}]'::jsonb "
            "where artifact_id='ba_sf_rec'")
    result = reconcile_for_material(CLIENT, "M_SF_REC")
    assert result["cleared"] == 1
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select has_uom_drift, state from hub.bom_artifacts "
            "where artifact_id='ba_sf_rec'")
        drift, state = cur.fetchone()
        assert drift is False
        assert state == "clean"


def test_tier_a_needs_input_preserved_despite_convertible():
    """Decision 2 non-regression: widening has_drift_remaining must NOT
    erase the 'cần xác nhận' surface. A tier-A artifact carrying the
    materialize-time `unconfirmed_default_1to1` reason still reports
    needs_input, even though the (now widened) drift check calls the pair
    convertible. Staleness and resolution-quality are decoupled."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_TA_NI", uom="EA")
        _insert_artifact(cur, "ba_ta_ni", "P_TA_NI", "technical_exploded",
                          source_kind="technical_flattened",
                          rows=[("M_TA_NI", 1.0, "SETS")])
        cur.execute(
            "update hub.bom_artifacts set is_stale=true, "
            "stale_reasons='[{\"dim\":\"unconfirmed_default_1to1\"}]'::jsonb "
            "where artifact_id='ba_ta_ni'")
        # The widened drift check sees SETS↔EA as convertible (tier-A)...
        cur.execute("select hub.has_drift_remaining(%s, %s, 'SETS')",
                     (CLIENT, "M_TA_NI"))
        assert cur.fetchone()[0] is False
        # ...yet the artifact still surfaces needs_input from its reason.
        assert _read_state(cur, "ba_ta_ni") == "needs_input"
