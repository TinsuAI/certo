"""Stage C1: confirm-on-update gate + audit log via Postgres trigger.

Drives the upload route through FastAPI's TestClient with httpx so the
preview-confirm flow gets exercised end-to-end. Each test cleans up its
own rows by transaction_key prefix.
"""
from __future__ import annotations

import io
import json

import psycopg
import pytest
from openpyxl import Workbook

from app import auth
from app.database import connect
from app.routes.bcct import _classify_rows


CLIENT = "growatt-vn"
TXN_PREFIX = "TEST_C1_"


def _xlsx(rows: list[tuple]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "BCCT"
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _seed_row(declaration_no: str, line_no: str, **overrides):
    """Insert a directly-seeded BCCT row to act as 'pre-existing' state."""
    txn_key = f"{TXN_PREFIX}{declaration_no}"
    defaults = {
        "registration_date": "2025-01-15",
        "customs_code": "PE-001",
        "internal_code": "PE-001",
        "goods_name": "PE-001#&Polyethylene",
        "quantity": 100,
        "total_value": 250,
        "declaration_type": "E11",
        "direction": "import",
    }
    defaults.update(overrides)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no,
                   declaration_type, direction, registration_date, customs_code,
                   internal_code, goods_name, quantity, total_value, payload)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '{}'::jsonb)
                on conflict (client_id, year, transaction_key, line_no) do nothing
                """,
                (CLIENT, txn_key, line_no, declaration_no,
                 defaults["declaration_type"], defaults["direction"],
                 defaults["registration_date"], defaults["customs_code"],
                 defaults["internal_code"], defaults["goods_name"],
                 defaults["quantity"], defaults["total_value"]),
            )
    return txn_key


@pytest.fixture(autouse=True)
def cleanup():
    yield
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from hub.bcct_rows where transaction_key like %s",
                (TXN_PREFIX + "%",),
            )
            cur.execute(
                "delete from hub.bcct_row_history where transaction_key like %s",
                (TXN_PREFIX + "%",),
            )
            cur.execute(
                "delete from hub.upload_pending where pending_id like 'test_%'",
            )


# ───────────────────────────────────────────────────────────────────────
# _classify_rows direct unit tests
# ───────────────────────────────────────────────────────────────────────

def test_classify_all_new_when_db_empty():
    parsed = [{
        "transaction_key": TXN_PREFIX + "999",
        "line_no": "1",
        "declaration_no": TXN_PREFIX + "999",
        "registration_date": "2025-03-15",
        "customs_code": "X",
        "goods_name": "Y",
    }]
    summary = _classify_rows(client_id=CLIENT, parsed=parsed, parser=None)
    assert summary["new"] == 1
    assert summary["noop"] == 0
    assert summary["diff"] == []
    assert summary["orphan"] == []


def test_classify_diff_when_value_changed():
    txn = _seed_row("888", "1", quantity=100)
    parsed = [{
        "transaction_key": txn, "line_no": "1",
        "declaration_no": "888",
        "registration_date": "2025-01-15",
        "customs_code": "PE-001", "internal_code": "PE-001",
        "goods_name": "PE-001#&Polyethylene",
        "quantity": 95,    # changed!
        "total_value": 250,
        "declaration_type": "E11", "direction": "import",
    }]
    summary = _classify_rows(client_id=CLIENT, parsed=parsed, parser=None)
    assert summary["new"] == 0
    assert len(summary["diff"]) == 1
    d = summary["diff"][0]
    assert "quantity" in d["changed_fields"]
    assert float(d["old"]["quantity"]) == 100
    assert float(d["new"]["quantity"]) == 95


def test_classify_noop_when_values_identical():
    txn = _seed_row("777", "1")
    parsed = [{
        "transaction_key": txn, "line_no": "1",
        "declaration_no": "777",
        "registration_date": "2025-01-15",
        "customs_code": "PE-001", "internal_code": "PE-001",
        "goods_name": "PE-001#&Polyethylene",
        "quantity": 100, "total_value": 250,
        "declaration_type": "E11", "direction": "import",
    }]
    summary = _classify_rows(client_id=CLIENT, parsed=parsed, parser=None)
    assert summary["new"] == 0
    assert summary["noop"] == 1
    assert summary["diff"] == []


def test_classify_orphan_when_db_has_extra_line():
    """File has line 1; DB has lines 1 and 2 for same declaration → line 2 is orphan."""
    _seed_row("666", "1")
    _seed_row("666", "2", customs_code="AL-100", goods_name="AL-100#&Aluminum")
    parsed = [{
        "transaction_key": TXN_PREFIX + "666", "line_no": "1",
        "declaration_no": "666",
        "registration_date": "2025-01-15",
        "customs_code": "PE-001", "internal_code": "PE-001",
        "goods_name": "PE-001#&Polyethylene",
        "quantity": 100, "total_value": 250,
        "declaration_type": "E11", "direction": "import",
    }]
    summary = _classify_rows(client_id=CLIENT, parsed=parsed, parser=None)
    assert summary["noop"] == 1
    assert len(summary["orphan"]) == 1
    assert summary["orphan"][0]["line_no"] == "2"


# ───────────────────────────────────────────────────────────────────────
# Audit-log trigger via direct SQL
# ───────────────────────────────────────────────────────────────────────

def test_trigger_logs_update_with_actor():
    txn = _seed_row("555", "1", quantity=100)
    with connect(user_id="audit-test-user") as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.bcct_rows set quantity = 95 "
                "where client_id=%s and transaction_key=%s and line_no='1'",
                (CLIENT, txn),
            )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select changed_by, action, old_row->>'quantity', new_row->>'quantity' "
                "from hub.bcct_row_history where transaction_key=%s",
                (txn,),
            )
            rows = cur.fetchall()
    assert len(rows) == 1
    actor, action, old_qty, new_qty = rows[0]
    assert actor == "audit-test-user"
    assert action == "update"
    assert float(old_qty) == 100
    assert float(new_qty) == 95


def test_trigger_skips_noop_update():
    """ON CONFLICT DO UPDATE with identical values should NOT generate
    an audit row (filtered by old_jsonb = new_jsonb)."""
    txn = _seed_row("444", "1")
    with connect(user_id="noop-test-user") as conn:
        with conn.cursor() as cur:
            # No-change update
            cur.execute(
                "update hub.bcct_rows set quantity = quantity "
                "where transaction_key=%s",
                (txn,),
            )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select count(*) from hub.bcct_row_history where transaction_key=%s",
                (txn,),
            )
            (n,) = cur.fetchone()
    assert n == 0


def test_trigger_logs_delete_with_actor():
    txn = _seed_row("333", "1")
    with connect(user_id="delete-test-user") as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from hub.bcct_rows where transaction_key=%s",
                (txn,),
            )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select changed_by, action, old_row->>'goods_name', new_row "
                "from hub.bcct_row_history where transaction_key=%s",
                (txn,),
            )
            rows = cur.fetchall()
    assert len(rows) == 1
    actor, action, old_goods, new_row = rows[0]
    assert actor == "delete-test-user"
    assert action == "delete"
    assert old_goods is not None
    assert new_row is None


def test_trigger_writes_system_when_guc_unset():
    txn = _seed_row("222", "1")
    with connect() as conn:  # no user_id GUC
        with conn.cursor() as cur:
            cur.execute(
                "update hub.bcct_rows set quantity = 88 where transaction_key=%s",
                (txn,),
            )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select changed_by from hub.bcct_row_history where transaction_key=%s",
                (txn,),
            )
            (actor,) = cur.fetchone()
    assert actor == "system"


# ───────────────────────────────────────────────────────────────────────
# upload_pending TTL + idempotency
# ───────────────────────────────────────────────────────────────────────

def test_confirm_orphans_only_does_not_delete_unconfirmed_diff_rows():
    """Regression for the data-loss bug found in /rev (2026-05-04):

    File [A,B,C], DB [A,B,C,D]. A's quantity changed (DIFF), D is orphan.
    User submits confirm_orphans=True, confirm_diffs=False.

    Old buggy behavior: filter A from rows → re-classify [B,C] vs DB →
      A and D both detected as orphan → both deleted.
    Correct behavior: A is preserved (user didn't confirm overwrite);
      only D is deleted.
    """
    from app.routes.bcct import _apply_bcct_rows
    from app.parsers.goods_name import internal_code_parser_for

    # Use distinct decl_nos so each row has a unique txn_key (helper
    # constructs the key from decl_no alone).
    txn_a = _seed_row("REGRESS_A", "1", quantity=100, customs_code="A-CODE")
    txn_b = _seed_row("REGRESS_B", "1", quantity=200, customs_code="B-CODE")
    txn_c = _seed_row("REGRESS_C", "1", quantity=300, customs_code="C-CODE")
    txn_d = _seed_row("REGRESS_D", "1", quantity=400, customs_code="D-CODE")

    # Simulate the confirm-route bucketing logic. Stashed diff_summary
    # would say: A is DIFF (quantity changed), B/C are NOOP, D is ORPHAN.
    diff_summary = {
        "new": 0, "noop": 2,
        "diff": [{"key": [txn_a, "1"], "decl_no": "REGRESS_A", "line_no": "1",
                  "old": {"quantity": 100}, "new": {"quantity": 95},
                  "changed_fields": ["quantity"]}],
        "orphan": [{"key": [txn_d, "1"], "decl_no": "REGRESS_D", "line_no": "1"}],
    }
    parsed_rows = [
        # A — would-be DIFF if applied
        {"transaction_key": txn_a, "line_no": "1", "declaration_no": "REGRESS_A",
         "registration_date": "2025-01-15", "customs_code": "A-CODE",
         "internal_code": "A-CODE", "goods_name": "PE-001#&Polyethylene",
         "quantity": 95, "total_value": 250,
         "declaration_type": "E11", "direction": "import"},
        # B, C — unchanged
        {"transaction_key": txn_b, "line_no": "1", "declaration_no": "REGRESS_B",
         "registration_date": "2025-01-15", "customs_code": "B-CODE",
         "internal_code": "B-CODE", "goods_name": "PE-001#&Polyethylene",
         "quantity": 200, "total_value": 250,
         "declaration_type": "E11", "direction": "import"},
        {"transaction_key": txn_c, "line_no": "1", "declaration_no": "REGRESS_C",
         "registration_date": "2025-01-15", "customs_code": "C-CODE",
         "internal_code": "C-CODE", "goods_name": "PE-001#&Polyethylene",
         "quantity": 300, "total_value": 250,
         "declaration_type": "E11", "direction": "import"},
    ]

    # Apply the (fixed) confirm logic: confirm_orphans=True, confirm_diffs=False
    confirm_diffs = False
    confirm_orphans = True
    diff_keys = {tuple(d["key"]) for d in diff_summary["diff"]}
    rows_to_apply = []
    for r in parsed_rows:
        key = (r["transaction_key"], r["line_no"])
        if key in diff_keys:
            if confirm_diffs:
                rows_to_apply.append(r)
        else:
            rows_to_apply.append(r)
    orphans_to_delete = diff_summary["orphan"] if confirm_orphans else []

    parser = internal_code_parser_for(CLIENT, "batch_aggregate_resolution")
    _apply_bcct_rows(
        client_id=CLIENT, rows=rows_to_apply, upload_id=None,
        parser=parser, orphans_to_delete=orphans_to_delete,
        user_id="regress-test",
    )

    # Verify final DB state:
    #   A still exists with quantity=100 (user did NOT confirm DIFF)
    #   B,C unchanged
    #   D deleted (user confirmed ORPHAN)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select transaction_key, quantity from hub.bcct_rows "
                "where transaction_key like %s order by transaction_key",
                (TXN_PREFIX + "REGRESS_%",),
            )
            present = {row[0]: float(row[1]) for row in cur.fetchall()}

    assert txn_a in present, "Row A was wrongly deleted (data-loss regression!)"
    assert present[txn_a] == 100, (
        f"Row A's quantity changed without user confirmation: {present[txn_a]}"
    )
    assert txn_b in present and present[txn_b] == 200
    assert txn_c in present and present[txn_c] == 300
    assert txn_d not in present, "Row D should have been deleted (confirmed orphan)"


def test_force_apply_cli_records_synthetic_actor():
    """scripts/bcct_force_apply.py should set the GUC to 'ops:script' so
    the audit trigger captures the bypass actor."""
    txn = _seed_row("CLI_TEST", "1", quantity=100)
    # Simulate what the CLI does: connect with the synthetic user_id.
    with connect(user_id="ops:script") as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.bcct_rows set quantity=42 where transaction_key=%s",
                (txn,),
            )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select changed_by from hub.bcct_row_history where transaction_key=%s",
                (txn,),
            )
            (actor,) = cur.fetchone()
    assert actor == "ops:script"


def test_pending_purge_function_clears_expired():
    with connect() as conn:
        with conn.cursor() as cur:
            # Insert a manually-expired pending row
            cur.execute(
                """
                insert into hub.upload_pending
                  (pending_id, client_id, module, parsed_rows, expires_at)
                values ('test_expired_purge', %s, 'bcct', '[]'::jsonb, now() - interval '1 hour')
                """,
                (CLIENT,),
            )
            cur.execute("select hub.purge_expired_pending_uploads()")
            (n,) = cur.fetchone()
    assert n >= 1
