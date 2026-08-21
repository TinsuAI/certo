"""Store-layer flatten tests. Touches Postgres. Spec items:
- 8: BTP BOM stored as own first-class version.
- 22: BOM version records include structured identity (source_bom_kind,
  flatten_status, flatten_strategy, source_channel, lineage, display_label).
- 23: Generic latest-by-product does not select non_flattened or wrong dual
  variant.
- 24: Stored statuses/strategies/reasons/evidence use stable English machine
  codes, not Vietnamese UI labels.

Also exercises:
- UOM lookup precedence (client-specific > client-wide > global > alias).
- create_flattened_artifact_set materializing TPs + BTPs + unresolved nodes.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from hub.app.database import connect
from hub.app.flatten import flatten
from hub.app.flatten.types import (
    CatalogEntry, ConversionMatch, FlattenContext, ParsedBom,
)
from hub.app.stores import bom as bom_store
from hub.app.stores import flatten_decisions as decisions_store
from hub.app.stores.uom import make_uom_lookup


CLIENT = "flat_test_client"


@pytest.fixture(autouse=True)
def setup_client():
    """Create a throwaway client and tear it down after every test.

    Cascades remove materials, BOM versions, flatten decisions, unresolved
    nodes, client_uom_overrides, and bcct_rows for this client_id.
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.clients (client_id, name)
                values (%s, %s) on conflict (client_id) do nothing
                """,
                (CLIENT, "flatten test"),
            )
    yield
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.clients where client_id = %s", (CLIENT,))


# ── Item 8 + 22: BTP and TP both materialize with structured identity ──

def test_create_flattened_artifact_set_emits_tp_and_btp_with_structured_identity():
    parsed: ParsedBom = {
        "FT_TP-A":  [{"material_code": "FT_BTP-B", "qty_per_unit": 2, "uom": "kg"}],
        "FT_BTP-B": [{"material_code": "FT_NVL-1", "qty_per_unit": 0.5, "uom": "kg"}],
    }
    cat = lambda m: CatalogEntry(
        material_code=m, category="nvl", status="active", uom="kg"
    ) if m == "FT_NVL-1" else None
    ctx = FlattenContext(
        client_id=CLIENT,
        catalog=cat,
        bcct_import=lambda m: False,
        same_upload_btp=lambda m, b, v: None,
        current_db_btp=lambda m, b, v: None,
        uom=lambda m, f, t: None,
        explicit_context=lambda r: None,
    )
    result = flatten(parsed, ctx)
    materialized = bom_store.create_flattened_artifact_set(
        client_id=CLIENT, source_upload_id=None, result=result,
    )
    assert any(k.startswith("FT_TP-A|") for k in materialized)
    assert any(k.startswith("FT_BTP-B|") for k in materialized)

    # Read TP-A back; verify structured identity fields are populated.
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select source_bom_kind, flatten_status, flatten_strategy,
                       source_channel, bom_variant_id, display_label,
                       lineage, flatten_method, flatten_method_version
                from hub.bom_artifacts
                where client_id = %s and product_code = 'FT_TP-A'
                """,
                (CLIENT,),
            )
            sk, fs, fst, ch, bv, lbl, lin, fm, fmv = cur.fetchone()
    assert sk == "technical_flattened"
    assert fs == "flattened"
    assert fst == "technical_exploded"
    assert ch == "agency_upload"
    assert bv == "default"
    assert "FT_TP-A" in lbl
    assert fm == "dh_flatten_v1"
    assert fmv == "0.1.0"
    assert "btp_versions_used" in lin
    # The TP's lineage points to the BTP's artifact_id.
    used = lin["btp_versions_used"]
    assert used and used[0]["material_code"] == "FT_BTP-B"
    assert used[0]["artifact_id"]


# ── Item 23: latest_flattened_versions excludes non_flattened ──

def test_latest_excludes_non_flattened():
    """Manual write of two versions: a flattened one and a non_flattened one
    for the same product. latest_flattened_versions returns only the flattened.
    """
    bom_store.create_artifact(
        client_id=CLIENT, product_code="FT_TP-LATEST",
        rows=[{"material_code": "FT_X", "qty_per_unit": 1, "uom": "kg"}],
        actor="agency_staff", intent="asserted_technical",
        parent_artifact_id=None, context={}, source_upload_id=None,
        source_bom_kind="technical_flattened",
        flatten_status="flattened",
        flatten_strategy="technical_exploded",
    )
    bom_store.create_artifact(
        client_id=CLIENT, product_code="FT_TP-LATEST",
        rows=[{"material_code": "FT_Y", "qty_per_unit": 2, "uom": "kg"}],
        actor="agency_staff", intent="asserted_technical",
        parent_artifact_id=None, context={}, source_upload_id=None,
        source_bom_kind="technical_non_flattened",
        flatten_status="non_flattened",
        flatten_strategy="no_strategy",
    )
    items = bom_store.latest_flattened_versions(
        client_id=CLIENT, product_code="FT_TP-LATEST",
    )
    assert len(items) == 1
    assert items[0]["flatten_status"] == "flattened"


