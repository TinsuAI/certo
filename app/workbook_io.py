from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter

from app.bang_ke_renderer import load_form_config, render_into_sheet
from app.bang_ke_xml_generator import render_case as render_case_via_xml
from app.demo_data import attach_results, get_demo_case

# Criteria migrated to the config-driven renderer (approach B).
# All five form-mau criteria are now driven by JSON config under
# config/bang-ke-forms/. The hardcoded Python mappings below are retained
# only as a fallback when no config is present (e.g. for the shell builder).
_CONFIG_DRIVEN_CRITERIA: set[str] = {"LVC", "CTH", "CTSH", "RVC", "PSR"}


def _render_via_config(ws_copy, sheet_code: str, case: dict, product: dict, sheet_title: str) -> bool:
    """If `sheet_code` has a JSON config, render through the engine and return True.

    Otherwise return False so the caller falls back to the legacy hardcoded path.
    """
    if sheet_code not in _CONFIG_DRIVEN_CRITERIA:
        return False
    try:
        config = load_form_config(sheet_code)
    except FileNotFoundError:
        return False
    render_into_sheet(ws_copy, config, case=case, product=product, sheet_title=sheet_title)
    return True

CASE_HEADERS = ["field", "value"]
DOCUMENT_HEADERS = ["slot", "label", "reference", "status"]
PRODUCT_HEADERS = [
    "product_code",
    "product_name",
    "finished_hs",
    "shipment_quantity",
    "fob_value",
    "rvc_threshold",
    "documented_result",
]
MATERIAL_HEADERS = [
    "product_code",
    "source_row",
    "import_declaration_no",
    "import_line_no",
    "customs_material_code",
    "internal_material_code",
    "material_description",
    "material_hs",
    "origin_status",
    "available_qty",
    "consumed_qty",
    "non_origin_cif_value",
    "uom",
    "source_document_ref",
]


class WorkbookParseError(ValueError):
    pass


def cell_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def decimal_value(value: Any) -> Decimal:
    text = cell_text(value).replace(",", "")
    if not text:
        return Decimal("0")
    return Decimal(text)


def create_input_workbook(case: dict | None = None) -> bytes:
    case = case or get_demo_case()
    wb = Workbook()
    ws = wb.active
    ws.title = "Case"
    ws.append(CASE_HEADERS)
    for field in [
        "id",
        "customer",
        "case_code",
        "title",
        "destination_market",
        "agreement",
        "co_form_type",
        "rule",
        "mode",
        "mode_note",
        "source_label",
    ]:
        ws.append([field, case.get(field, "")])

    docs = wb.create_sheet("Documents")
    docs.append(DOCUMENT_HEADERS)
    for document in case.get("documents", []):
        docs.append([document.get(header, "") for header in DOCUMENT_HEADERS])

    products = wb.create_sheet("Products")
    products.append(PRODUCT_HEADERS)
    for product in case.get("products", []):
        products.append(
            [
                product.get("code", ""),
                product.get("name", ""),
                product.get("finished_hs", ""),
                product.get("quantity", ""),
                product.get("fob", ""),
                product.get("rvc_threshold", ""),
                product.get("documented_result", ""),
            ]
        )

    materials = wb.create_sheet("Materials")
    materials.append(MATERIAL_HEADERS)
    for product in case.get("products", []):
        for material in product.get("materials", []):
            materials.append(
                [
                    product.get("code", ""),
                    material.get("source_row", ""),
                    material.get("import_declaration_no", ""),
                    material.get("import_line_no", ""),
                    material.get("customs_material_code", material.get("material_code", "")),
                    material.get("internal_material_code", material.get("material_code", "")),
                    material.get("material_description", ""),
                    material.get("hs_code", ""),
                    material.get("origin_status", ""),
                    material.get("available_qty", ""),
                    material.get("consumed_qty", ""),
                    material.get("non_origin_cif_value", ""),
                    material.get("uom", ""),
                    material.get("source_document_ref", ""),
                ]
            )

    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


def parse_input_workbook(content: bytes, source_label: str = "Workbook upload") -> dict:
    try:
        wb = load_workbook(BytesIO(content), data_only=True)
    except Exception as exc:
        raise WorkbookParseError(f"Không đọc được workbook: {exc}") from exc

    required_sheets = {"Case", "Documents", "Products", "Materials"}
    missing = required_sheets - set(wb.sheetnames)
    if missing:
        raise WorkbookParseError("Thiếu sheet: " + ", ".join(sorted(missing)))

    case_values = read_key_values(wb["Case"])
    case = {
        "id": case_values.get("id", "uploaded-co-case"),
        "customer": case_values.get("customer", ""),
        "case_code": case_values.get("case_code", ""),
        "title": case_values.get("title", "Hồ sơ C/O upload"),
        "destination_market": case_values.get("destination_market", ""),
        "agreement": case_values.get("agreement", ""),
        "co_form_type": case_values.get("co_form_type", ""),
        "rule": case_values.get("rule", "RVC 35% + CTSH"),
        "mode": case_values.get("mode", "Upload workbook"),
        "mode_note": case_values.get("mode_note", ""),
        "source_label": source_label,
        "documents": [],
        "workflow": get_demo_case()["workflow"],
        "products": [],
    }

    case["documents"] = [
        {
            "slot": row.get("slot", ""),
            "label": row.get("label", ""),
            "reference": row.get("reference", ""),
            "status": row.get("status", "pending") or "pending",
        }
        for row in read_table(wb["Documents"])
        if row.get("slot") or row.get("label") or row.get("reference")
    ]

    products_by_code: dict[str, dict] = {}
    for row in read_table(wb["Products"]):
        product_code = row.get("product_code", "")
        if not product_code:
            continue
        product = {
            "code": product_code,
            "name": row.get("product_name", ""),
            "finished_hs": row.get("finished_hs", ""),
            "quantity": row.get("shipment_quantity", ""),
            "fob": row.get("fob_value", "0"),
            "non_origin_value": "",
            "rvc_threshold": row.get("rvc_threshold", "35") or "35",
            "documented_result": row.get("documented_result", ""),
            "materials": [],
        }
        products_by_code[product_code] = product
        case["products"].append(product)

    for row in read_table(wb["Materials"]):
        product_code = row.get("product_code", "")
        if product_code not in products_by_code:
            continue
        products_by_code[product_code]["materials"].append(
            {
                "source_row": row.get("source_row", ""),
                "import_declaration_no": row.get("import_declaration_no", ""),
                "import_line_no": row.get("import_line_no", ""),
                "material_code": row.get("internal_material_code") or row.get("customs_material_code", ""),
                "customs_material_code": row.get("customs_material_code", ""),
                "internal_material_code": row.get("internal_material_code", ""),
                "material_description": row.get("material_description", ""),
                "hs_code": row.get("material_hs", ""),
                "origin_status": row.get("origin_status", "non_origin") or "non_origin",
                "available_qty": decimal_value(row.get("available_qty", "0")),
                "consumed_qty": decimal_value(row.get("consumed_qty", "0")),
                "non_origin_cif_value": decimal_value(row.get("non_origin_cif_value", "0")),
                "uom": row.get("uom", ""),
                "source_document_ref": row.get("source_document_ref", ""),
            }
        )

    if not case["products"]:
        raise WorkbookParseError("Workbook không có dòng Products hợp lệ.")
    return attach_results(case)


