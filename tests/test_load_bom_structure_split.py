"""Phase 2 — tách Load BOM (cấu trúc) khỏi Tính bảng kê (phân bổ tồn).

allocate=False khai triển NVL theo cấu trúc BOM mà KHÔNG đụng tồn:
- field cấu trúc (mã NVL, định mức, lượng dùng, xuất xứ, mô tả) đầy đủ
- field phân bổ trung tính (không có dòng phân bổ, trị giá rỗng, không cảnh báo thiếu tồn)
- LVC sản phẩm = "Chưa tính", KHÔNG bịa 100%.
"""
from __future__ import annotations

from decimal import Decimal

from app.web.co_case_context import (
    ORIGIN_SHEET_STATUS_LABELS,
    attach_origin_sheet_states,
    origin_material_from_bom_row,
    origin_product_from_invoice_match,
    origin_sheet_action_error,
    origin_sheet_export_blockers,
    prepare_case_origin_sheet,
)


def _bom_row(**extra):
    base = {"material_code": "M1", "qty_per": "2", "uom": "kg", "material_name": "Thép tấm", "hs_code": "7208"}
    base.update(extra)
    return base


def _stock_pool_with_lot():
    # A real lot for M1 — allocate=False must IGNORE it (0 phân bổ).
    return {
        "M1": [
            {
                "source_row": "ROW-1",
                "material_code": "M1",
                "available_qty": "1000",
                "remaining_qty": "1000",
                "unit_value": "5000",
                "currency": "VND",
                "value_currency": "VND",
                "import_declaration_no": "D1",
                "line_no": "1",
            }
        ]
    }


def test_material_structure_only_skips_allocation():
    mat = origin_material_from_bom_row(
        _bom_row(),
        Decimal("10"),
        {"M1": {"name": "Thép tấm", "hs_code": "7208"}},
        _stock_pool_with_lot(),
        product_sequence=1,
        product_code="TP1",
        product_name="Sản phẩm 1",
        material_sequence=1,
        allocate=False,
    )
    # cấu trúc đầy đủ
    assert mat["material_code"] == "M1"
    assert mat["consumed_qty"] == Decimal("20")  # 10 * 2
    assert mat["bom_qty_per"] == "2"
    assert mat["uom"] == "kg"
    assert mat["material_description"] == "Thép tấm"
    assert mat["hs_code"] == "7208"
    assert mat["material_sequence"] == "1"
    # phân bổ trung tính — KHÔNG đụng lot có trong pool
    assert mat["allocation_lines"] == []
    assert mat["material_value"] == ""
    assert mat["non_origin_cif_value"] == ""
    assert mat["valuation_status"] == "not_calculated"
    assert mat["allocation_status"] == "pending"
    assert mat["allocation_shortage_qty"] == ""
    # không cảnh báo "thiếu tồn"/"thiếu đơn giá" ở giai đoạn nạp cấu trúc
    warnings_text = " ".join(mat.get("material_warnings", []))
    assert "thiếu tồn" not in warnings_text.lower()
    assert "thiếu đơn giá" not in warnings_text.lower()


def test_material_allocate_true_still_allocates():
    # Bảo hiểm hồi quy: allocate mặc định vẫn phân bổ lot trong pool.
    mat = origin_material_from_bom_row(
        _bom_row(),
        Decimal("10"),
        {"M1": {"name": "Thép tấm", "hs_code": "7208"}},
        _stock_pool_with_lot(),
        product_sequence=1,
        product_code="TP1",
        product_name="Sản phẩm 1",
        material_sequence=1,
    )
    assert mat["allocation_lines"]  # có phân bổ
    assert mat["valuation_status"] != "not_calculated"


def _invoice_match():
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


