from __future__ import annotations

from decimal import Decimal

from app.origin import evaluate_rvc_ctsh


SOURCE_NOTES = [
    "docs/origin-qualification-case-studies.md ghi nhận model PV00.0048500 đạt RVC 35.88% + CTSH.",
    "docs/origin-qualification-case-studies.md ghi nhận model PV01.0117600 đạt RVC 40.19% + CTSH.",
    "docs/co-input-output-model.md ghi nhận bộ chứng từ Growatt gồm TKX, BL, INV + PBO, bảng RVC, và quy trình sản xuất.",
    "docs/customs-and-code-taxonomy.md cảnh báo Growatt thật thường có lệch mã HQ và mã nội bộ.",
]

CLIENTS = [
    {
        "id": "growatt",
        "name": "Growatt",
        "code": "GROWATT",
        "status": "active",
        "tax_code": "Chưa nhập",
        "contact": "CO operations",
        "module_status": {
            "materials": "seeded",
            "products": "seeded",
            "bom": "seeded",
            "co_stock": "seeded",
            "bcct": "seeded",
            "co_cases": "active",
        },
        "bom_source_profile": {
            "kind": "Growatt multi-workbook technical BOM graph",
            "summary": "2025 cross-workbook flatten: 9 priority TP codes, 0 unresolved BTP parents, per-product leaf counts from 274 to 482.",
            "signals": [
                "Finished-product BOM and BTP BOM are separate workbook families.",
                "Exact-code BTP workbook candidates should win over embedded finished-product candidates.",
                "Technical BOM versus DS NVL DK HQ comparison still shows only-in-BOM, only-in-DS, and quantity-delta review buckets.",
            ],
        },
        "material_catalog": [
            {
                "customs_code": "DEMO-NPL-001",
                "internal_code": "DEMO-NPL-001",
                "name": "Main control board - seed",
                "hs_code": "8542.39",
                "role": "NVL",
                "origin_default": "Không xuất xứ",
            },
            {
                "customs_code": "DEMO-NPL-002",
                "internal_code": "DEMO-NPL-002",
                "name": "Connector set - seed",
                "hs_code": "8536.90",
                "role": "NVL",
                "origin_default": "Không xuất xứ",
            },
            {
                "customs_code": "DEMO-NPL-003",
                "internal_code": "DEMO-NPL-003",
                "name": "Battery module - seed",
                "hs_code": "8507.60",
                "role": "NVL",
                "origin_default": "Không xuất xứ",
            },
        ],
        "product_catalog": [
            {
                "product_code": "PV00.0048500",
                "name": "Model inverter PV00.0048500",
                "hs_code": "8504.40",
                "rule": "RVC 35% + CTSH",
                "status": "Đang dùng",
            },
            {
                "product_code": "PV01.0117600",
                "name": "Model inverter PV01.0117600",
                "hs_code": "8504.40",
                "rule": "RVC 35% + CTSH",
                "status": "Đang dùng",
            },
        ],
        "bom_rows": [
            {
                "product_code": "PV00.0048500",
                "version": "Seed v1",
                "material_code": "DEMO-NPL-001",
                "material_name": "Main control board - seed",
                "qty_per": "1.00",
                "uom": "PCE",
                "scrap_rate": "0%",
                "source": "Growatt RVC seed",
                "state": "reviewable",
            },
            {
                "product_code": "PV00.0048500",
                "version": "Seed v1",
                "material_code": "DEMO-NPL-002",
                "material_name": "Connector set - seed",
                "qty_per": "1.75",
                "uom": "PCE",
                "scrap_rate": "0%",
                "source": "Growatt RVC seed",
                "state": "reviewable",
            },
            {
                "product_code": "PV01.0117600",
                "version": "Seed v1",
                "material_code": "DEMO-NPL-003",
                "material_name": "Battery module - seed",
                "qty_per": "1.00",
                "uom": "PCE",
                "scrap_rate": "0%",
                "source": "Growatt RVC seed",
                "state": "reviewable",
            },
            {
                "product_code": "PV01.0117600",
                "version": "Seed v1",
                "material_code": "DEMO-NPL-004",
                "material_name": "Plastic enclosure - seed",
                "qty_per": "4.00",
                "uom": "PCE",
                "scrap_rate": "0%",
                "source": "Growatt RVC seed",
                "state": "reviewable",
            },
        ],
        "co_stock": [
            {
                "source_row": "IMP-001/1",
                "import_declaration_no": "107101950210",
                "line_no": "1",
                "material_code": "DEMO-NPL-001",
                "available_qty": "520",
                "used_qty": "120",
                "remaining_qty": "400",
            },
            {
                "source_row": "IMP-002/3",
                "import_declaration_no": "107101950210",
                "line_no": "3",
                "material_code": "DEMO-NPL-002",
                "available_qty": "900",
                "used_qty": "210",
                "remaining_qty": "690",
            },
            {
                "source_row": "IMP-004/6",
                "import_declaration_no": "107101950211",
                "line_no": "6",
                "material_code": "DEMO-NPL-004",
                "available_qty": "1800",
                "used_qty": "300",
                "remaining_qty": "1500",
            },
        ],
        "bcct_rows": [
            {
                "period": "Seed 2026",
                "declaration_no": "107101950210",
                "direction": "Nhập khẩu",
                "declaration_type": "E11",
                "item_code": "DEMO-NPL-001",
                "qty": "520",
            },
            {
                "period": "Seed 2026",
                "declaration_no": "GIN01425L031",
                "direction": "Xuất khẩu",
                "declaration_type": "E42",
                "item_code": "PV00.0048500",
                "qty": "demo",
            },
            {
                "period": "Seed 2026",
                "declaration_no": "GIN01425L031",
                "direction": "Xuất khẩu",
                "declaration_type": "E42",
                "item_code": "PV01.0117600",
                "qty": "demo",
            },
        ],
    },
    {
        "id": "johnson",
        "name": "Johnson",
        "code": "JOHNSON",
        "status": "discovery",
        "tax_code": "Chưa nhập",
        "contact": "SAP BOM intake",
        "module_status": {
            "materials": "seeded",
            "products": "seeded",
            "bom": "seeded",
            "co_stock": "planned",
            "bcct": "planned",
            "co_cases": "planned",
        },
        "bom_source_profile": {
            "kind": "Johnson SAP exploded BOM export",
            "summary": "82 SAP WebAS workbooks, 22,800 aggregate rows, 14,289 structural leaves, 13,882 material-candidate leaves.",
            "signals": [
                "One Sheet1 per workbook with a shared 29-column SAP-style schema.",
                "Use Comp. Qty (CUn) as the safest flattened quantity, while preserving recomputed quantity as validation.",
                "Revision Level and Change Number are line-level evidence, not workbook-level BOM versions.",
            ],
        },
        "material_catalog": [
            {
                "customs_code": "0000096074",
                "internal_code": "0000096074",
                "name": "Powder Painting Material; silvery matte 2",
                "hs_code": "Chưa map",
                "role": "NVL",
                "origin_default": "Chưa xác định",
            },
            {
                "customs_code": "004426-00",
                "internal_code": "004426-00",
                "name": "Screw; Flat Head; M6x1.0Px12L",
                "hs_code": "Chưa map",
                "role": "NVL",
                "origin_default": "Chưa xác định",
            },
            {
                "customs_code": "1000461274",
                "internal_code": "1000461274",
                "name": "Tube; Round; 20#",
                "hs_code": "Chưa map",
                "role": "NVL",
                "origin_default": "Chưa xác định",
            },
        ],
        "product_catalog": [
            {
                "product_code": "MFW0502-39",
                "name": "Johnson SAP export product MFW0502-39",
                "hs_code": "Chưa map",
                "rule": "Chưa xác định",
                "status": "Đang phân tích",
            },
            {
                "product_code": "MFW0502-571",
                "name": "Johnson SAP export product MFW0502-571",
                "hs_code": "Chưa map",
                "rule": "Chưa xác định",
                "status": "Đang phân tích",
            },
        ],
        "bom_rows": [
            {
                "product_code": "MFW0502-39",
                "version": "SAP snapshot 2026-04-23",
                "material_code": "0000096074",
                "material_name": "Powder Painting Material; silvery matte 2",
                "qty_per": "0.759",
                "uom": "KG",
                "scrap_rate": "N/A",
                "source": "Johnson SAP WebAS export",
                "state": "material-candidate leaf",
            },
            {
                "product_code": "MFW0502-39",
                "version": "SAP snapshot 2026-04-23",
                "material_code": "004426-00",
                "material_name": "Screw; Flat Head; M6x1.0Px12L",
                "qty_per": "2",
                "uom": "EA",
                "scrap_rate": "N/A",
                "source": "Johnson SAP WebAS export",
                "state": "material-candidate leaf",
            },
            {
                "product_code": "MFW0502-39",
                "version": "SAP snapshot 2026-04-23",
                "material_code": "1000461274",
                "material_name": "Tube; Round; 20#",
                "qty_per": "1.306",
                "uom": "EA",
                "scrap_rate": "N/A",
                "source": "Johnson SAP WebAS export",
                "state": "material-candidate leaf",
            },
        ],
        "co_stock": [],
        "bcct_rows": [],
    },
    {
        "id": "do-thanh",
        "name": "Do Thanh",
        "code": "DO-THANH",
        "status": "discovery",
        "tax_code": "Chưa nhập",
        "contact": "Chưa nhập",
        "module_status": {
            "materials": "planned",
            "products": "planned",
            "bom": "planned",
            "co_stock": "planned",
            "bcct": "planned",
            "co_cases": "planned",
        },
        "material_catalog": [],
        "product_catalog": [],
        "bom_rows": [],
        "co_stock": [],
        "bcct_rows": [],
    },
]