def read_key_values(ws) -> dict[str, str]:
    values = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        key = cell_text(row[0])
        if key:
            values[key] = cell_text(row[1] if len(row) > 1 else "")
    return values


def read_table(ws) -> list[dict[str, str]]:
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [cell_text(value) for value in rows[0]]
    output = []
    for raw in rows[1:]:
        row = {headers[index]: cell_text(value) for index, value in enumerate(raw) if index < len(headers)}
        if any(row.values()):
            output.append(row)
    return output


def create_evidence_workbook(case: dict) -> bytes:
    wb = Workbook()
    summary = wb.active
    summary.title = "Summary"
    summary.append(["customer", case.get("customer", "")])
    summary.append(["case_code", case.get("case_code", "")])
    summary.append(["rule", case.get("rule", "")])
    summary.append(["passed_products", case["summary"]["passed_products"]])
    summary.append(["product_count", case["summary"]["product_count"]])
    summary.append(["min_rvc", str(case["summary"]["min_rvc"])])

    products = wb.create_sheet("Product Results")
    products.append(
        [
            "product_code",
            "finished_hs",
            "fob",
            "non_origin_cif",
            "rvc_percent",
            "rvc_pass",
            "ctsh_pass",
            "combined_pass",
        ]
    )
    for product in case.get("products", []):
        result = product["result"]
        products.append(
            [
                product.get("code", ""),
                product.get("finished_hs", ""),
                str(result.rvc.fob),
                str(result.rvc.non_origin_value),
                str(result.rvc.percentage),
                result.rvc.passed,
                result.tariff_shift.passed,
                result.passed,
            ]
        )

    materials = wb.create_sheet("Allocation Trace")
    materials.append(
        [
            "product_code",
            "source_row",
            "import_declaration_no",
            "import_line_no",
            "customs_material_code",
            "internal_material_code",
            "material_hs",
            "origin_status",
            "available_qty",
            "consumed_qty",
            "remaining_qty",
            "non_origin_cif_value",
        ]
    )
    for product in case.get("products", []):
        for material in product.get("materials", []):
            remaining = material.get("available_qty", 0) - material.get("consumed_qty", 0)
            materials.append(
                [
                    product.get("code", ""),
                    material.get("source_row", ""),
                    material.get("import_declaration_no", ""),
                    material.get("import_line_no", ""),
                    material.get("customs_material_code", ""),
                    material.get("internal_material_code", ""),
                    material.get("hs_code", ""),
                    material.get("origin_status", ""),
                    str(material.get("available_qty", "")),
                    str(material.get("consumed_qty", "")),
                    str(remaining),
                    str(material.get("non_origin_cif_value", "")),
                ]
            )

    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


def write_seed_workbook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(create_input_workbook(get_demo_case()))


# HQ "Bảng kê C/O" exporter — mirrors structure of legacy
# `tru lui CO final ...xlsm` workbook documented in
# docs/legacy-workbook-output-sheet-structure.md.

HQ_SHEET_DEFS = [
    {"sheet": "LVC", "title": 'BẢNG TÍNH HÀM LƯỢNG VÀ KÊ KHAI HÀNG HÓA XUẤT KHẨU ĐẠT TIÊU CHÍ "LVC"', "default_threshold": "30"},
    {"sheet": "RVC", "title": 'BẢNG KÊ KHAI HÀNG HÓA XUẤT KHẨU ĐẠT TIÊU CHÍ "RVC"', "default_threshold": "40"},
    {"sheet": "CTH", "title": 'BẢNG KÊ KHAI HÀNG HÓA XUẤT KHẨU ĐẠT TIÊU CHÍ "CTC" (CTH)', "default_threshold": ""},
    {"sheet": "CTSH", "title": 'BẢNG KÊ KHAI HÀNG HÓA XUẤT KHẨU ĐẠT TIÊU CHÍ "CTC" (CTSH)', "default_threshold": ""},
    {"sheet": "PSR", "title": 'BẢNG KÊ KHAI HÀNG HÓA XUẤT KHẨU ĐẠT TIÊU CHÍ "PSR"', "default_threshold": ""},
    {"sheet": "EUR1", "title": 'BẢNG KÊ KHAI HÀNG HÓA XUẤT KHẨU ĐẠT TIÊU CHÍ "PSR" (EUR.1)', "default_threshold": ""},
]
HQ_LEGAL_NOTE = "Ban hành kèm theo Thông tư 05/2018/TT-BCT (sửa đổi 44/2023/TT-BCT, 23/2025/TT-BCT)."
HQ_HEADERS = [
    "STT", "Tên nguyên phụ liệu", "HS", "ĐVT", "Định mức/SP", "SL cần cho lô",
    "Đơn giá CIF", "Trị giá xuất xứ", "Trị giá KXX", "Nước xuất xứ",
    "Tờ khai NK / VAT", "Ngày", "C/O / khai báo", "Ngày",
]
HQ_BODY_START = 16
HQ_BODY_END = 1585

