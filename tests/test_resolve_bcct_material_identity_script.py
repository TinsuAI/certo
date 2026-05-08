"""Tests for scripts/resolve_bcct_material_identity.py backfill."""
from __future__ import annotations

import secrets

import pytest

from app.database import connect
from scripts.resolve_bcct_material_identity import resolve_for_client


@pytest.fixture
def client_with_null_pids():
    cid = "backfill-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name, code_resolution_mode) "
            "values (%s, 'Backfill Test', 'batch_aggregate_resolution')",
            (cid,),
        )
        cur.execute(
            "insert into hub.materials (client_id, customs_code, "
            "internal_code, name, category) values "
            "(%s, 'PV01.0117500', 'PV01.0117500', 'Test TP', 'tp') "
            "on conflict do nothing",
            (cid,),
        )
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            "product_code, artifact_no, actor, intent, normalized_hash, "
            "source_bom_kind, flatten_status, flatten_strategy, "
            "source_channel, flatten_method, flatten_method_version, "
            "status, published_at) "
            "values (%s, %s, 'PV01.0117500', 1, 'agency_staff', "
            "'asserted_technical', 'h_bf', 'technical_flattened', "
            "'flattened', 'technical_exploded', 'agency_upload', "
            "'manual', '0.1', 'published', now())",
            (f"ba_{cid}", cid),
        )
        for txkey, customs, gname in [
            ("BFA-1", "BIENTAN.17", "BIENTAN.17#&Hàng (PV01.0117500)#&VN"),
            ("BFB-1", "UNKNOWN.99", "UNKNOWN.99#&Plain text#&VN"),
        ]:
            cur.execute(
                "insert into hub.bcct_rows "
                "(client_id, transaction_key, line_no, declaration_no, "
                " declaration_type, direction, registration_date, "
                " customs_code, goods_name, payload) "
                "values (%s, %s, '1', %s, 'E42', 'export', '2026-01-15', "
                "%s, %s, '{}'::jsonb)",
                (cid, txkey, txkey.split("-")[0], customs, gname),
            )
            # Force material_identity NULL (insert path normally fills it; this
            # simulates legacy rows that pre-date the resolver).
            cur.execute(
                "update hub.bcct_rows set material_identity = null "
                "where client_id=%s and transaction_key=%s",
                (cid, txkey),
            )
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bcct_rows where client_id = %s", (cid,))
        cur.execute("delete from hub.bcct_row_history where client_id = %s", (cid,))
        cur.execute("delete from hub.bom_artifacts where client_id = %s", (cid,))
        cur.execute("delete from hub.materials where client_id = %s", (cid,))
        cur.execute("delete from hub.clients where client_id = %s", (cid,))


def test_backfill_populates_null_rows(client_with_null_pids):
    cid = client_with_null_pids
    stats = resolve_for_client(cid, recompute=False, dry_run=False)
    assert stats["rows_examined"] == 2
    assert stats["rows_updated"] == 2
    # One resolved, one missing.
    assert stats["by_status"].get("resolved") == 1
    assert stats["by_status"].get("missing") == 1

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select transaction_key, material_identity->>'resolution_status' "
            "from hub.bcct_rows where client_id=%s order by transaction_key",
            (cid,),
        )
        results = dict(cur.fetchall())
    assert results["BFA-1"] == "resolved"
    assert results["BFB-1"] == "missing"


def test_dry_run_does_not_write(client_with_null_pids):
    cid = client_with_null_pids
    stats = resolve_for_client(cid, recompute=False, dry_run=True)
    assert stats["rows_examined"] == 2
    assert stats["rows_updated"] == 0
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.bcct_rows "
            "where client_id=%s and material_identity is null",
            (cid,),
        )
        (n_null,) = cur.fetchone()
    assert n_null == 2  # untouched


def test_default_skips_already_resolved(client_with_null_pids):
    cid = client_with_null_pids
    # First pass — fills both rows.
    resolve_for_client(cid, recompute=False, dry_run=False)
    # Second pass without --recompute should examine 0 rows.
    stats = resolve_for_client(cid, recompute=False, dry_run=False)
    assert stats["rows_examined"] == 0


def test_recompute_revisits_all_rows(client_with_null_pids):
    cid = client_with_null_pids
    resolve_for_client(cid, recompute=False, dry_run=False)
    # --recompute revisits everything.
    stats = resolve_for_client(cid, recompute=True, dry_run=False)
    assert stats["rows_examined"] == 2
    assert stats["rows_updated"] == 2