DEMO_CASE = {
    "id": "growatt-gin01425l031",
    "customer": "Growatt",
    "case_code": "GIN01425L031",
    "title": "Demo hồ sơ C/O Growatt",
    "destination_market": "Ấn Độ",
    "agreement": "Chưa xác nhận trong seed demo",
    "co_form_type": "Chưa xác nhận trong seed demo",
    "rule": "RVC 35% + CTSH",
    "mode": "Demo đơn giản: Mã HQ = Mã nội bộ",
    "mode_note": "Growatt thật có dấu hiệu lệch mã HQ và mã nội bộ; bản demo này cố ý khóa một-mã để dựng khung trước.",
    "source_label": "Seed nội bộ Growatt",
    "documents": [
        {"slot": "export_declaration", "label": "Tờ khai xuất khẩu", "reference": "1. TKX.pdf", "status": "ready"},
        {"slot": "bill_of_lading", "label": "Vận đơn", "reference": "2. BL.pdf", "status": "ready"},
        {"slot": "invoice_packing", "label": "Invoice / Packing", "reference": "7. INV + PBO.pdf", "status": "ready"},
        {"slot": "rvc_workbook", "label": "Bảng RVC", "reference": "6. Bang RVC GIN01425L031.xlsx", "status": "ready"},
        {"slot": "process_pdf", "label": "Quy trình sản xuất", "reference": "5. QUY TRINH SAN XUAT MÁY BIẾN TẦN.pdf", "status": "ready"},
        {"slot": "ecosys_package", "label": "Gói khai eCoSys", "reference": "Chờ build từ dữ liệu đã duyệt", "status": "pending"},
    ],
    "workflow": [
        {"key": "profile", "label": "Hồ sơ thương nhân", "state": "read_only"},
        {"key": "evidence", "label": "Bằng chứng sản phẩm", "state": "active"},
        {"key": "shipment", "label": "Hồ sơ lô hàng", "state": "active"},
        {"key": "evaluation", "label": "Đánh giá xuất xứ", "state": "active"},
        {"key": "filing", "label": "Khai eCoSys", "state": "pending"},
        {"key": "archive", "label": "Lưu vết", "state": "pending"},
    ],
    "products": [
        {
            "code": "PV00.0048500",
            "name": "Model inverter PV00.0048500",
            "finished_hs": "8504.40",
            "quantity": "demo",
            "fob": "100000",
            "non_origin_value": "",
            "rvc_threshold": "35",
            "documented_result": "35.88% + CTSH",
            "materials": [
                {
                    "source_row": "IMP-001/1",
                    "import_declaration_no": "107101950210",
                    "import_line_no": "1",
                    "material_code": "DEMO-NPL-001",
                    "customs_material_code": "DEMO-NPL-001",
                    "internal_material_code": "DEMO-NPL-001",
                    "material_description": "Main control board - seed",
                    "hs_code": "8542.39",
                    "origin_status": "non_origin",
                    "available_qty": Decimal("520"),
                    "consumed_qty": Decimal("120"),
                    "non_origin_cif_value": Decimal("32000"),
                    "uom": "PCE",
                    "source_document_ref": "Seed import row 1",
                },
                {
                    "source_row": "IMP-002/3",
                    "import_declaration_no": "107101950210",
                    "import_line_no": "3",
                    "material_code": "DEMO-NPL-002",
                    "customs_material_code": "DEMO-NPL-002",
                    "internal_material_code": "DEMO-NPL-002",
                    "material_description": "Connector set - seed",
                    "hs_code": "8536.90",
                    "origin_status": "non_origin",
                    "available_qty": Decimal("900"),
                    "consumed_qty": Decimal("210"),
                    "non_origin_cif_value": Decimal("32120"),
                    "uom": "PCE",
                    "source_document_ref": "Seed import row 3",
                },
            ],
        },
        {
            "code": "PV01.0117600",
            "name": "Model inverter PV01.0117600",
            "finished_hs": "8504.40",
            "quantity": "demo",
            "fob": "100000",
            "non_origin_value": "",
            "rvc_threshold": "35",
            "documented_result": "40.19% + CTSH",
            "materials": [
                {
                    "source_row": "IMP-003/2",
                    "import_declaration_no": "107101950211",
                    "import_line_no": "2",
                    "material_code": "DEMO-NPL-003",
                    "customs_material_code": "DEMO-NPL-003",
                    "internal_material_code": "DEMO-NPL-003",
                    "material_description": "Battery module - seed",
                    "hs_code": "8507.60",
                    "origin_status": "non_origin",
                    "available_qty": Decimal("310"),
                    "consumed_qty": Decimal("75"),
                    "non_origin_cif_value": Decimal("29800"),
                    "uom": "PCE",
                    "source_document_ref": "Seed import row 2",
                },
                {
                    "source_row": "IMP-004/6",
                    "import_declaration_no": "107101950211",
                    "import_line_no": "6",
                    "material_code": "DEMO-NPL-004",
                    "customs_material_code": "DEMO-NPL-004",
                    "internal_material_code": "DEMO-NPL-004",
                    "material_description": "Plastic enclosure - seed",
                    "hs_code": "3926.90",
                    "origin_status": "non_origin",
                    "available_qty": Decimal("1800"),
                    "consumed_qty": Decimal("300"),
                    "non_origin_cif_value": Decimal("30010"),
                    "uom": "PCE",
                    "source_document_ref": "Seed import row 6",
                },
            ],
        },
    ],
}