# Per-sheet layout descriptors. The "legacy" layout matches CTH/CTSH/RVC/PSR/EUR1
# (cols A-N data + O-Y helpers, body to row 1585, footer 1586-1611).
# The "lvc" layout matches the compact LVC template (cols A-N, body to row 437,
# template-owned summary block at 438+, conclusion at B463).
_HQ_LEGACY_LAYOUT = {
    "kind": "legacy",
    "body_end": 1585,
    "helper_cols": range(15, 26),
    "cols": {
        "stt": 1, "name": 2, "hs": 3, "uom": 4, "norm": 5, "qty": 6,
        "unit_price": 7, "origin_val": 8, "non_origin_val": 9, "country": 10,
        "imp_no": 11, "imp_date": 12, "co_no": 13, "co_date": 14,
        "line_no": 15, "mat_code": 16, "col_q": 17, "col_s": 19,
        "prod_code": 23, "src_line": 24, "qty_y": 25,
    },
}
_HQ_LVC_LAYOUT = {
    "kind": "lvc",
    "body_end": 437,
    "helper_cols": [],
    "cols": {
        "stt": 1, "name": 2, "mat_code": 3, "hs": 4, "uom": 5, "norm": 6,
        "unit_price": 7, "origin_val": 8, "non_origin_val": 9, "country": 10,
        "imp_no": 11, "imp_date": 12, "co_no": 13, "co_date": 14,
    },
}


def _hq_layout_for(sheet_code: str) -> dict:
    return _HQ_LVC_LAYOUT if sheet_code == "LVC" else _HQ_LEGACY_LAYOUT


def hq_sheet_codes_for_product(product: dict) -> set[str]:
    """Pick the ONE HQ template sheet this TP should use.

    Per legacy macro flow and user requirement: 1 sheet per TP per dossier.
    Priority within a single source: LVC > RVC > CTSH > CTH (PSR/EUR1 by form).
    Returns a set of size 1 (set type kept for caller convenience).

    Source priority — use the FIRST non-empty source, don't merge:
      1. `origin_sheet_criteria_override` — operator's explicit choice via the
         config bar. Authoritative; never override this with anything else.
      2. `documented_result` — operator's persisted criterion saved on the
         product record (typically what they originally documented).
      3. `origin_sheet_effective_criteria_text` — engine recommendation (only
         used when neither override nor documented result is set).
      4. `origin_criterion_mode` — coarse mode (legacy fallback).

    Why not merge: if documented_result = "LVC 30% hoặc CTH" and operator
    overrides to "CTH", merging keeps "LVC" in the search string and ships the
    wrong template. With the precedence chain, the override wins by virtue of
    being checked first.

    Form-driven fallback (EUR.1 → PSR/Phụ lục VII) only applies when no
    criterion above matches — explicit overrides (LVC/CTH/...) always win,
    even for EVFTA cases.
    """
    form = str(product.get("origin_sheet_effective_form_code") or "").upper()
    is_eur1 = form == "EUR.1" or "EUR.1" in form
    primary_criterion = ""
    for key in (
        "origin_sheet_criteria_override",
        "documented_result",
        "origin_sheet_effective_criteria_text",
        "origin_criterion_mode",
    ):
        candidate = str(product.get(key) or "").strip()
        if candidate:
            primary_criterion = candidate.upper()
            break
    if "PSR" in primary_criterion:
        return {"PSR"}
    # For "LVC 30% hoặc CTH"-style alternatives, prefer LVC > RVC > CTSH > CTH.
    # Operator overrides to a single criterion get the matched sheet directly.
    if "LVC" in primary_criterion:
        return {"LVC"}
    if "RVC" in primary_criterion or "MAXNOM" in primary_criterion:
        return {"RVC"}
    if "CTSH" in primary_criterion:
        return {"CTSH"}
    if "CTH" in primary_criterion:
        return {"CTH"}
    # No specific criterion matched. EVFTA defaults to PSR (Phụ lục VII);
    # everything else falls back to LVC for backward compat.
    return {"EUR1"} if is_eur1 else {"LVC"}


def write_hq_sheet_header(ws, product: dict, sheet_def: dict, case: dict, threshold: str) -> None:
    ws["E2"] = "Phụ lục VII"
    ws["A3"] = sheet_def["title"]
    ws["A4"] = HQ_LEGAL_NOTE
    ws["B6"] = case.get("customer", "") or case.get("client_id", "")
    ws["K6"] = product.get("origin_sheet_effective_criteria_text") or product.get("documented_result", "")
    ws["K7"] = product.get("name", "")
    ws["P7"] = product.get("code", "")
    ws["K8"] = product.get("finished_hs", "")
    ws["O8"] = product.get("incoterm", "FOB")
    ws["P8"] = product.get("fob", "") or "0"
    ws["K9"] = product.get("quantity", "") or "0"
    ws["L9"] = product.get("uom") or product.get("unit") or product.get("export_unit", "")
    ws["P9"] = product.get("quantity", "") or "0"
    ws["Q9"] = (case.get("shipment", {}).get("export_declaration_nos") or [""])[0]
    ws["K10"] = product.get("fob", "") or "0"
    ws["K11"] = product.get("fob", "") or "0"
    for col_index, label in enumerate(HQ_HEADERS, start=1):
        ws.cell(row=12, column=col_index, value=label)
    ws["O5"] = "Ngưỡng (%)"
    ws["P5"] = threshold


