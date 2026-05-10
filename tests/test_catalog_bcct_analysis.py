"""Tests for app.stores.catalog_bcct_analysis."""
from __future__ import annotations

import pytest

from app.database import connect
from app.routes.clients import upsert_client
from app.stores.catalog_bcct_analysis import analyze_material_bcct


@pytest.fixture
def client_id():
    cid = "test-bcct-analysis"
    upsert_client(
        client_id=cid, name="Test BCCT Analysis",
        tax_code=None, code_resolution_mode="identity",
        bom_proposal_mode="manual", bom_proposal_qty_tolerance_pct=5.0,
        bom_approver_tier="edit", status="active", notes=None,
    )
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


def _insert_bcct(client_id, **rows):
    """rows: dict of transaction_key→col-overrides. Inserts a BCCT row.
    Defaults provide a sane row with import direction + customs_code='X1'."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.file_uploads
              (upload_id, client_id, module, original_filename,
               stored_path, content_sha256, size_bytes,
               parse_status, row_count)
            values ('bcct-an-up', %s, 'bcct', 't.xls', 't', 'x', 0, 'done', 0)
            on conflict do nothing
            """, (client_id,),
        )
        for tx, ov in rows.items():
            defaults = dict(
                line_no="1", declaration_no="100001",
                declaration_type="E11", direction="import",
                registration_date="2026-04-01", customs_code="X1",
                goods_name="goods", hs_code="12345678",
                quantity=1.0, unit="pcs",
                total_value=100.0, currency_nt="USD",
                origin="VN", unit_price=10.0,
                upload_id="bcct-an-up",
            )
            defaults.update(ov)
            cols = ["client_id", "transaction_key"] + list(defaults.keys())
            ph = ", ".join(["%s"] * len(cols))
            vals = [client_id, tx] + list(defaults.values())
            cur.execute(
                f"insert into hub.bcct_rows ({', '.join(cols)}) values ({ph})",
                vals,
            )
        conn.commit()


def test_no_drift_single_consistent_row(client_id):
    _insert_bcct(client_id, **{"100001-1": {}})
    a = analyze_material_bcct(client_id=client_id, material_code="X1")
    assert a.bcct_row_count == 1
    assert a.declaration_count == 1
    assert a.direction_breakdown == {"import": 1}
    assert a.drifts == []
    assert a.representative is not None
    assert a.representative.unit == "pcs"


def test_uom_drift_critical(client_id):
    _insert_bcct(client_id, **{
        "100001-1": {"unit": "pcs"},
        "100002-1": {"unit": "kg", "declaration_no": "100002"},
    })
    a = analyze_material_bcct(client_id=client_id, material_code="X1")
    assert a.bcct_row_count == 2
    assert any(d.field == "unit" and d.severity == "critical" for d in a.drifts)
    assert a.has_critical is True


def test_hs_drift_warn(client_id):
    _insert_bcct(client_id, **{
        "100001-1": {"hs_code": "12345678"},
        "100002-1": {"hs_code": "87654321", "declaration_no": "100002"},
    })
    a = analyze_material_bcct(client_id=client_id, material_code="X1")
    hs = next(d for d in a.drifts if d.field == "hs_code")
    assert hs.severity == "warn"
    assert hs.distinct_count == 2
    assert a.has_critical is False


def test_representative_picks_most_frequent(client_id):
    _insert_bcct(client_id, **{
        "100001-1": {"unit": "pcs", "goods_name": "Common"},
        "100002-1": {"unit": "pcs", "goods_name": "Common",
                     "declaration_no": "100002"},
        "100003-1": {"unit": "pcs", "goods_name": "Common",
                     "declaration_no": "100003"},
        "100004-1": {"unit": "kg", "goods_name": "Rare",
                     "declaration_no": "100004"},
    })
    a = analyze_material_bcct(client_id=client_id, material_code="X1")
    assert a.representative is not None
    assert a.representative.goods_name == "Common"
    assert a.representative.unit == "pcs"
    assert a.representative.occurrence_count == 3


def test_mixed_directions(client_id):
    _insert_bcct(client_id, **{
        "100001-1": {"direction": "import"},
        "200001-1": {"direction": "export", "declaration_no": "200001"},
    })
    a = analyze_material_bcct(client_id=client_id, material_code="X1")
    assert a.direction_breakdown == {"import": 1, "export": 1}
    assert a.bcct_row_count == 2


def test_no_bcct_rows_returns_empty(client_id):
    a = analyze_material_bcct(client_id=client_id, material_code="UNKNOWN")
    assert a.bcct_row_count == 0
    assert a.declaration_count == 0
    assert a.representative is None
    assert a.drifts == []