def get_demo_case() -> dict:
    return attach_results(clone_case(DEMO_CASE))


def get_clients() -> list[dict]:
    return [client_summary(client) for client in CLIENTS]


def get_client(client_id: str) -> dict:
    for client in CLIENTS:
        if client["id"] == client_id:
            return clone_client(client)
    raise KeyError(client_id)


def get_client_case(client_id: str) -> dict:
    client = get_client(client_id)
    if client_id == "growatt":
        return get_demo_case()
    case = clone_case(DEMO_CASE)
    case.update(
        {
            "id": f"{client_id}-empty-co-case",
            "customer": client["name"],
            "case_code": "Chưa tạo",
            "title": f"Hồ sơ C/O {client['name']}",
            "destination_market": "Chưa nhập",
            "agreement": "Chưa nhập",
            "co_form_type": "Chưa nhập",
            "source_label": "Chưa có dữ liệu C/O",
            "products": [],
        }
    )
    return attach_results(case)


def client_summary(client: dict) -> dict:
    output = clone_client(client)
    output["counts"] = {
        "materials": len(client.get("material_catalog", [])),
        "products": len(client.get("product_catalog", [])),
        "bom_lines": len(client.get("bom_rows", [])),
        "co_stock": len(client.get("co_stock", [])),
        "bcct": len(client.get("bcct_rows", [])),
    }
    return output


