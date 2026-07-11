"""BG1 — xoá NVL trên bảng kê là SOFT delete: giữ dòng trong materials (gắn cờ
`deleted`), index ổn định, loại khỏi tính VNM/LVC/phân bổ.

Bug gốc: `sheet_edit_bom_rows` `continue` bỏ dòng deleted ⇒ `recalculate_origin_sheet_edits`
co `materials` + persist list đã co, NHƯNG override vẫn key theo index cũ ⇒ lần xoá kế
tiếp key rơi trúng dòng kế bên (đã dịch) ⇒ mất dòng thật, fold "đã xoá" kẹt ở 1.
"""
from __future__ import annotations

from decimal import Decimal

from app.routers.co_case import sheet_edit_bom_rows
from app.web.co_case_context import (
    attach_origin_sheet_states,
    decimal_value,
    origin_product_from_invoice_match,
)


def _product(n: int) -> dict:
    return {
        "code": "TP1",
        "bom_product_code": "TP1",
        "materials": [
            {
                "material_code": f"M{i}",
                "material_description": f"NVL {i}",
                "hs_code": "7208",
                "bom_qty_per": "2",
                "uom": "kg",
                "bom_source": "seed",
                "unit_value": "5",
            }
            for i in range(1, n + 1)
        ],
    }


# --- sheet_edit_bom_rows: soft delete, index-stable -------------------------

def test_sheet_edit_bom_rows_keeps_deleted_row_flagged():
    rows = sheet_edit_bom_rows(_product(3), {"2": {"deleted": True}})
    assert len(rows) == 3, "soft delete: dòng deleted phải GIỮ trong output (index ổn định)"
    assert rows[1].get("deleted") is True
    assert rows[1]["material_code"] == "M2", "dòng deleted giữ danh tính gốc"


def test_sheet_edit_bom_rows_neighbors_keep_identity():
    rows = sheet_edit_bom_rows(_product(3), {"2": {"deleted": True}})
    assert rows[0]["material_code"] == "M1" and not rows[0].get("deleted")
    assert rows[2]["material_code"] == "M3" and not rows[2].get("deleted")


# --- origin_product_from_invoice_match: deleted excluded from VNM/LVC --------

def _invoice_match() -> dict:
    return {
        "item_code": "TP1",
        "description": "Sản phẩm 1",
        "hs_code": "8501",
        "quantity": "10",
        "unit": "cái",
        "fob_value": "1000000",
        "fob_currency": "VND",
        "currency": "VND",
    }


def _lot(code: str) -> dict:
    return {
        "source_row": f"R-{code}",
        "material_code": code,
        "available_qty": "1000",
        "remaining_qty": "1000",
        "unit_value": "10",
        "currency": "VND",
        "value_currency": "VND",
        "import_declaration_no": "D1",
        "line_no": "1",
    }


def _bom_row(code: str, **extra) -> dict:
    base = {"material_code": code, "qty_per": "1", "uom": "kg", "material_name": code, "hs_code": "7208"}
    base.update(extra)
    return base


def _product_from_rows(bom_rows: list[dict]) -> dict:
    return origin_product_from_invoice_match(
        _invoice_match(),
        bom_rows,
        {},
        {},  # empty catalog ⇒ default_conservative ⇒ non_origin (counts toward VNM)
        {"M1": [_lot("M1")], "M2": [_lot("M2")]},
        product_sequence=1,
        bom_product_code="TP1",
        allocate=True,
    )


def test_deleted_row_kept_in_materials_but_excluded_from_vnm():
    both = _product_from_rows([_bom_row("M1"), _bom_row("M2")])
    one_deleted = _product_from_rows([_bom_row("M1"), _bom_row("M2", deleted=True)])
    assert len(one_deleted["materials"]) == 2, "dòng deleted vẫn nằm trong materials"
    assert one_deleted["materials"][1].get("deleted") is True
    assert not one_deleted["materials"][1].get("non_origin_cif_value"), "dòng deleted trị giá rỗng"
    assert decimal_value(one_deleted["vnm_value"]) < decimal_value(both["vnm_value"]), (
        "VNM phải LOẠI dòng deleted"
    )


