"""Ingest-time integration: BCCT insert populates `material_identity` jsonb.

The resolver runs as part of `_insert_bcct_with_cursor`. New rows ship
with their identity already resolved; lazy-fill at read time is a
fallback for rows ingested before this feature shipped.
"""
from __future__ import annotations

import json

import pytest

from app.database import connect

from app.routes.bcct import _insert_bcct_with_cursor


CLIENT = "ingest_pid_test"


@pytest.fixture(autouse=True)
def setup_growatt_like_client():
    from app.parsers.client_parser_rules import clear_rules_cache
    clear_rules_cache()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name, code_resolution_mode) "
            "values (%s, %s, %s) on conflict (client_id) do nothing",
            (CLIENT, "ingest pid test", "batch_aggregate_resolution"),
        )
        # Stage 2 candidate-extraction rule (was hardcoded in
        # bcct_adapters/growatt.py; now config-driven).
        cur.execute(
            "insert into hub.client_parser_rules "
            "(client_id, output_field, priority, pattern, source_field, "
            " match_action, no_match_action, notes, created_by) "
            "values (%s, 'material_identity_candidates', 10, "
            r" '\(([A-Z]{2,}\d{2}\.[A-Za-z0-9._\-]+)\)', "
            "'goods_name', 'capture', 'next_rule', "
            "'parenthesized_product_code_exists_in_bom_products', 'test')",
            (CLIENT,),
        )
        # Materials catalog: TP with BOM (PV01.0117500).
        cur.execute(
            "insert into hub.materials (client_id, customs_code, "
            "internal_code, name, category) values (%s, %s, %s, %s, %s) "
            "on conflict do nothing",
            (CLIENT, "PV01.0117500", "PV01.0117500", "Test TP", "tp"),
        )
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            "product_code, artifact_no, actor, intent, normalized_hash, "
            "source_bom_kind, flatten_status, flatten_strategy, "
            "source_channel, flatten_method, flatten_method_version, "
            "status, published_at) "
            "values ('ba_ingest_test_pid', %s, 'PV01.0117500', 1, "
            "'agency_staff', 'asserted_technical', 'h_ingest_pid', "
            "'technical_flattened', 'flattened', 'technical_exploded', "
            "'agency_upload', 'manual', '0.1', 'published', now()) "
            "on conflict (artifact_id) do nothing",
            (CLIENT,),
        )
    yield
    clear_rules_cache()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bcct_rows where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.client_parser_rules where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def _row(*, txkey="DECLA1-1", customs="BIENTAN.17",
         goods="BIENTAN.17#&Thiết bị (PV01.0117500)#&VN"):
    return {
        "transaction_key": txkey,
        "line_no": "1",
        "declaration_no": "DECLA1",
        "declaration_type": "E42",
        "direction": "export",
        "registration_date": "2026-01-15",
        "customs_code": customs,
        "goods_name": goods,
        "payload": {},
    }


def test_insert_populates_material_identity_resolved():
    """A Growatt-shaped row with embedded BOM code + matching artifact
    populates material_identity at insert time."""
    client_dict = {"client_id": CLIENT, "code_resolution_mode": "batch_aggregate_resolution"}
    with connect() as conn, conn.cursor() as cur:
        n = _insert_bcct_with_cursor(
            cur, client_id=CLIENT, rows=[_row()], upload_id=None, client=client_dict,
        )
        assert n == 1
        cur.execute(
            "select material_identity from hub.bcct_rows "
            "where client_id=%s and transaction_key=%s",
            (CLIENT, "DECLA1-1"),
        )
        (pid,) = cur.fetchone()

    assert pid is not None
    assert pid["resolution_status"] == "resolved"
    assert pid["resolved_code"] == "PV01.0117500"
    assert pid["bom_product_code"] == "PV01.0117500"  # TP with BOM
    assert pid["product_kind"] == "tp"
    assert pid["resolution_source"] == "goods_name_embedded_code"
    assert pid["parser_adapter"] == "client_parser_rules"