def write_hq_template_sheet_header(ws, product: dict, sheet_def: dict, case: dict, threshold: str) -> None:
    """Fill input cells on a copied `tru lui CO` template sheet.

    The template already owns titles, merged table headers, row heights,
    formulas, and print setup. Keep those intact and only replace the cells
    the legacy macro treated as output values.
    """
    merchant = (
        case.get("customer_legal_name")
        or case.get("customer", "")
        or case.get("client_name", "")
        or case.get("client_id", "")
    )
    tax_code = case.get("customer_tax_code", "") or case.get("client_tax_code", "")
    quantity = decimal_value(product.get("quantity") or "0")
    _mode_for_fob = (product.get("origin_sheet_currency_mode") or "native").strip().lower()
    _fob_source = product.get("fob_vnd") if _mode_for_fob == "vnd" and product.get("fob_vnd") else product.get("fob")
    fob = decimal_value(_fob_source or "0")
    unit_price = fob / quantity if quantity else fob
    declaration_no = product.get("source_declaration_no") or first_non_empty(case.get("shipment", {}).get("export_declaration_nos") or [])
    declaration_date = product.get("source_declaration_date") or product.get("export_declaration_date") or ""
    criterion = product.get("origin_sheet_effective_criteria_text") or product.get("documented_result", "") or sheet_def["sheet"]
    if threshold and sheet_def["sheet"] in {"LVC", "RVC"} and "%" not in str(criterion):
        criterion = f"{sheet_def['sheet']} {threshold}%"
    material_count = count_hq_material_rows(product)

    sheet_code = sheet_def["sheet"]
    uom = product.get("uom") or product.get("unit") or product.get("export_unit", "")
    currency_mode = (product.get("origin_sheet_currency_mode") or "native").strip().lower()
    from app.bang_ke_renderer import _resolve_target_currency
    currency = _resolve_target_currency(product, currency_mode == "vnd")
    if sheet_code == "LVC":
        # Compact LVC layout (Phụ lục VII, form-mau-combined): K-N header cells.
        ws["B6"] = f"Tên Thương nhân: {merchant}" if merchant else "Tên Thương nhân: "
        ws["B7"] = f"Mã số thuế : {tax_code}" if tax_code else "Mã số thuế : "
        if declaration_no:
            ws["B8"] = f"Tờ khai: {declaration_no} ngày {declaration_date}".strip()
        ws["K6"] = f"Tiêu chí áp dụng: {criterion}"
        ws["L7"] = product.get("name", "")
        ws["K8"] = f"Mã HS của hàng hóa (6 số) : {product.get('finished_hs', '')}"
        ws["L9"] = quantity
        ws["N9"] = uom
        ws["L10"] = fob
        if currency:
            ws["H13"] = f"Trị giá ({currency})"
        return
    # Legacy wide layout (CTH/CTSH/RVC/PSR) — preserves Mã LH / Tỷ giá / helper cols.
    ws["B6"] = f"Tên Thương nhân: {merchant}" if merchant else "Tên Thương nhân: "
    ws["B7"] = f"Mã số thuế: {tax_code}" if tax_code else "Mã số thuế: "
    ws["K6"] = criterion
    ws["K7"] = product.get("name", "")
    ws["P7"] = product.get("code", "")
    ws["K8"] = product.get("finished_hs", "")
    ws["O8"] = product.get("incoterm", "FOB") or "FOB"
    ws["P8"] = unit_price
    if declaration_no:
        ws["B9"] = f"{declaration_no} Ngày {declaration_date}".strip()
    ws["K9"] = quantity
    ws["L9"] = uom
    ws["P9"] = quantity
    ws["Q9"] = declaration_no
    ws["K10"] = fob
    ws["K11"] = fob
    # Template hardcodes "USD" at L10/L11 + "(USD)" in H13 header. Overwrite
    # with the product's actual currency so the bảng kê HQ never mismatches.
    if currency:
        ws["L10"] = currency
        ws["L11"] = currency
        ws["H13"] = f"Trị giá ({currency})"
    ws["P5"] = material_count
    # PSR template carries Trị giá xuất xưởng / Phí B/L+THC / Phí vận chuyển
    # labels at M9/M10/M11 in the source template; we don't compute the
    # breakdown yet, so leave those header cells to whatever the template ships.


def count_hq_material_rows(product: dict) -> int:
    materials = product.get("materials") or []
    overrides = product.get("origin_sheet_material_overrides") or {}
    count = 0
    for index, _material in enumerate(materials):
        override = overrides.get(str(index)) if isinstance(overrides.get(str(index)), dict) else {}
        if not override.get("deleted"):
            count += 1
    count += sum(
        1
        for key, value in overrides.items()
        if key.startswith("added_") and isinstance(value, dict) and not value.get("deleted")
    )
    return count


def first_non_empty(values) -> str:
    for value in values or []:
        text = cell_text(value)
        if text:
            return text
    return ""