def test_product_structure_only_lvc_not_calculated():
    product = origin_product_from_invoice_match(
        _invoice_match(),
        [_bom_row()],
        {},
        {"M1": {"name": "Thép tấm"}},
        _stock_pool_with_lot(),
        product_sequence=1,
        bom_product_code="TP1",
        allocate=False,
    )
    assert product["materials"], "phải khai triển NVL theo cấu trúc"
    assert len(product["materials"]) == 1
    # KHÔNG bịa LVC 100% khi chưa phân bổ
    assert product["lvc_percentage"] == ""
    assert product["lvc_status"] not in {"pass", "partial_pass"}
    assert product.get("origin_not_calculated") is True


def test_allocate_true_clears_not_calculated_marker():
    """Marker không rò sang sheet đã tính: build lại allocate=True ⇒ marker False + LVC thật."""
    full = origin_product_from_invoice_match(
        _invoice_match(),
        [_bom_row()],
        {},
        {"M1": {"name": "Thép tấm"}},
        _stock_pool_with_lot(),
        product_sequence=1,
        bom_product_code="TP1",
        allocate=True,
    )
    assert full.get("origin_not_calculated") is False
    assert full["lvc_status"] != "not_calculated"


def _case_with_one_product():
    return {"products": [{"code": "TP1", "name": "Sản phẩm 1"}]}


def _bom_workspace():
    return {
        "latest_rows": [
            {"product_code": "TP1", "material_code": "M1", "qty_per": "2", "uom": "kg",
             "material_name": "Thép tấm", "hs_code": "7208"},
        ]
    }


def test_prepare_case_origin_sheet_allocate_false_expands_structure_no_allocation():
    prepared = prepare_case_origin_sheet(
        _case_with_one_product(),
        "TP1",
        [_invoice_match()],
        _bom_workspace(),
        {},
        [],  # material_rows
        [],  # stock_rows — allocate=False phải bỏ qua, không gọi case_allocation_pool
        allocate=False,
    )
    products = prepared.get("products", [])
    target = next(p for p in products if p.get("code") == "TP1")
    assert target.get("origin_not_calculated") is True
    assert target["materials"], "phải khai triển NVL theo cấu trúc"
    mat = target["materials"][0]
    assert mat["material_code"] == "M1"
    assert mat["consumed_qty"] in ("20", Decimal("20"))
    assert mat["allocation_lines"] == []
    assert mat["allocation_status"] == "pending"


def _case_bom_loaded():
    return {
        "products": [{"code": "TP1", "name": "Sản phẩm 1"}],
        "origin_sheet_states": {"TP1": {"status": "bom_loaded"}},
    }


def test_bom_loaded_is_a_known_status():
    assert "bom_loaded" in ORIGIN_SHEET_STATUS_LABELS


def test_bom_loaded_survives_attach_not_reset_to_draft():
    prepared = attach_origin_sheet_states(_case_bom_loaded())
    assert prepared["products"][0]["origin_sheet_status"] == "bom_loaded"


def test_bom_loaded_cannot_lock():
    prepared = attach_origin_sheet_states(_case_bom_loaded())
    assert prepared["products"][0]["origin_can_lock"] is False
    assert origin_sheet_action_error(_case_bom_loaded(), "TP1", "lock")


def test_bom_loaded_blocks_export():
    assert "TP1" in origin_sheet_export_blockers(_case_bom_loaded())


def test_bom_loaded_can_calculate():
    prepared = attach_origin_sheet_states(_case_bom_loaded())
    assert prepared["products"][0]["origin_can_calculate"] is True


# --- endpoint wiring (material expansion covered by unit tests above) ---

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.co_case_store import get_case_record, update_case_record  # noqa: E402
from app.demo_data import get_client  # noqa: E402


def _seed_growatt_case(case_code: str, product_code: str) -> str:
    http = TestClient(app)
    created = http.post(
        "/clients/growatt/co-case/create",
        data={"title": case_code, "case_code": case_code, "destination_market": "Ấn Độ",
              "invoice_no": f"INV-{case_code}"},
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
            "products": [{"code": product_code, "name": "SP", "quantity": "1", "unit": "PCS",
                          "fob": "100", "currency": "USD", "materials": []}],
            "origin_product_order": [product_code],
        },
    )
    return case_id