def test_all_deleted_does_not_fabricate_lvc():
    product = _product_from_rows([_bom_row("M1", deleted=True)])
    assert product["materials"][0].get("deleted") is True
    assert product["lvc_status"] not in {"pass", "partial_pass"}, "all-deleted không được bịa LVC đạt"


# --- end-to-end regression qua /save (growatt file-mode, no .env) ------------

from fastapi.testclient import TestClient  # noqa: E402

from app.co_case_store import get_case_record, update_case_record  # noqa: E402
from app.demo_data import get_client  # noqa: E402
from app.main import app  # noqa: E402


def _seed_growatt_case_n_materials(case_code: str, n: int) -> str:
    http = TestClient(app)
    created = http.post(
        "/clients/growatt/co-case/create",
        data={
            "title": case_code,
            "case_code": case_code,
            "destination_market": "Ấn Độ",
            "invoice_no": f"INV-{case_code}",
        },
        follow_redirects=False,
    )
    case_id = created.headers["location"].rstrip("/").split("/")[-1]
    update_case_record(
        get_client("growatt"),
        {
            "persisted_case_id": case_id,
            "case_code": case_code,
            "title": case_code,
            "destination_market": "Ấn Độ",
            "shipment": {"invoice_no": f"INV-{case_code}"},
            "products": [
                {
                    "code": "TP1",
                    "name": "SP",
                    "quantity": "10",
                    "unit": "PCS",
                    "fob": "1000",
                    "currency": "USD",
                    "materials": [
                        {
                            "material_code": f"M{i}",
                            "material_description": f"NVL {i}",
                            "hs_code": "7208",
                            "bom_qty_per": "2",
                            "uom": "kg",
                            "bom_source": "seed",
                            "unit_value": "5",
                            "allocation_lines": [],
                        }
                        for i in range(1, n + 1)
                    ],
                }
            ],
            "origin_product_order": ["TP1"],
            "origin_sheet_states": {"TP1": {"status": "calculated"}},
        },
    )
    return case_id


def _active_codes(stored: dict) -> list[str]:
    mats = stored["products"][0]["materials"]
    return [m["material_code"] for m in mats if not m.get("deleted")]


def _deleted_count(stored: dict) -> int:
    ov = stored["origin_sheet_states"]["TP1"].get("material_overrides") or {}
    return sum(1 for v in ov.values() if v.get("deleted"))


def test_successive_single_deletes_do_not_lose_extra_rows():
    case_id = _seed_growatt_case_n_materials("CO-SOFTDEL-1", 4)
    http = TestClient(app)
    base = f"/clients/growatt/co-case/{case_id}/origin/sheet/TP1"

    r1 = http.post(f"{base}/save", json={"deletes": {"2": True}})
    assert r1.status_code == 200
    stored = get_case_record(get_client("growatt"), case_id)
    assert len(stored["products"][0]["materials"]) == 4, "length giữ nguyên (soft delete)"
    assert _active_codes(stored) == ["M1", "M3", "M4"]
    assert _deleted_count(stored) == 1

    # sequence 3 = M3 — key VẪN ổn định vì materials không co
    r2 = http.post(f"{base}/save", json={"deletes": {"3": True}})
    assert r2.status_code == 200
    stored2 = get_case_record(get_client("growatt"), case_id)
    assert len(stored2["products"][0]["materials"]) == 4
    assert _active_codes(stored2) == ["M1", "M4"], "chỉ M2,M3 bị xoá — không mất dòng thừa"
    assert _deleted_count(stored2) == 2, "fold 'đã xoá' phải cộng dồn = 2"


def test_diff_removed_accumulates_in_render_state():
    case_id = _seed_growatt_case_n_materials("CO-SOFTDEL-2", 4)
    http = TestClient(app)
    base = f"/clients/growatt/co-case/{case_id}/origin/sheet/TP1"
    http.post(f"{base}/save", json={"deletes": {"1": True}})
    http.post(f"{base}/save", json={"deletes": {"2": True}})
    stored = get_case_record(get_client("growatt"), case_id)
    prepared = attach_origin_sheet_states(stored)
    target = next(p for p in prepared["products"] if p["code"] == "TP1")
    assert target["origin_sheet_material_diff_removed"] == 2