def write_hq_sheet_materials(ws, product: dict, start_row: int, *, legacy_export_layout: bool = False, sheet_code: str = "") -> int:
    layout = _hq_layout_for(sheet_code)
    cols = layout["cols"]
    materials = product.get("materials") or []
    overrides = product.get("origin_sheet_material_overrides") or {}
    row_index = start_row
    counter = 1
    sum_origin = Decimal("0")
    sum_non_origin = Decimal("0")

    def put(row: int, key: str, value) -> None:
        col = cols.get(key)
        if not col:
            return
        ws.cell(row=row, column=col, value=value)

    for index, material in enumerate(materials):
        override = overrides.get(str(index)) if isinstance(overrides.get(str(index)), dict) else {}
        if override.get("deleted"):
            continue
        material_code = override.get("material_code") or material.get("material_code", "")
        material_name = override.get("name") or material.get("material_description", "")
        norm = override.get("norm_per_unit") or material.get("bom_qty_per", "0")
        required_qty = decimal_value(material.get("consumed_qty") or norm)
        unit_price = decimal_value(material.get("unit_value") or "0")
        material_value = decimal_value(material.get("material_value") or "0")
        origin_status = str(material.get("origin_status") or "non_origin")
        origin_value = material_value if origin_status == "origin" else Decimal("0")
        non_origin_value = material_value if origin_status != "origin" else Decimal("0")
        sum_origin += origin_value
        sum_non_origin += non_origin_value

        put(row_index, "stt", counter)
        put(row_index, "name", material_name)
        put(row_index, "mat_code", material_code)
        put(row_index, "hs", material.get("hs_code", ""))
        put(row_index, "uom", material.get("uom", ""))
        put(row_index, "norm", str(norm))
        put(row_index, "qty", str(required_qty))
        put(row_index, "unit_price", str(unit_price))
        put(row_index, "origin_val", str(origin_value))
        put(row_index, "non_origin_val", str(non_origin_value))
        put(row_index, "country", material.get("origin_country", ""))
        put(row_index, "imp_no", material.get("import_declaration_no", ""))
        put(
            row_index,
            "imp_date",
            material.get("import_declaration_date")
            or material.get("declaration_date")
            or material.get("registration_date")
            or "",
        )
        put(row_index, "co_no", material.get("source_document_ref", ""))
        put(row_index, "co_date", material.get("source_document_date", ""))
        # Legacy helper columns — only meaningful on the wide layout.
        if layout["kind"] == "legacy":
            put(row_index, "line_no", material.get("import_line_no", ""))
            put(row_index, "col_q", f"{product.get('source_declaration_no', '')}{material_code}")
            put(row_index, "col_s", material.get("import_declaration_type", ""))
            put(row_index, "prod_code", product.get("code", ""))
            put(row_index, "src_line", product.get("source_line_no", ""))
            put(row_index, "qty_y", product.get("quantity", ""))
        row_index += 1
        counter += 1

    # Added-rows from overrides go at the end.
    for key, value in overrides.items():
        if not key.startswith("added_") or not isinstance(value, dict):
            continue
        put(row_index, "stt", counter)
        put(row_index, "name", value.get("name", ""))
        put(row_index, "mat_code", value.get("material_code", ""))
        put(row_index, "hs", value.get("hs_code", ""))
        put(row_index, "uom", value.get("uom", ""))
        put(row_index, "norm", str(value.get("norm_per_unit", "0")))
        if layout["kind"] == "legacy":
            put(row_index, "prod_code", product.get("code", ""))
        row_index += 1
        counter += 1

    fob = decimal_value(product.get("fob") or "0")
    if layout["kind"] == "legacy":
        # Footer totals at fixed positions per docs/legacy-workbook-output-sheet-structure.md
        ws["C1586"] = str(sum_origin)
        ws["C1587"] = str(sum_non_origin)
        ws["H1588"] = str(sum_origin)
        ws["I1588"] = str(sum_non_origin)
        if fob > 0:
            lvc_ratio = ((fob - sum_non_origin) / fob).quantize(Decimal("0.0001"))
            lvc_percent = (lvc_ratio * Decimal("100")).quantize(Decimal("0.01"))
            ws["K1606"] = str(sum_non_origin)
            ws["J1606"] = str(fob)
            ws["I1604"] = str(fob)
            ws["M1607"] = lvc_ratio
            if sheet_code in {"CTH", "CTSH"}:
                ws["B1611"] = f"Kết luận: Hàng hóa đáp ứng tiêu chí “{sheet_code}”"
            elif sheet_code == "RVC":
                ws["B1611"] = f"Kết luận: Hàng hóa đáp ứng tiêu chí RVC {lvc_percent} %"
            elif sheet_code in {"PSR", "EUR1"}:
                # FORM PSR carries an example "Tỷ lệ giá trị nguyên liệu sử dụng" string
                # in B1611 and its real conclusion at B1617 — clear the first and
                # set the second so stale example numbers don't show up.
                ws["B1611"] = None
                ws["B1617"] = "Kết luận: Hàng hóa đáp ứng tiêu chí PSR"
        if legacy_export_layout:
            hide_hq_unused_rows_and_helpers(ws, row_index)
    else:  # LVC compact layout — re-point the template's SUM ranges & conclusion.
        last_data_row = row_index - 1
        ws["H438"] = f"=SUM(H16:H{last_data_row})" if last_data_row >= HQ_BODY_START else 0
        ws["I438"] = f"=SUM(I16:I{last_data_row})" if last_data_row >= HQ_BODY_START else 0
        if fob > 0:
            lvc_ratio = ((fob - sum_non_origin) / fob).quantize(Decimal("0.0001"))
            lvc_percent = (lvc_ratio * Decimal("100")).quantize(Decimal("0.01"))
            ws["B463"] = f"Kết luận: Sản phẩm đạt tiêu chí LVC = {lvc_percent}%"
        # Hide the empty body rows between last data row and the summary block
        # so the print preview stays at 1-2 pages instead of paginating blanks.
        if legacy_export_layout:
            body_end = _HQ_LVC_LAYOUT["body_end"]
            for hide_row in range(max(row_index, HQ_BODY_START), body_end + 1):
                ws.row_dimensions[hide_row].hidden = True
    return row_index


HQ_FORM_MAU_COMBINED_PATH = Path(__file__).resolve().parent.parent / "data" / "local" / "hq-templates" / "form-mau-combined.xlsx"
HQ_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "data" / "local" / "hq-templates" / "tru-lui-co-output-template.xlsx"
HQ_LEGACY_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "data" / "local" / "hq-templates" / "tru-lui-co-template.xlsm"


