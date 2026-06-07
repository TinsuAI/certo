"""`dossier_content_revision` — the staleness key for a saved dossier export.

It must change when anything that lands in the .zip changes (bảng kê / products,
chứng từ, shipment declarations, close-state) and stay constant across benign
derived-data drift (source/bom/origin snapshots, timestamps), so a cached export
isn't needlessly regenerated nor wrongly served stale.
"""
from __future__ import annotations

from app.web.co_case_context import dossier_content_revision


def _record():
    return {
        "case_id": "co-case-1",
        "case_code": "CO-X",
        "status": "completed",
        "shipment": {"invoice_no": "INV1", "export_declaration_nos": ["308491637440"], "bill_of_lading_no": "BL1"},
        "products": [{"code": "TP1", "materials": [{"material_code": "M1", "consumed_qty": "1"}]}],
        "origin_sheet_states": {"TP1": {"status": "locked"}},
        "supporting_files": [{"content_sha256": "aaa", "slot": "bill", "filename": "bl.pdf"}],
    }


def test_same_content_same_revision():
    assert dossier_content_revision(_record()) == dossier_content_revision(_record())


def test_bang_ke_change_changes_revision():
    a = _record()
    b = _record()
    b["products"][0]["materials"][0]["consumed_qty"] = "2"
    assert dossier_content_revision(a) != dossier_content_revision(b)


def test_supporting_file_change_changes_revision():
    a = _record()
    b = _record()
    b["supporting_files"][0]["content_sha256"] = "bbb"
    assert dossier_content_revision(a) != dossier_content_revision(b)


def test_shipment_declaration_change_changes_revision():
    a = _record()
    b = _record()
    b["shipment"]["export_declaration_nos"] = ["999999999999"]
    assert dossier_content_revision(a) != dossier_content_revision(b)


def test_close_state_change_changes_revision():
    a = _record()
    b = _record()
    b["status"] = "open"
    assert dossier_content_revision(a) != dossier_content_revision(b)


def test_derived_drift_does_not_change_revision():
    a = _record()
    b = _record()
    # Volatile/derived fields recomputed every render must not flip the key.
    b["updated_at"] = "2026-06-07T10:00:00+00:00"
    b["source_snapshot"] = {"bcct_reviewed_row_count": 999}
    b["bom_snapshot"] = {"x": 1}
    b["origin_snapshot"] = {"y": 2}
    b["source_invoice_matches"] = [{"declaration_no": "z"}]
    assert dossier_content_revision(a) == dossier_content_revision(b)