# ── Item 14 (store-side): dual-source variants both queryable as latest ──

def test_latest_returns_two_when_dual_source_published():
    bom_store.create_artifact(
        client_id=CLIENT, product_code="FT_TP-DUAL",
        rows=[{"material_code": "FT_BTP", "qty_per_unit": 1, "uom": "kg"}],
        actor="agency_staff", intent="asserted_technical",
        parent_artifact_id=None, context={}, source_upload_id=None,
        source_bom_kind="technical_flattened",
        flatten_status="flattened",
        flatten_strategy="purchased_btp_as_leaf",
    )
    bom_store.create_artifact(
        client_id=CLIENT, product_code="FT_TP-DUAL",
        rows=[{"material_code": "FT_NVL", "qty_per_unit": 0.5, "uom": "kg"}],
        actor="agency_staff", intent="asserted_technical",
        parent_artifact_id=None, context={}, source_upload_id=None,
        source_bom_kind="technical_flattened",
        flatten_status="flattened",
        flatten_strategy="self_produced_btp_exploded",
    )
    items = bom_store.latest_flattened_versions(
        client_id=CLIENT, product_code="FT_TP-DUAL",
    )
    strategies = sorted(i["flatten_strategy"] for i in items)
    assert strategies == ["purchased_btp_as_leaf", "self_produced_btp_exploded"]


# ── Mẫu 16 customs-filed BOM coexists with SAP technical as a variant ──

def test_latest_surfaces_customs_filed_alongside_technical():
    """When a product has BOTH manual_flat (Mẫu 16 customs-filed, variant
    'm16_<year>') AND technical_flattened (SAP rollup, variant 'default'),
    latest_flattened_versions returns BOTH — they live in distinct
    bom_variant_id partitions. CO repo handles the resulting 409
    dual_source by surfacing a dropdown with `human_label` to disambiguate.
    """
    # Two technical_flattened strategies under 'default' variant
    bom_store.create_artifact(
        client_id=CLIENT, product_code="FT_TP-M16VAR",
        rows=[{"material_code": "FT_NVL_A", "qty_per_unit": 1, "uom": "kg"}],
        actor="agency_staff", intent="asserted_technical",
        parent_artifact_id=None, context={}, source_upload_id=None,
        source_bom_kind="technical_flattened",
        flatten_status="flattened",
        flatten_strategy="technical_exploded",
        human_label="BOM kỹ thuật SAP",
    )
    bom_store.create_artifact(
        client_id=CLIENT, product_code="FT_TP-M16VAR",
        rows=[{"material_code": "FT_NVL_B", "qty_per_unit": 2, "uom": "kg"}],
        actor="agency_staff", intent="asserted_technical",
        parent_artifact_id=None, context={}, source_upload_id=None,
        source_bom_kind="technical_flattened",
        flatten_status="flattened",
        flatten_strategy="purchased_btp_as_leaf",
        human_label="BOM kỹ thuật SAP",
    )
    # Mẫu 16 customs-filed: distinct actor/intent/variant
    bom_store.create_artifact(
        client_id=CLIENT, product_code="FT_TP-M16VAR",
        rows=[{"material_code": "FT_NVL_C", "qty_per_unit": 0.5, "uom": "kg"}],
        actor="customs_filing", intent="customs_declared",
        parent_artifact_id=None, context={"regulatory": "m16_2025"},
        source_upload_id=None,
        source_bom_kind="manual_flat",
        flatten_status="flattened",
        flatten_strategy="manual_flat_as_provided",
        bom_variant_id="m16_2025",
        human_label="Mẫu 16/2025",
    )
    items = bom_store.latest_flattened_versions(
        client_id=CLIENT, product_code="FT_TP-M16VAR",
    )
    kinds_by_variant = {
        (i["bom_variant_id"], i["flatten_strategy"]): i["source_bom_kind"]
        for i in items
    }
    assert kinds_by_variant == {
        ("default", "technical_exploded"): "technical_flattened",
        ("default", "purchased_btp_as_leaf"): "technical_flattened",
        ("m16_2025", "manual_flat_as_provided"): "manual_flat",
    }
    # Each row carries human_label
    m16 = next(i for i in items if i["bom_variant_id"] == "m16_2025")
    assert m16["human_label"] == "Mẫu 16/2025"