def hq_template_path() -> Path | None:
    """Locate the bảng kê styling template.

    Preference order: the new 2026 FORM MAU combined workbook, then the legacy
    `tru lui CO` template, then the original .xlsm.
    """
    if HQ_FORM_MAU_COMBINED_PATH.exists():
        return HQ_FORM_MAU_COMBINED_PATH
    if HQ_TEMPLATE_PATH.exists():
        return HQ_TEMPLATE_PATH
    if HQ_LEGACY_TEMPLATE_PATH.exists():
        return HQ_LEGACY_TEMPLATE_PATH
    return None


def create_hq_bang_ke_workbook_xml(case: dict) -> bytes:
    """Render bảng kê via the XML-driven generator (approach A).

    Output is built from scratch using config/bang-ke-config.xml — no xlsx
    template is consulted. Consistent style across all criteria.

    The template-based path remains via `create_hq_bang_ke_workbook` for
    parallel evaluation.
    """
    def _criterion_for(product: dict) -> str:
        codes = hq_sheet_codes_for_product(product)
        for preferred in ("LVC", "RVC", "CTH", "CTSH", "PSR", "EUR1"):
            if preferred in codes:
                return "PSR" if preferred == "EUR1" else preferred
        return ""
    return render_case_via_xml(case, _criterion_for)


def create_hq_bang_ke_workbook(case: dict) -> bytes:
    """Build the HQ-style bảng kê workbook by cloning the legacy template per product.

    Follows the macro flow documented in
    docs/legacy-workbook-output-sheet-structure.md:
      - For each product, copy the relevant criterion sheet (LVC/RVC/CTH/CTSH/EUR1)
      - Fill header cells (A3 title preserved, K7/P7/P8/P9/Q9 etc.)
      - Write material rows starting at row 16
      - Footer totals at rows 1586-1607
      - Name the copied tab as `<sequence><product_code>` (per macro: `so & P7`)

    If the template file is not present, falls back to the structured shell builder
    from before (no styling parity).
    """
    template_path = hq_template_path()
    if template_path is None:
        return _create_hq_bang_ke_workbook_shell(case)
    wb = load_workbook(template_path, keep_vba=False)
    _sanitize_hq_template_workbook(wb)
    products = case.get("products") or []
    sheets_used: set[str] = set()
    created_sheet_titles: list[str] = []
    sequence = 0
    for product in products:
        codes = hq_sheet_codes_for_product(product)
        # EUR1 falls back to PSR in the form-mau template (same Phụ lục VII).
        if "EUR1" in codes and "EUR1" not in wb.sheetnames and "PSR" in wb.sheetnames:
            codes = {"PSR" if c == "EUR1" else c for c in codes}
        for sheet_def in HQ_SHEET_DEFS:
            if sheet_def["sheet"] not in codes:
                continue
            if sheet_def["sheet"] not in wb.sheetnames:
                continue
            template_ws = wb[sheet_def["sheet"]]
            sequence += 1
            new_title = _safe_sheet_title(f"{sequence}{product.get('code', '')}", wb)
            ws_copy = wb.copy_worksheet(template_ws)
            ws_copy.title = new_title
            created_sheet_titles.append(new_title)
            sheets_used.add(sheet_def["sheet"])
            threshold = product.get("origin_sheet_effective_lvc_threshold") or sheet_def["default_threshold"]
            if _render_via_config(ws_copy, sheet_def["sheet"], case, product, new_title):
                continue
            # Fallback to legacy hardcoded path for criteria without a config yet.
            _clear_template_body(ws_copy, sheet_code=sheet_def["sheet"])
            write_hq_template_sheet_header(ws_copy, product, sheet_def, case, threshold)
            write_hq_sheet_materials(ws_copy, product, HQ_BODY_START, legacy_export_layout=True, sheet_code=sheet_def["sheet"])
            # openpyxl's copy_worksheet drops print_area; re-apply with the new title.
            body_end = _hq_layout_for(sheet_def["sheet"])["body_end"]
            print_end_row = 1623 if body_end > 500 else 477
            ws_copy.print_area = f"'{new_title}'!$A$1:$N${print_end_row}"
    # Drop every sheet that wasn't created for this dossier — including all
    # template/source sheets which still hold the legacy workbook's example data.
    keep = set(created_sheet_titles)
    for name in list(wb.sheetnames):
        if name not in keep:
            del wb[name]
    if not wb.sheetnames:
        ws = wb.create_sheet("README")
        ws["A1"] = "Hồ sơ chưa có TP nào sẵn sàng để xuất bảng kê HQ."
    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


def _sanitize_hq_template_workbook(wb: Workbook) -> None:
    """Remove legacy workbook links/names that can make Excel reject the XLSX."""
    wb._external_links = []
    wb.defined_names.clear()
    for ws in wb.worksheets:
        ws.defined_names.clear()
    wb.code_name = None


def _safe_sheet_title(name: str, wb: Workbook) -> str:
    cleaned = "".join(c for c in name if c not in "[]:*?/\\")[:31] or "Sheet"
    if cleaned not in wb.sheetnames:
        return cleaned
    suffix = 1
    while f"{cleaned[:28]}_{suffix}" in wb.sheetnames:
        suffix += 1
    return f"{cleaned[:28]}_{suffix}"


def _clear_template_body(ws, sheet_code: str = "") -> None:
    """Wipe the example body rows from the template so we can re-fill cleanly.

    LVC uses the compact layout (body to ~row 437, no helper cols). All other
    criteria use the wide legacy layout (body to row 1585, helper cols O-Y).
    """
    layout = _hq_layout_for(sheet_code)
    body_end = layout["body_end"]
    max_clear_col = 14 if layout["kind"] == "lvc" else 27
    for row_index in range(HQ_BODY_START, body_end + 1):
        ws.row_dimensions[row_index].hidden = False
    for col_index in layout["helper_cols"]:
        ws.column_dimensions[get_column_letter(col_index)].hidden = False
    for row in ws.iter_rows(min_row=HQ_BODY_START, max_row=body_end, max_col=max_clear_col):
        for cell in row:
            cell.value = None
    if layout["kind"] == "lvc":
        _clear_lvc_template_example_data(ws)
    else:
        _clear_legacy_summary_example_data(ws)