def clone_client(client: dict) -> dict:
    cloned = {key: value for key, value in client.items() if key not in {
        "module_status",
        "material_catalog",
        "product_catalog",
        "bom_rows",
        "co_stock",
        "bcct_rows",
    }}
    cloned["module_status"] = dict(client.get("module_status", {}))
    cloned["material_catalog"] = [dict(row) for row in client.get("material_catalog", [])]
    cloned["product_catalog"] = [dict(row) for row in client.get("product_catalog", [])]
    cloned["bom_rows"] = [dict(row) for row in client.get("bom_rows", [])]
    cloned["co_stock"] = [dict(row) for row in client.get("co_stock", [])]
    cloned["bcct_rows"] = [dict(row) for row in client.get("bcct_rows", [])]
    cloned["counts"] = {
        "materials": len(cloned["material_catalog"]),
        "products": len(cloned["product_catalog"]),
        "bom_lines": len(cloned["bom_rows"]),
        "co_stock": len(cloned["co_stock"]),
        "bcct": len(cloned["bcct_rows"]),
    }
    return cloned


def clone_case(case: dict) -> dict:
    return {
        key: value
        for key, value in case.items()
        if key not in {"documents", "workflow", "products", "summary"}
    } | {
        "documents": [dict(document) for document in case.get("documents", [])],
        "workflow": [dict(step) for step in case.get("workflow", [])],
        "products": [
            {
                key: value
                for key, value in product.items()
                if key not in {"materials", "result"}
            }
            | {"materials": [dict(material) for material in product.get("materials", [])]}
            for product in case.get("products", [])
        ],
    }


