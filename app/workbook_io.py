from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter

from app.demo_data import attach_results, get_demo_case

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
    {"sheet": "LVC", "title": 'BẢNG KÊ KHAI HÀNG HÓA XUẤT KHẨU ĐẠT TIÊU CHÍ "LVC"', "default_threshold": "30"},
    {"sheet": "RVC", "title": 'BẢNG KÊ KHAI HÀNG HÓA XUẤT KHẨU ĐẠT TIÊU CHÍ "RVC"', "default_threshold": "40"},
    {"sheet": "CTH", "title": 'BẢNG KÊ KHAI HÀNG HÓA XUẤT KHẨU ĐẠT TIÊU CHÍ "CTC" (CTH)', "default_threshold": ""},
    {"sheet": "CTSH", "title": 'BẢNG KÊ KHAI HÀNG HÓA XUẤT KHẨU ĐẠT TIÊU CHÍ "CTC" (CTSH)', "default_threshold": ""},
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


def hq_sheet_codes_for_product(product: dict) -> set[str]:
    """Pick the ONE HQ template sheet this TP should use.

    Per legacy macro flow and user requirement: 1 sheet per TP per dossier.
    Priority: LVC > RVC > CTSH > CTH > EUR1, narrowed by the TP's effective
    criteria text. Returns a set of size 1 (set type kept for caller convenience).
    """
    form = str(product.get("origin_sheet_effective_form_code") or "").upper()
    criteria_sources = [
        product.get("origin_sheet_effective_criteria_text") or "",
        product.get("documented_result") or "",
        product.get("origin_criterion_mode") or "",
    ]
    criteria = " ".join(str(c) for c in criteria_sources).upper()
    if form == "EUR.1" or "EUR.1" in form or "PSR" in criteria:
        return {"EUR1"}
    if "LVC" in criteria:
        return {"LVC"}
    if "RVC" in criteria or "MAXNOM" in criteria:
        return {"RVC"}
    if "CTSH" in criteria:
        return {"CTSH"}
    if "CTH" in criteria:
        return {"CTH"}
    return {"LVC"}


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
    merchant = case.get("customer", "") or case.get("client_name", "") or case.get("client_id", "")
    tax_code = case.get("customer_tax_code", "") or case.get("client_tax_code", "")
    quantity = decimal_value(product.get("quantity") or "0")
    fob = decimal_value(product.get("fob") or "0")
    unit_price = fob / quantity if quantity else fob
    declaration_no = product.get("source_declaration_no") or first_non_empty(case.get("shipment", {}).get("export_declaration_nos") or [])
    declaration_date = product.get("source_declaration_date") or product.get("export_declaration_date") or ""
    criterion = product.get("origin_sheet_effective_criteria_text") or product.get("documented_result", "") or sheet_def["sheet"]
    if threshold and sheet_def["sheet"] in {"LVC", "RVC"} and "%" not in str(criterion):
        criterion = f"{sheet_def['sheet']} {threshold}%"
    material_count = count_hq_material_rows(product)

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
    ws["L9"] = product.get("uom") or product.get("unit") or product.get("export_unit", "")
    ws["P9"] = quantity
    ws["Q9"] = declaration_no
    ws["K10"] = fob
    ws["K11"] = fob
    ws["P5"] = material_count


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
    materials = product.get("materials") or []
    overrides = product.get("origin_sheet_material_overrides") or {}
    row_index = start_row
    counter = 1
    sum_origin = Decimal("0")
    sum_non_origin = Decimal("0")
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
        ws.cell(row=row_index, column=1, value=counter)
        ws.cell(row=row_index, column=2, value=material_name)
        ws.cell(row=row_index, column=3, value=material.get("hs_code", ""))
        ws.cell(row=row_index, column=4, value=material.get("uom", ""))
        ws.cell(row=row_index, column=5, value=str(norm))
        ws.cell(row=row_index, column=6, value=str(required_qty))
        ws.cell(row=row_index, column=7, value=str(unit_price))
        ws.cell(row=row_index, column=8, value=str(origin_value))
        ws.cell(row=row_index, column=9, value=str(non_origin_value))
        ws.cell(row=row_index, column=10, value=material.get("origin_country", ""))
        ws.cell(row=row_index, column=11, value=material.get("import_declaration_no", ""))
        ws.cell(row=row_index, column=12, value=material.get("import_declaration_date", ""))
        ws.cell(row=row_index, column=13, value=material.get("source_document_ref", ""))
        ws.cell(row=row_index, column=14, value=material.get("source_document_date", ""))
        # Helper columns (preserved per legacy macro layout, hidden in print).
        ws.cell(row=row_index, column=15, value=material.get("import_line_no", ""))  # O
        ws.cell(row=row_index, column=16, value=material_code)  # P
        ws.cell(row=row_index, column=17, value=f"{product.get('source_declaration_no', '')}{material_code}")  # Q
        ws.cell(row=row_index, column=19, value=material.get("import_declaration_type", ""))  # S
        ws.cell(row=row_index, column=23, value=product.get("code", ""))  # W
        ws.cell(row=row_index, column=24, value=product.get("source_line_no", ""))  # X
        ws.cell(row=row_index, column=25, value=product.get("quantity", ""))  # Y
        row_index += 1
        counter += 1
    # Add added-rows from overrides at the end.
    for key, value in overrides.items():
        if not key.startswith("added_") or not isinstance(value, dict):
            continue
        ws.cell(row=row_index, column=1, value=counter)
        ws.cell(row=row_index, column=2, value=value.get("name", ""))
        ws.cell(row=row_index, column=3, value=value.get("hs_code", ""))
        ws.cell(row=row_index, column=4, value=value.get("uom", ""))
        ws.cell(row=row_index, column=5, value=str(value.get("norm_per_unit", "0")))
        ws.cell(row=row_index, column=16, value=value.get("material_code", ""))
        ws.cell(row=row_index, column=23, value=product.get("code", ""))
        row_index += 1
        counter += 1
    # Footer totals at fixed positions per docs/legacy-workbook-output-sheet-structure.md
    ws["C1586"] = str(sum_origin)
    ws["C1587"] = str(sum_non_origin)
    ws["H1588"] = str(sum_origin)
    ws["I1588"] = str(sum_non_origin)
    fob = decimal_value(product.get("fob") or "0")
    if fob > 0:
        lvc_ratio = ((fob - sum_non_origin) / fob).quantize(Decimal("0.0001"))
        lvc_percent = (lvc_ratio * Decimal("100")).quantize(Decimal("0.01"))
        ws["K1606"] = str(sum_non_origin)
        ws["J1606"] = str(fob)
        ws["I1604"] = str(fob)
        ws["M1607"] = lvc_ratio
        if sheet_code in {"CTH", "CTSH"}:
            ws["B1611"] = f"Kết luận: Hàng hóa đáp ứng tiêu chí “{sheet_code}”"
        elif sheet_code in {"LVC", "RVC"}:
            ws["B1611"] = f"Kết luận: Hàng hóa đáp ứng tiêu chí {sheet_code} {lvc_percent} %"
    if legacy_export_layout:
        hide_hq_unused_rows_and_helpers(ws, row_index)
    return row_index


