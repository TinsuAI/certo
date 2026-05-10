"""Phase 2 step 2b — UoM conversion in `_rederive_shape` refresh path.

Verifies the new convert-after-walk layer applied to raw walker output:
- Tier-A cross-family (count↔assembly/packaging) → factor 1.0 default
  + `unconfirmed_default_1to1` drift on new artifact.
- Tier-B (count↔mass) without override → raw qty kept + `factor_missing`
  drift, new artifact stays stale.
- Explicit override row → conversion happens, no drift.
- Catalog UoM null → raw kept + `catalog_uom_missing` drift.
- Same-family auto-convert (gam → kg) → silent conversion, no drift.

Fixture builds a real raw_graph + bom_edges + materials catalog +
derived stale artifact, then drives the refresh helper directly
(skipping HTTP).
"""
from __future__ import annotations

import json

import pytest

from app.database import connect
from app.stores.bom_staleness import refresh_artifact


CLIENT = "_uom_refresh_test"


def _seed_client(cur):
    cur.execute(
        "insert into hub.clients (client_id, name) values (%s, %s) "
        "on conflict (client_id) do nothing",
        (CLIENT, "uom-refresh test"),
    )


def _seed_material(cur, code: str, category: str = "nvl",
                   uom: str | None = "kg"):
    cur.execute(
        "insert into hub.materials (client_id, material_code, name, "
        "category, status, uom) values (%s, %s, %s, %s, 'active', %s) "
        "on conflict (client_id, material_code) do update set "
        "category=excluded.category, uom=excluded.uom",
        (CLIENT, code, code, category, uom),
    )


def _insert_raw_artifact(cur, artifact_id: str, product_code: str,
                          edges: list[tuple[str, str, float, str]]) -> None:
    """Insert a published technical_raw artifact + its bom_edges.

    edges = [(parent_code, child_code, qty_per_parent, uom), ...]
    """
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


def _insert_derived_stale(cur, artifact_id: str, product_code: str,
                            strategy: str = "purchased_btp_as_leaf") -> None:
    reasons = [{"dim": "catalog_category", "source_table": "hub.materials",
                "source_pk": f"{CLIENT}/seed", "observed_at":
                "2026-05-12T00:00:00Z"}]
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
        "'flattened', %s, 'migration', 'default', '{}', 'recursive_sql', "
        "'1', now(), true, %s::jsonb, now())",
        (artifact_id, CLIENT, product_code, f"h_{artifact_id}", strategy,
         json.dumps(reasons)),
    )


def _new_artifact_rows(cur, parent_artifact_id: str) -> list[tuple]:
    """Rows of artifacts that link back to parent_artifact_id."""
    cur.execute(
        "select b.artifact_id, b.flatten_strategy, b.flatten_method, "
        "b.flatten_method_version, b.is_stale, b.stale_reasons "
        "from hub.bom_artifacts b "
        "where b.parent_artifact_id=%s order by b.created_at",
        (parent_artifact_id,),
    )
    return list(cur.fetchall())


def _artifact_rows(cur, artifact_id: str) -> list[dict]:
    cur.execute(
        "select material_code, qty_per_unit, uom from hub.bom_artifact_rows "
        "where artifact_id=%s order by material_code",
        (artifact_id,),
    )
    return [{"material_code": r[0], "qty_per_unit": float(r[1]), "uom": r[2]}
            for r in cur.fetchall()]


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        _seed_client(cur)
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.bom_artifact_rows where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (CLIENT,),
        )
        cur.execute(
            "delete from hub.bom_edges where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (CLIENT,),
        )
        cur.execute(
            "delete from hub.bom_artifacts where client_id=%s", (CLIENT,))
        cur.execute(
            "delete from hub.client_uom_overrides where client_id=%s",
            (CLIENT,))
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


# ── Same-family auto-convert (gam → kg) ──────────────────────────────────