def test_load_bom_no_artifact_does_not_falsely_mark_loaded():
    # Load BOM on a product with NO BOM artifact (0 rows to load) must NOT report
    # "Đã nạp BOM" nor advance status to bom_loaded — that would show a loaded state
    # on an empty sheet. (In file-mode there is no Data Hub BOM, so nothing loads.)
    case_id = _seed_growatt_case("CO-LOADBOM-1", "TP1")
    http = TestClient(app)
    resp = http.post(f"/clients/growatt/co-case/{case_id}/origin/sheet/TP1/load-bom", json={})
    assert resp.status_code == 200
    stored = get_case_record(get_client("growatt"), case_id)
    assert stored.get("origin_sheet_states", {}).get("TP1", {}).get("status") != "bom_loaded"
    assert "chưa có BOM artifact" in resp.text


def test_load_bom_then_lock_is_blocked():
    case_id = _seed_growatt_case("CO-LOADBOM-2", "TP1")
    http = TestClient(app)
    http.post(f"/clients/growatt/co-case/{case_id}/origin/sheet/TP1/load-bom", json={})
    locked = http.post(f"/clients/growatt/co-case/{case_id}/origin/sheet/TP1/lock", json={})
    # bom_loaded chưa tính ⇒ không chốt được
    assert locked.status_code == 409


def _seed_growatt_case_with_material_and_override(case_code: str) -> str:
    http = TestClient(app)
    created = http.post(
        "/clients/growatt/co-case/create",
        data={"title": case_code, "case_code": case_code, "destination_market": "Ấn Độ",
              "invoice_no": f"INV-{case_code}"},
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
            "products": [{
                "code": "TP1", "name": "SP", "quantity": "10", "unit": "PCS",
                "fob": "1000", "currency": "USD",
                "materials": [{
                    "material_code": "M1", "material_description": "Thép tấm", "hs_code": "7208",
                    "bom_qty_per": "2", "uom": "kg", "bom_source": "seed", "unit_value": "5",
                    "allocation_lines": [],
                }],
            }],
            "origin_product_order": ["TP1"],
            # mô phỏng: đã Load BOM rồi sửa định mức dòng 0 (edit-row → override, stale)
            "origin_sheet_states": {"TP1": {
                "status": "stale",
                "material_overrides": {"0": {"norm_per_unit": "5", "norm_edit_only": True}},
            }},
        },
    )
    return case_id


def test_origin_page_renders_split_load_bom_and_tinh_buttons():
    case_id = _seed_growatt_case("CO-BTN", "TP1")
    http = TestClient(app)
    page = http.get(f"/clients/growatt/co-case/{case_id}/origin")
    assert page.status_code == 200
    assert "Load BOM" in page.text
    assert "Tính bảng kê" in page.text
    assert f"/origin/sheet/TP1/load-bom" in page.text
    assert f"/origin/sheet/TP1/calculate" in page.text


def test_calculate_preserves_material_overrides_not_wiped():
    """DU1 — Tính bảng kê GIỮ chỉnh sửa NVL (override) thay vì xóa."""
    case_id = _seed_growatt_case_with_material_and_override("CO-DU1")
    http = TestClient(app)
    resp = http.post(f"/clients/growatt/co-case/{case_id}/origin/sheet/TP1/calculate", json={})
    assert resp.status_code == 200
    stored = get_case_record(get_client("growatt"), case_id)
    overrides = stored["origin_sheet_states"]["TP1"].get("material_overrides") or {}
    assert "0" in overrides, "override (chỉnh sửa NVL) phải được giữ sau khi Tính bảng kê"
    assert overrides["0"].get("norm_per_unit") == "5"