def _clear_lvc_template_example_data(ws) -> None:
    """Wipe the example labor / overhead / freight / signature values that
    ship in FORM LVC.xlsx so they don't bleed into a fresh export.

    The LVC template carries a fully-worked example case beyond the body
    table (rows 438-476): labor wages, factory rent, depreciation, freight,
    plus a hard-coded city + date on the signature line. Those numbers and
    the date must be cleared — actual labor/overhead/freight inputs need to
    come from the user's case data once we model them.
    """
    # I440-I446 + J440-J446: labor and overhead absolute values + percent of FOB.
    # NB: ws.cell(row, col, value=None) is a no-op in openpyxl — `value=None`
    # means "don't update". Set .value explicitly to clear.
    for row_index in (440, 441, 444, 445, 446):
        ws.cell(row=row_index, column=9).value = None   # I
        ws.cell(row=row_index, column=10).value = None  # J
    # Freight + other (I454, J454).
    ws["I454"].value = None
    ws["J454"].value = None
    # Signature city + date stamped in the template.
    ws["K466"].value = None


def _clear_legacy_summary_example_data(ws) -> None:
    """Wipe example labor / overhead / cost-buildup values shipped with the
    FORM CTH/RVC/PSR templates at rows 1589-1609.

    The CTH/RVC/PSR templates each carry a fully-worked example case below
    the body table — labor wages at I1590/I1591, overhead at I1595-I1597,
    chi phí xuất xưởng / lợi nhuận / giá xuất xưởng / các chi phí khác at
    I1600-I1603 and FOB shadows at J1609. They confuse output because they
    look like real numbers. Clear them — actual cost-buildup inputs need to
    come from the user's case data once we model them.
    """
    for cell_address in (
        "I1590", "I1591", "I1593",          # Chi phí nhân công + Tổng II
        "I1595", "I1596", "I1597", "I1599", # Chi phí phân bổ + Tổng III
        "I1600", "I1601", "I1602", "I1603", # IV/V/VI/VII totals
        "J1609",                              # shadow FOB used by ratio formula
    ):
        ws[cell_address].value = None


def hide_hq_unused_rows_and_helpers(ws, first_blank_row: int) -> None:
    for row_index in range(max(first_blank_row, HQ_BODY_START), HQ_BODY_END + 1):
        ws.row_dimensions[row_index].hidden = True
    for col_index in range(15, 26):
        ws.column_dimensions[get_column_letter(col_index)].hidden = True
    ws.print_area = "A1:N1623"


def _create_hq_bang_ke_workbook_shell(case: dict) -> bytes:
    """Fallback builder when the legacy template isn't present."""
    wb = Workbook()
    wb.remove(wb.active)
    products = case.get("products") or []
    for sheet_def in HQ_SHEET_DEFS:
        ws = wb.create_sheet(sheet_def["sheet"])
        ws.page_setup.orientation = "landscape"
        ws.print_options.horizontalCentered = True
        ws.print_area = "A1:N1623"
        relevant = [p for p in products if sheet_def["sheet"] in hq_sheet_codes_for_product(p)]
        row = HQ_BODY_START
        for product in relevant:
            threshold = product.get("origin_sheet_effective_lvc_threshold") or sheet_def["default_threshold"]
            write_hq_sheet_header(ws, product, sheet_def, case, threshold)
            row = write_hq_sheet_materials(ws, product, row)
            row += 1
            if row >= HQ_BODY_END:
                break
        if not relevant:
            ws["A3"] = sheet_def["title"]
            ws["A6"] = "Không có TP nào áp dụng tiêu chí này."
    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


def create_dossier_zip(
    case: dict,
    supporting_files: list[dict],
    tkx_tkn_summary: dict,
    *,
    data_hub_base_url: str = "",
    declaration_archives: dict[str, bytes] | None = None,
) -> bytes:
    """Bundle the full C/O dossier into a single .zip an operator can hand
    straight to HQ.

    Layout (numbered prefixes drive Windows Explorer sort order):
        00-README.md                            — Vietnamese cover doc.
        01-bang-ke/{case_code}-bang-ke-HQ.xlsx
        02-chung-tu/{NN}-{slot}-{original}      — supporting files from step 2,
                                                  numbered + slot-tagged so the
                                                  HQ reviewer sees groups
                                                  (BL, Invoice, Packing, ...).
        03-to-khai/MANIFEST.md                  — list of every TKX/TKN with
                                                  Data Hub download URLs (until
                                                  the Bearer-aware download API
                                                  ships per .ai/api-requests/
                                                  2026-05-28-bcct-declarations-
                                                  download-bearer.md).
        03-to-khai/{direction}/{filename}       — actual blobs when
                                                  declaration_archives carries
                                                  pre-fetched bytes (future).
    """
    import zipfile
    case_code = (case.get("case_code") or "co-case").strip() or "co-case"
    archives = declaration_archives or {}
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "00-README.md",
            build_dossier_readme(case, tkx_tkn_summary, embedded_declaration_archives=bool(archives)),
        )
        zf.writestr(
            f"01-bang-ke/{case_code}-bang-ke-HQ.xlsx",
            create_hq_bang_ke_workbook(case),
        )
        for index, file in enumerate(supporting_files or [], start=1):
            content = file.get("content")
            if not isinstance(content, (bytes, bytearray)):
                continue
            slot = _slugify(file.get("slot") or "other")
            original = (file.get("filename") or "supporting.bin").strip() or "supporting.bin"
            archive_name = f"02-chung-tu/{index:02d}-{slot}-{original}"
            zf.writestr(archive_name, bytes(content))
        zf.writestr(
            "03-to-khai/MANIFEST.md",
            _build_declarations_manifest(
                case, tkx_tkn_summary, data_hub_base_url,
                embedded=bool(archives),
            ),
        )
        for archive_path, blob in archives.items():
            if isinstance(blob, (bytes, bytearray)):
                zf.writestr(f"03-to-khai/{archive_path}", bytes(blob))
    return stream.getvalue()