def test_latest_technical_only_still_returns_dual_strategies():
    """Regression guard: when there is NO manual_flat artifact, the
    pre-existing dual-strategy behavior must still surface both
    technical_flattened variants (so /latest 409s and CO disambiguates)."""
    bom_store.create_artifact(
        client_id=CLIENT, product_code="FT_TP-TECHONLY",
        rows=[{"material_code": "FT_NVL_X", "qty_per_unit": 1, "uom": "kg"}],
        actor="agency_staff", intent="asserted_technical",
        parent_artifact_id=None, context={}, source_upload_id=None,
        source_bom_kind="technical_flattened",
        flatten_status="flattened",
        flatten_strategy="technical_exploded",
    )
    bom_store.create_artifact(
        client_id=CLIENT, product_code="FT_TP-TECHONLY",
        rows=[{"material_code": "FT_NVL_Y", "qty_per_unit": 2, "uom": "kg"}],
        actor="agency_staff", intent="asserted_technical",
        parent_artifact_id=None, context={}, source_upload_id=None,
        source_bom_kind="technical_flattened",
        flatten_status="flattened",
        flatten_strategy="purchased_btp_as_leaf",
    )
    items = bom_store.latest_flattened_versions(
        client_id=CLIENT, product_code="FT_TP-TECHONLY",
    )
    assert len(items) == 2
    assert {i["flatten_strategy"] for i in items} == {
        "technical_exploded", "purchased_btp_as_leaf",
    }


def test_create_artifact_stores_human_label():
    """human_label round-trips through create_artifact + get_artifact_with_rows."""
    artifact_id = bom_store.create_artifact(
        client_id=CLIENT, product_code="FT_TP-LABEL",
        rows=[{"material_code": "FT_X", "qty_per_unit": 1, "uom": "kg"}],
        actor="erp_pipeline", intent="asserted_technical",
        parent_artifact_id=None, context={}, source_upload_id=None,
        source_bom_kind="manual_flat",
        flatten_status="flattened",
        flatten_strategy="manual_flat_as_provided",
        human_label="Mẫu 16/2025",
    )
    data = bom_store.get_artifact_with_rows(artifact_id)
    assert data["artifact"]["human_label"] == "Mẫu 16/2025"


# ── Item 24: every stored value uses stable English machine codes ──

def test_stored_codes_are_english_only():
    """Audit: all enum values written by create_artifact + flatten path
    come from the spec's English code set. CHECK constraints enforce this
    at the DB layer, but we double-check the seed data + spec coverage."""
    valid_status = {"flattened", "non_flattened", "not_applicable"}
    valid_kind = {"manual_flat", "technical_raw", "technical_flattened",
                  "technical_non_flattened", "co_modified", "staff_edit"}
    valid_strategy = {"manual_flat_as_provided", "technical_exploded",
                      "purchased_btp_as_leaf", "self_produced_btp_exploded",
                      "mixed_confirmed", "no_strategy"}
    valid_channel = {"agency_upload", "staff_form", "co_proposal",
                     "migration", "seed"}

    bom_store.create_artifact(
        client_id=CLIENT, product_code="FT_CODES",
        rows=[{"material_code": "FT_X", "qty_per_unit": 1, "uom": "kg"}],
        actor="agency_staff", intent="asserted_technical",
        parent_artifact_id=None, context={}, source_upload_id=None,
        source_bom_kind="technical_flattened",
        flatten_status="flattened",
        flatten_strategy="technical_exploded",
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select source_bom_kind, flatten_status, flatten_strategy,
                       source_channel
                from hub.bom_artifacts where client_id = %s
                """,
                (CLIENT,),
            )
            for sk, fs, fst, ch in cur.fetchall():
                assert sk in valid_kind
                assert fs in valid_status
                assert fst in valid_strategy
                assert ch in valid_channel


# ── Variant-scoped artifact_no (spec §3A) ──

def test_artifact_no_is_scoped_to_variant():
    """Two versions with different bom_variant_id share artifact_no=1."""
    bom_store.create_artifact(
        client_id=CLIENT, product_code="FT_VAR",
        rows=[{"material_code": "FT_A", "qty_per_unit": 1, "uom": "kg"}],
        actor="agency_staff", intent="asserted_technical",
        parent_artifact_id=None, context={}, source_upload_id=None,
        source_bom_kind="technical_flattened",
        flatten_status="flattened",
        flatten_strategy="technical_exploded",
        bom_variant_id="V1",
    )
    bom_store.create_artifact(
        client_id=CLIENT, product_code="FT_VAR",
        rows=[{"material_code": "FT_B", "qty_per_unit": 1, "uom": "kg"}],
        actor="agency_staff", intent="asserted_technical",
        parent_artifact_id=None, context={}, source_upload_id=None,
        source_bom_kind="technical_flattened",
        flatten_status="flattened",
        flatten_strategy="technical_exploded",
        bom_variant_id="V2",
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select bom_variant_id, artifact_no from hub.bom_artifacts
                where client_id = %s and product_code = 'FT_VAR'
                order by bom_variant_id
                """,
                (CLIENT,),
            )
            rows = cur.fetchall()
    assert {r[0]: r[1] for r in rows} == {"V1": 1, "V2": 1}