HQ_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "data" / "local" / "hq-templates" / "tru-lui-co-output-template.xlsx"
HQ_LEGACY_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "data" / "local" / "hq-templates" / "tru-lui-co-template.xlsm"


def hq_template_path() -> Path | None:
    """Locate the legacy `tru lui CO` workbook used as styling template."""
    if HQ_TEMPLATE_PATH.exists():
        return HQ_TEMPLATE_PATH
    if HQ_LEGACY_TEMPLATE_PATH.exists():
        return HQ_LEGACY_TEMPLATE_PATH
    return None


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
            _clear_template_body(ws_copy)
            write_hq_template_sheet_header(ws_copy, product, sheet_def, case, threshold)
            write_hq_sheet_materials(ws_copy, product, HQ_BODY_START, legacy_export_layout=True, sheet_code=sheet_def["sheet"])
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


def _clear_template_body(ws) -> None:
    """Wipe the example body rows from the template so we can re-fill cleanly."""
    for row_index in range(HQ_BODY_START, HQ_BODY_END + 1):
        ws.row_dimensions[row_index].hidden = False
    for col_index in range(15, 26):
        ws.column_dimensions[get_column_letter(col_index)].hidden = False
    for row in ws.iter_rows(min_row=HQ_BODY_START, max_row=HQ_BODY_END, max_col=27):
        for cell in row:
            cell.value = None


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


def create_dossier_zip(case: dict, supporting_files: list[dict], tkx_tkn_summary: dict) -> bytes:
    """Bundle uploaded supporting files + TKX/TKN summary + HQ bảng kê into one .zip."""
    import json
    import zipfile
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", build_dossier_readme(case))
        zf.writestr("bang-ke-co-hq.xlsx", create_hq_bang_ke_workbook(case))
        zf.writestr("tkx-tkn.json", json.dumps(_serialise_tkx_tkn(tkx_tkn_summary), ensure_ascii=False, indent=2))
        for file in supporting_files or []:
            content = file.get("content")
            if not isinstance(content, (bytes, bytearray)):
                continue
            slot = str(file.get("slot") or "other").strip() or "other"
            filename = str(file.get("filename") or "supporting.bin").strip() or "supporting.bin"
            zf.writestr(f"chung-tu/{slot}/{filename}", bytes(content))
    return stream.getvalue()


def _serialise_tkx_tkn(summary: dict) -> dict:
    """Convert sets to lists so the TKX/TKN summary survives JSON round-trip."""
    cleaned: dict = {}
    for key, value in (summary or {}).items():
        if isinstance(value, list):
            cleaned[key] = [
                {**entry, "products": sorted(entry["products"]) if isinstance(entry.get("products"), set) else entry.get("products", [])}
                for entry in value
            ]
        else:
            cleaned[key] = value
    return cleaned


def build_dossier_readme(case: dict) -> str:
    lines = [
        f"Hồ sơ C/O: {case.get('case_code', '')}",
        f"Khách hàng: {case.get('customer', '') or case.get('client_id', '')}",
        f"Thị trường: {case.get('destination_market', '')}",
        f"Số TP: {len(case.get('products') or [])}",
        "",
        "Cấu trúc thư mục:",
        "  bang-ke-co-hq.xlsx — Bảng kê C/O theo template HQ (LVC/RVC/CTH/CTSH/EUR1)",
        "  tkx-tkn.json       — Danh sách TKX và TKN tham chiếu trong hồ sơ",
        "  chung-tu/<slot>/   — Các chứng từ đã upload theo tab Chứng từ",
        "",
        "Lưu ý: bảng kê HQ được build từ template tham chiếu trong",
        "docs/legacy-workbook-output-sheet-structure.md. Khi file .xlsm",
        "gốc 'tru lui CO final ...' được nạp vào repo, builder cần đọc",
        "template đó trực tiếp để giữ đúng styling/format gốc.",
    ]
    return "\n".join(lines)