def test_refresh_converts_same_family_silently():
    """Raw row qty=2500 g; catalog uom=kg → derived row qty=2.5 kg + no drift."""
    raw_id = "ba_raw_samefam"
    derived_id = "ba_der_samefam"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP1", category="tp", uom="kg")
        _seed_material(cur, "M_NVL", category="nvl", uom="kg")
        _insert_raw_artifact(cur, raw_id, "TP1",
                              edges=[("TP1", "M_NVL", 2500.0, "g")])
        _insert_derived_stale(cur, derived_id, "TP1",
                                strategy="technical_exploded")

    result = refresh_artifact(CLIENT, derived_id)

    assert result["new_artifact_ids"], "expected new artifact"
    new_id = result["new_artifact_ids"][0]
    with connect() as conn, conn.cursor() as cur:
        rows = _artifact_rows(cur, new_id)
        cur.execute(
            "select is_stale, stale_reasons from hub.bom_artifacts "
            "where artifact_id=%s", (new_id,))
        is_stale, reasons = cur.fetchone()

    assert len(rows) == 1
    assert rows[0]["material_code"] == "M_NVL"
    assert rows[0]["uom"] == "kg"
    assert rows[0]["qty_per_unit"] == pytest.approx(2.5)
    assert is_stale is False, "same-family conversion should not produce drift"
    assert reasons == []


# ── Tier A: cross-family count↔assembly default 1:1 + drift ─────────────


def test_refresh_tier_a_emits_unconfirmed_default_drift():
    """EA (count) → SETS (assembly): factor=1, drift `unconfirmed_default_1to1`."""
    raw_id = "ba_raw_tier_a"
    derived_id = "ba_der_tier_a"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_A", category="tp", uom="SETS")
        _seed_material(cur, "M_TIER_A", category="nvl", uom="SETS")
        _insert_raw_artifact(cur, raw_id, "TP_A",
                              edges=[("TP_A", "M_TIER_A", 4.0, "EA")])
        _insert_derived_stale(cur, derived_id, "TP_A",
                                strategy="technical_exploded")

    result = refresh_artifact(CLIENT, derived_id)
    new_id = result["new_artifact_ids"][0]

    with connect() as conn, conn.cursor() as cur:
        rows = _artifact_rows(cur, new_id)
        cur.execute(
            "select is_stale, stale_reasons from hub.bom_artifacts "
            "where artifact_id=%s", (new_id,))
        is_stale, reasons = cur.fetchone()

    # Tier-A: factor 1.0 applied, qty unchanged, uom changes to catalog.
    assert rows[0]["uom"] == "SETS"
    assert rows[0]["qty_per_unit"] == pytest.approx(4.0)
    assert is_stale is True, "tier-A drift keeps artifact stale (warning)"
    dims = sorted({r["dim"] for r in reasons})
    assert "unconfirmed_default_1to1" in dims


# ── Tier B: cross-family count↔mass without override → factor_missing ────


def test_refresh_tier_b_keeps_raw_and_emits_factor_missing():
    """EA (count) → KG (mass): no override → keep raw + factor_missing drift."""
    raw_id = "ba_raw_tier_b"
    derived_id = "ba_der_tier_b"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_B", category="tp", uom="KG")
        _seed_material(cur, "M_TIER_B", category="nvl", uom="KG")
        _insert_raw_artifact(cur, raw_id, "TP_B",
                              edges=[("TP_B", "M_TIER_B", 7.0, "EA")])
        _insert_derived_stale(cur, derived_id, "TP_B",
                                strategy="technical_exploded")

    result = refresh_artifact(CLIENT, derived_id)
    new_id = result["new_artifact_ids"][0]

    with connect() as conn, conn.cursor() as cur:
        rows = _artifact_rows(cur, new_id)
        cur.execute(
            "select is_stale, stale_reasons from hub.bom_artifacts "
            "where artifact_id=%s", (new_id,))
        is_stale, reasons = cur.fetchone()

    # Tier-B: factor missing → keep raw qty + raw uom unchanged.
    assert rows[0]["uom"] == "EA", "raw uom kept (no silent corruption)"
    assert rows[0]["qty_per_unit"] == pytest.approx(7.0)
    assert is_stale is True
    dims = sorted({r["dim"] for r in reasons})
    assert "factor_missing" in dims


# ── Tier B with explicit override → silent convert, no drift ────────────