# ── UOM lookup precedence ──

def test_uom_lookup_client_specific_beats_global():
    """Client-specific override (factor=42) wins over the global g→kg
    canonical factor (0.001)."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.client_uom_overrides
                  (client_id, material_code, from_uom, to_uom, factor)
                values (%s, 'FT_M', 'g', 'kg', 42)
                """,
                (CLIENT,),
            )
    lookup = make_uom_lookup(CLIENT)
    match = lookup("FT_M", "g", "kg")
    assert match is not None
    assert match.factor == Decimal(42)
    assert match.source == "client_specific"


def test_uom_lookup_falls_back_to_global_canonical():
    lookup = make_uom_lookup(CLIENT)
    match = lookup("FT_M2", "g", "kg")
    assert match is not None
    assert match.factor == Decimal("0.001")
    assert match.source == "global"


def test_uom_lookup_alias_returns_factor_one():
    lookup = make_uom_lookup(CLIENT)
    match = lookup("FT_M3", "KG", "kg")
    assert match is not None
    assert match.factor == Decimal(1)
    assert match.source == "alias"


def test_uom_lookup_returns_none_for_incompatible_families():
    """ml→kg has no general factor (mass vs volume); engine should treat
    as missing and emit uom_conversion_missing at flatten time."""
    lookup = make_uom_lookup(CLIENT)
    assert lookup("FT_M4", "ml", "kg") is None


def test_uom_lookup_client_wide_beats_global():
    """material_code is NULL ⇒ override applies to every material for the client."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.client_uom_overrides
                  (client_id, material_code, from_uom, to_uom, factor)
                values (%s, NULL, 'g', 'kg', 99)
                """,
                (CLIENT,),
            )
    lookup = make_uom_lookup(CLIENT)
    match = lookup("FT_ANY", "g", "kg")
    assert match is not None
    assert match.factor == Decimal(99)
    assert match.source == "client_wide"


# ── BCCT import lookup is import-only (spec §5) ──

def test_bcct_import_lookup_excludes_export_only_codes():
    """Insert a bcct row with direction=export — lookup must not return it."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, registration_date,
                   declaration_no, declaration_type, direction,
                   customs_code, goods_name)
                values (%s, 'FT_TX', '1', '2026-01-01',
                        'FT_DECL', 'A11', 'export',
                        'FT_EXPONLY', 'export only goods')
                """,
                (CLIENT,),
            )
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, registration_date,
                   declaration_no, declaration_type, direction,
                   customs_code, goods_name)
                values (%s, 'FT_TX2', '1', '2026-01-01',
                        'FT_DECL2', 'E11', 'import',
                        'FT_IMP', 'imported goods')
                """,
                (CLIENT,),
            )
    lookup = bom_store.make_bcct_import_lookup(CLIENT)
    assert lookup("FT_IMP") is True
    assert lookup("FT_EXPONLY") is False


# ── End-to-end: flatten → materialize → unresolved persisted ──

def test_non_flattened_version_persists_unresolved_nodes():
    """A TP whose component has no evidence becomes non_flattened. Its
    UnresolvedNode rows must land in hub.bom_unresolved_nodes."""
    parsed: ParsedBom = {
        "FT_TP_NF": [{"material_code": "FT_UNKN", "qty_per_unit": 1, "uom": "kg"}],
    }
    ctx = FlattenContext(
        client_id=CLIENT,
        catalog=lambda m: None,
        bcct_import=lambda m: False,
        same_upload_btp=lambda m, b, v: None,
        current_db_btp=lambda m, b, v: None,
        uom=lambda m, f, t: None,
        explicit_context=lambda r: None,
    )
    result = flatten(parsed, ctx)
    materialized = bom_store.create_flattened_artifact_set(
        client_id=CLIENT, source_upload_id=None, result=result,
    )
    [vid] = [v for k, v in materialized.items() if k.startswith("FT_TP_NF|")]
    unresolved = bom_store.get_unresolved_for_version(vid)
    assert len(unresolved) == 1
    assert unresolved[0]["reason"] == "missing_child_bom"
    # English machine code, not Vietnamese.
    assert unresolved[0]["material_code"] == "FT_UNKN"