def attach_results(case: dict) -> dict:
    for product in case["products"]:
        product["result"] = evaluate_rvc_ctsh(product)
    case["summary"] = build_summary(case)
    return case


def build_summary(case: dict) -> dict:
    products = case["products"]
    passed_products = sum(1 for product in products if product["result"].passed)
    rvc_values = [product["result"].rvc.percentage for product in products]
    ready_docs = sum(1 for doc in case["documents"] if doc["status"] == "ready")
    return {
        "product_count": len(products),
        "passed_products": passed_products,
        "ready_documents": ready_docs,
        "document_count": len(case["documents"]),
        "min_rvc": min(rvc_values) if rvc_values else Decimal("0"),
    }


def update_products_from_form(form: dict[str, str]) -> dict:
    return attach_results(case_from_form(form))


def case_from_form(form: dict[str, str]) -> dict:
    case = {
        "id": form.get("case_id", DEMO_CASE["id"]),
        "persisted_case_id": form.get("persisted_case_id", ""),
        "customer": form.get("customer", DEMO_CASE["customer"]),
        "case_code": form.get("case_code", DEMO_CASE["case_code"]),
        "title": form.get("title", DEMO_CASE["title"]),
        "destination_market": form.get("destination_market", DEMO_CASE["destination_market"]),
        "agreement": form.get("agreement", DEMO_CASE["agreement"]),
        "co_form_type": form.get("co_form_type", DEMO_CASE["co_form_type"]),
        "rule": form.get("rule", DEMO_CASE["rule"]),
        "mode": form.get("mode", DEMO_CASE["mode"]),
        "mode_note": form.get("mode_note", DEMO_CASE["mode_note"]),
        "source_label": form.get("source_label", "Dữ liệu trên màn hình"),
        "bom_version_id": form.get("bom_version_id", ""),
        "bom_product_version_overrides": {},
        "documents": [],
        "workflow": [dict(step) for step in DEMO_CASE["workflow"]],
        "shipment": {
            "invoice_no": form.get("invoice_no", ""),
            "bill_of_lading_no": form.get("bill_of_lading_no", ""),
        },
        "supporting_files": [],
        "products": [],
    }

    document_count = int(form.get("document_count", "0") or "0")
    for index in range(document_count):
        prefix = f"document_{index}_"
        case["documents"].append(
            {
                "slot": form.get(prefix + "slot", ""),
                "label": form.get(prefix + "label", ""),
                "reference": form.get(prefix + "reference", ""),
                "status": form.get(prefix + "status", "pending"),
            }
        )
    if not case["documents"]:
        case["documents"] = [dict(document) for document in DEMO_CASE["documents"]]

    product_count = int(form.get("product_count", "0") or "0")
    for index in range(product_count):
        prefix = f"product_{index}_"
        material_count = int(form.get(prefix + "material_count", "0") or "0")
        product = {
            "code": form.get(prefix + "code", ""),
            "name": form.get(prefix + "name", ""),
            "finished_hs": form.get(prefix + "finished_hs", ""),
            "quantity": form.get(prefix + "quantity", ""),
            "unit": form.get(prefix + "unit", form.get(prefix + "export_unit", "")),
            "currency": form.get(prefix + "currency", ""),
            "source_declaration_no": form.get(prefix + "source_declaration_no", ""),
            "source_line_no": form.get(prefix + "source_line_no", ""),
            "invoice_ref": form.get(prefix + "invoice_ref", ""),
            "fob": form.get(prefix + "fob", "0"),
            "non_origin_value": form.get(prefix + "non_origin_value", ""),
            "rvc_threshold": form.get(prefix + "rvc_threshold", "35"),
            "documented_result": form.get(prefix + "documented_result", ""),
            "lvc_percentage": form.get(prefix + "lvc_percentage", ""),
            "lvc_status": form.get(prefix + "lvc_status", ""),
            "lvc_status_label": form.get(prefix + "lvc_status_label", ""),
            "lvc_threshold": form.get(prefix + "lvc_threshold", ""),
            "vnm_value": form.get(prefix + "vnm_value", ""),
            "bom_product_version_id": form.get(prefix + "bom_product_version_id", ""),
            "origin_method": form.get(prefix + "origin_method", ""),
            "origin_method_label": form.get(prefix + "origin_method_label", ""),
            "origin_formula": form.get(prefix + "origin_formula", ""),
            "origin_criterion_mode": form.get(prefix + "origin_criterion_mode", ""),
            "origin_readiness_status": form.get(prefix + "origin_readiness_status", ""),
            "origin_readiness_label": form.get(prefix + "origin_readiness_label", ""),
            "origin_warnings_text": form.get(prefix + "origin_warnings", ""),
            "origin_warnings": text_list(form.get(prefix + "origin_warnings", "")),
            "tariff_shift_rule": form.get(prefix + "tariff_shift_rule", ""),
            "tariff_shift_status": form.get(prefix + "tariff_shift_status", ""),
            "tariff_shift_status_label": form.get(prefix + "tariff_shift_status_label", ""),
            "tariff_shift_note": form.get(prefix + "tariff_shift_note", ""),
            "materials": [],
        }
        if product["code"] and product["bom_product_version_id"]:
            case["bom_product_version_overrides"][product["code"]] = product["bom_product_version_id"]
        for material_index in range(material_count):
            material_prefix = f"{prefix}material_{material_index}_"
            material = {
                "source_row": form.get(material_prefix + "source_row", ""),
                "import_declaration_no": form.get(material_prefix + "import_declaration_no", ""),
                "import_line_no": form.get(material_prefix + "import_line_no", ""),
                "material_code": form.get(material_prefix + "material_code", ""),
                "customs_material_code": form.get(material_prefix + "customs_material_code", ""),
                "internal_material_code": form.get(material_prefix + "internal_material_code", ""),
                "material_description": form.get(material_prefix + "material_description", ""),
                "hs_code": form.get(material_prefix + "hs_code", ""),
                "origin_status": form.get(material_prefix + "origin_status", "non_origin"),
                "origin_status_label": form.get(material_prefix + "origin_status_label", ""),
                "origin_status_source": form.get(material_prefix + "origin_status_source", ""),
                "origin_status_note": form.get(material_prefix + "origin_status_note", ""),
                "available_qty": Decimal(form.get(material_prefix + "available_qty", "0") or "0"),
                "consumed_qty": Decimal(form.get(material_prefix + "consumed_qty", "0") or "0"),
                "non_origin_cif_value": Decimal(form.get(material_prefix + "non_origin_cif_value", "0") or "0"),
                "unit_value": form.get(material_prefix + "unit_value", ""),
                "currency": form.get(material_prefix + "currency", ""),
                "material_value": form.get(material_prefix + "material_value", ""),
                "valuation_status": form.get(material_prefix + "valuation_status", ""),
                "valuation_status_label": form.get(material_prefix + "valuation_status_label", ""),
                "valuation_source": form.get(material_prefix + "valuation_source", ""),
                "valuation_source_label": form.get(material_prefix + "valuation_source_label", ""),
                "data_status_label": form.get(material_prefix + "data_status_label", ""),
                "allocation_status": form.get(material_prefix + "allocation_status", ""),
                "allocation_shortage_qty": form.get(material_prefix + "allocation_shortage_qty", ""),
                "allocation_summary": form.get(material_prefix + "allocation_summary", ""),
                "allocation_lines": [],
                "material_warnings_text": form.get(material_prefix + "material_warnings", ""),
                "material_warnings": text_list(form.get(material_prefix + "material_warnings", "")),
                "bom_qty_per": form.get(material_prefix + "bom_qty_per", ""),
                "bom_scrap_rate": form.get(material_prefix + "bom_scrap_rate", ""),
                "bom_source": form.get(material_prefix + "bom_source", ""),
                "bom_row_class": form.get(material_prefix + "bom_row_class", ""),
                "uom": form.get(material_prefix + "uom", ""),
                "source_document_ref": form.get(material_prefix + "source_document_ref", ""),
            }
            allocation_line_count = int(form.get(material_prefix + "allocation_line_count", "0") or "0")
            for allocation_index in range(allocation_line_count):
                allocation_prefix = f"{material_prefix}allocation_{allocation_index}_"
                material["allocation_lines"].append(
                    {
                        "source_row": form.get(allocation_prefix + "source_row", ""),
                        "source_line_ids": form.get(allocation_prefix + "source_line_ids", ""),
                        "import_declaration_no": form.get(allocation_prefix + "import_declaration_no", ""),
                        "import_line_no": form.get(allocation_prefix + "import_line_no", ""),
                        "customs_material_code": form.get(allocation_prefix + "customs_material_code", ""),
                        "allocation_code": form.get(allocation_prefix + "allocation_code", ""),
                        "available_qty": form.get(allocation_prefix + "available_qty", ""),
                        "remaining_qty": form.get(allocation_prefix + "remaining_qty", ""),
                        "allocated_qty": form.get(allocation_prefix + "allocated_qty", ""),
                        "unit_value": form.get(allocation_prefix + "unit_value", ""),
                        "currency": form.get(allocation_prefix + "currency", ""),
                        "material_value": form.get(allocation_prefix + "material_value", ""),
                        "valuation_source": form.get(allocation_prefix + "valuation_source", ""),
                        "valuation_source_label": form.get(allocation_prefix + "valuation_source_label", ""),
                        "material_description": form.get(allocation_prefix + "material_description", ""),
                        "hs_code": form.get(allocation_prefix + "hs_code", ""),
                    }
                )
            product["materials"].append(material)
        case["products"].append(product)
    return case


def text_list(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split("|") if item.strip()]