def _slugify(text: str) -> str:
    import re
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", str(text or "").strip().lower()).strip("-")
    return cleaned or "other"


def _build_declarations_manifest(
    case: dict,
    summary: dict,
    data_hub_base_url: str,
    *,
    embedded: bool = False,
) -> str:
    from urllib.parse import quote
    case_code = case.get("case_code") or case.get("id") or "co-case"
    client_id = case.get("client_id") or ""
    if embedded:
        intro = [
            "Danh sách TKX (xuất) và TKN (nhập) tham chiếu trong hồ sơ.",
            "Bộ file tờ khai thực đã được nhúng trong thư mục `03-to-khai/TKX/`",
            "và `03-to-khai/TKN/`. Bảng kê dưới đây để đối chiếu nhanh.",
        ]
    else:
        intro = [
            "Danh sách TKX (xuất) và TKN (nhập) được hồ sơ tham chiếu. Bộ file tờ khai",
            "chưa được nhúng trực tiếp vào ZIP — bấm các link dưới để tải về từ Data Hub",
            "(yêu cầu đã đăng nhập Data Hub trong cùng browser).",
        ]
    lines = [
        f"# Tờ khai tham chiếu — hồ sơ {case_code}",
        "",
        *intro,
        "",
    ]

    def _block(title: str, entries: list[dict], direction: str) -> list[str]:
        out = [f"## {title} ({len(entries)})", ""]
        if not entries:
            out.append("_Không có tờ khai nào._")
            out.append("")
            return out
        nos = [str(entry.get("declaration_no") or "").strip() for entry in entries if entry.get("declaration_no")]
        if data_hub_base_url and nos and client_id:
            link_filename = quote(f"{direction.upper()}_{case_code}.zip")
            url = (
                f"{data_hub_base_url}/clients/{client_id}/declarations/download.zip"
                f"?direction={direction}&declaration_nos={quote(','.join(nos))}"
                f"&filename={link_filename}"
            )
            out.append(f"Tải nhanh toàn bộ {direction.upper()}: [{link_filename}]({url})")
            out.append("")
        for entry in entries:
            decl_no = entry.get("declaration_no") or "?"
            file_count = entry.get("file_count") or 0
            present = "✅" if file_count > 0 else "⚠️"
            out.append(f"- {present} **{decl_no}** — file đã upload: {file_count}")
        out.append("")
        return out

    lines += _block("TKX (xuất khẩu)", summary.get("tkx") or [], "export")
    lines += _block("TKN (nhập khẩu)", summary.get("tkn") or [], "import")
    missing_tkx = summary.get("missing_tkx") or []
    missing_tkn = summary.get("missing_tkn") or []
    if missing_tkx or missing_tkn:
        lines.append("## Còn thiếu")
        lines.append("")
        for entry in missing_tkx:
            lines.append(f"- TKX **{entry.get('declaration_no', '?')}** — chưa có file trên Data Hub.")
        for entry in missing_tkn:
            lines.append(f"- TKN **{entry.get('declaration_no', '?')}** — chưa có file trên Data Hub.")
    return "\n".join(lines)


def build_dossier_readme(
    case: dict,
    tkx_tkn_summary: dict | None = None,
    *,
    embedded_declaration_archives: bool = False,
) -> str:
    summary = tkx_tkn_summary or {}
    tkx_count = len(summary.get("tkx") or [])
    tkn_count = len(summary.get("tkn") or [])
    missing = len(summary.get("missing_tkx") or []) + len(summary.get("missing_tkn") or [])
    declaration_section = (
        "- `03-to-khai/TKX/…zip`, `03-to-khai/TKN/…zip` — File tờ khai đã nhúng sẵn."
        if embedded_declaration_archives
        else "- `03-to-khai/<direction>/…` — File tờ khai (sẽ tự nhúng khi Data Hub bật endpoint Bearer-aware)."
    )
    lines = [
        f"# Hồ sơ C/O — {case.get('case_code', '')}",
        "",
        f"- Khách hàng: **{case.get('customer_legal_name') or case.get('customer') or case.get('client_id', '')}**",
        f"- MST: {case.get('customer_tax_code') or '—'}",
        f"- Thị trường: {case.get('destination_market', '')}",
        f"- Số TP: {len(case.get('products') or [])}",
        f"- TKX/TKN: {tkx_count}/{tkn_count}" + (f" — còn thiếu **{missing}**" if missing else ""),
        "",
        "## Cấu trúc thư mục",
        "",
        "- `01-bang-ke/…-bang-ke-HQ.xlsx` — Bảng kê C/O theo template HQ.",
        "- `02-chung-tu/NN-<slot>-<tên file>` — Chứng từ upload ở bước 2 (BL, Invoice, Packing, …) đã đánh số.",
        "- `03-to-khai/MANIFEST.md` — Danh sách TKX/TKN + link Data Hub để tải file tờ khai.",
        declaration_section,
        "",
        "## Lưu ý",
        "",
        "Bảng kê HQ render từ JSON config `config/bang-ke-forms/*.json` + template",
        "`data/local/hq-templates/form-mau-combined.xlsx`. Khi tham chiếu lại để rà soát,",
        "đối chiếu cell theo số dòng nguyên gốc của form (cell K6 = tiêu chí, K8 = HS, …).",
    ]
    return "\n".join(lines)