def test_insert_populates_material_identity_missing_when_no_bom():
    """Row whose customs_code + goods_name yield no BOM match still
    persists material_identity with status=missing (not NULL)."""
    client_dict = {"client_id": CLIENT, "code_resolution_mode": "batch_aggregate_resolution"}
    row = _row(
        txkey="DECLNOM-1",
        customs="UNKNOWN.99",
        goods="UNKNOWN.99#&Plain text no codes#&VN",
    )
    with connect() as conn, conn.cursor() as cur:
        _insert_bcct_with_cursor(
            cur, client_id=CLIENT, rows=[row], upload_id=None, client=client_dict,
        )
        cur.execute(
            "select material_identity from hub.bcct_rows "
            "where client_id=%s and transaction_key=%s",
            (CLIENT, "DECLNOM-1"),
        )
        (pid,) = cur.fetchone()

    assert pid is not None
    assert pid["resolution_status"] == "missing"
    assert pid["bom_product_code"] is None


def test_insert_resolves_via_structured_field_when_customs_is_bom_code():
    """Row whose customs_code IS a BOM product code (Stage 1) resolves
    even without a goods_name paren."""
    client_dict = {"client_id": CLIENT, "code_resolution_mode": "batch_aggregate_resolution"}
    row = _row(
        txkey="DECLST1-1",
        customs="PV01.0117500",
        goods="PV01.0117500#&Plain description#&VN",
    )
    with connect() as conn, conn.cursor() as cur:
        _insert_bcct_with_cursor(
            cur, client_id=CLIENT, rows=[row], upload_id=None, client=client_dict,
        )
        cur.execute(
            "select material_identity from hub.bcct_rows "
            "where client_id=%s and transaction_key=%s",
            (CLIENT, "DECLST1-1"),
        )
        (pid,) = cur.fetchone()

    assert pid["resolution_status"] == "resolved"
    assert pid["resolved_code"] == "PV01.0117500"
    assert pid["bom_product_code"] == "PV01.0117500"
    assert pid["resolution_source"] == "structured_field"


def test_insert_resolves_nvl_import_via_materials_catalog():
    """Imports of raw materials (NVL) resolve against materials catalog
    even though there's no BOM for them — BCQT settlement uses this."""
    client_dict = {"client_id": CLIENT, "code_resolution_mode": "batch_aggregate_resolution"}
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, customs_code, "
            "internal_code, name, category) values (%s, %s, %s, %s, %s) "
            "on conflict do nothing",
            (CLIENT, "NVL.PE001", "NVL.PE001", "Polyethylene resin", "nvl"),
        )
    row = _row(
        txkey="DECLNVL-1",
        customs="NVL.PE001",
        goods="NVL.PE001#&Polyethylene resin#&CN",
    )
    with connect() as conn, conn.cursor() as cur:
        _insert_bcct_with_cursor(
            cur, client_id=CLIENT, rows=[row], upload_id=None, client=client_dict,
        )
        cur.execute(
            "select material_identity from hub.bcct_rows "
            "where client_id=%s and transaction_key=%s",
            (CLIENT, "DECLNVL-1"),
        )
        (pid,) = cur.fetchone()

    assert pid["resolution_status"] == "resolved"
    assert pid["resolved_code"] == "NVL.PE001"
    assert pid["bom_product_code"] is None  # NVL has no BOM, alias gated
    assert pid["product_kind"] == "nvl"


def test_insert_batch_uses_one_resolver_context():
    """Multiple rows in a single insert call share one ResolverContext
    (Q5 — per-request memoization). Asserted indirectly: two rows
    inserted, both resolved."""
    client_dict = {"client_id": CLIENT, "code_resolution_mode": "batch_aggregate_resolution"}
    rows = [
        _row(txkey="DECLAA-1", goods="BIENTAN.17#&(PV01.0117500)#&VN"),
        _row(txkey="DECLBB-1", goods="BIENTAN.17#&Hàng (PV01.0117500)#&VN"),
    ]
    with connect() as conn, conn.cursor() as cur:
        _insert_bcct_with_cursor(
            cur, client_id=CLIENT, rows=rows, upload_id=None, client=client_dict,
        )
        cur.execute(
            "select transaction_key, material_identity->>'resolution_status' "
            "from hub.bcct_rows where client_id=%s order by transaction_key",
            (CLIENT,),
        )
        results = list(cur.fetchall())
    assert len(results) == 2
    assert all(status == "resolved" for _, status in results)