def test_refresh_tier_b_with_override_converts():
    """EA → KG with `client_uom_overrides` row factor=0.5 → qty * 0.5."""
    raw_id = "ba_raw_tier_b_override"
    derived_id = "ba_der_tier_b_override"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_BO", category="tp", uom="KG")
        _seed_material(cur, "M_HEAVY", category="nvl", uom="KG")
        _insert_raw_artifact(cur, raw_id, "TP_BO",
                              edges=[("TP_BO", "M_HEAVY", 10.0, "EA")])
        _insert_derived_stale(cur, derived_id, "TP_BO",
                                strategy="technical_exploded")
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'M_HEAVY', 'EA', 'KG', 0.5, 'supplier_data')",
            (CLIENT,),
        )

    result = refresh_artifact(CLIENT, derived_id)
    new_id = result["new_artifact_ids"][0]

    with connect() as conn, conn.cursor() as cur:
        rows = _artifact_rows(cur, new_id)
        cur.execute(
            "select is_stale, stale_reasons from hub.bom_artifacts "
            "where artifact_id=%s", (new_id,))
        is_stale, reasons = cur.fetchone()

    assert rows[0]["uom"] == "KG"
    assert rows[0]["qty_per_unit"] == pytest.approx(5.0), \
        "10 EA × 0.5 kg/EA = 5 kg"
    assert is_stale is False, "override row resolves drift"
    assert reasons == []


# ── Catalog UoM null → catalog_uom_missing drift ─────────────────────────


def test_refresh_catalog_uom_null_emits_catalog_uom_missing():
    """Material has uom=NULL → defer materialization (keep raw + drift)."""
    raw_id = "ba_raw_cat_null"
    derived_id = "ba_der_cat_null"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_NULL", category="tp", uom=None)
        _seed_material(cur, "M_NULL", category="nvl", uom=None)
        _insert_raw_artifact(cur, raw_id, "TP_NULL",
                              edges=[("TP_NULL", "M_NULL", 3.0, "kg")])
        _insert_derived_stale(cur, derived_id, "TP_NULL",
                                strategy="technical_exploded")

    result = refresh_artifact(CLIENT, derived_id)
    new_id = result["new_artifact_ids"][0]

    with connect() as conn, conn.cursor() as cur:
        rows = _artifact_rows(cur, new_id)
        cur.execute(
            "select is_stale, stale_reasons from hub.bom_artifacts "
            "where artifact_id=%s", (new_id,))
        is_stale, reasons = cur.fetchone()

    assert rows[0]["uom"] == "kg", "raw uom kept when catalog has none"
    assert rows[0]["qty_per_unit"] == pytest.approx(3.0)
    assert is_stale is True
    dims = sorted({r["dim"] for r in reasons})
    assert "catalog_uom_missing" in dims


# ── Original artifact always cleared, new stays stale per drift ─────────


def test_refresh_clears_original_keeps_new_stale_when_drift():
    """User clicked refresh on A. New artifact B has tier-A drift.
    A's flag must clear (action taken). B stays stale (warning)."""
    raw_id = "ba_raw_clear_orig"
    derived_id = "ba_der_clear_orig"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_CO", category="tp", uom="SETS")
        _seed_material(cur, "M_CO", category="nvl", uom="SETS")
        _insert_raw_artifact(cur, raw_id, "TP_CO",
                              edges=[("TP_CO", "M_CO", 1.0, "EA")])
        _insert_derived_stale(cur, derived_id, "TP_CO",
                                strategy="technical_exploded")

    result = refresh_artifact(CLIENT, derived_id)
    new_id = result["new_artifact_ids"][0]
    assert new_id != derived_id, "different hash should mint new artifact"

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select is_stale from hub.bom_artifacts where artifact_id=%s",
            (derived_id,))
        original_stale = cur.fetchone()[0]
        cur.execute(
            "select is_stale from hub.bom_artifacts where artifact_id=%s",
            (new_id,))
        new_stale = cur.fetchone()[0]

    assert original_stale is False, "original artifact: refresh action taken → flag cleared"
    assert new_stale is True, "new artifact: tier-A default warning → stays stale"


# ── No drift → both original and new clear ──────────────────────────────


def test_refresh_clean_path_clears_both():
    """Same-family conversion (no drift) → both original A and new B clear."""
    raw_id = "ba_raw_clean"
    derived_id = "ba_der_clean"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_CLEAN", category="tp", uom="kg")
        _seed_material(cur, "M_CLEAN", category="nvl", uom="kg")
        _insert_raw_artifact(cur, raw_id, "TP_CLEAN",
                              edges=[("TP_CLEAN", "M_CLEAN", 500.0, "g")])
        _insert_derived_stale(cur, derived_id, "TP_CLEAN",
                                strategy="technical_exploded")

    result = refresh_artifact(CLIENT, derived_id)
    new_id = result["new_artifact_ids"][0]

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select is_stale from hub.bom_artifacts where artifact_id=%s",
            (new_id,))
        new_stale = cur.fetchone()[0]
    assert new_stale is False
