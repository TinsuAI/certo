from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook

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
