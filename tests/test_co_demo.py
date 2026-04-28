from decimal import Decimal
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from app.bom_store import get_bom_workspace
from app.client_config_store import (
    get_client_config,
    resolve_allocation_code,
    save_client_config,
)
from app.demo_data import get_client, get_client_case, get_clients, get_demo_case, update_products_from_form
from app.main import app
from app.origin import calculate_rvc, evaluate_tariff_shift
from app.source_store import (
    create_bcct_template_workbook,
    create_material_catalog_template_workbook,
    create_product_catalog_template_workbook,
    get_source_workspace,
    parse_bcct_workbook,
    parse_catalog_workbook,
    process_bcct_upload,
    process_catalog_upload,
)
from app.table_view import build_table_view
from app.workbook_io import create_evidence_workbook, create_input_workbook, parse_input_workbook


@pytest.fixture(autouse=True)
def isolate_bom_store(tmp_path, monkeypatch):
    monkeypatch.setenv("BOM_STORE_ROOT", str(tmp_path / "bom-store"))
    monkeypatch.setenv("SOURCE_STORE_ROOT", str(tmp_path / "source-store"))
    monkeypatch.setenv("CLIENT_CONFIG_ROOT", str(tmp_path / "client-config"))


def workbook_bytes(workbook: Workbook) -> bytes:
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def bcct_workbook(rows: list[dict]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "BCCT"
    worksheet.append([
        "coverage_period",
        "direction",
        "declaration_no",
        "declaration_date",
        "customs_office",
        "declaration_type",
        "line_no",
        "item_code",
        "description",
        "hs_code",
        "quantity",
        "unit",
        "customs_value",
        "invoice_ref",
    ])
    for row in rows:
        worksheet.append([
            row.get("coverage_period", ""),
            row["direction"],
            row["declaration_no"],
            row.get("declaration_date", ""),
            row.get("customs_office", ""),
            row.get("declaration_type", ""),
            row["line_no"],
            row["item_code"],
            row.get("description", ""),
            row.get("hs_code", ""),
            row["quantity"],
            row["unit"],
            row.get("customs_value", ""),
            row.get("invoice_ref", ""),
        ])
    return workbook_bytes(workbook)


def customs_zip_entry(filename: str) -> bytes:
    archive_path = Path("temp/drive-download-20260428T145419Z-3-001.zip")
    if not archive_path.exists():
        pytest.skip("Customs sample ZIP is local-only.")
    with ZipFile(archive_path) as archive:
        return archive.read(filename)


def test_calculates_growatt_documented_rvc_seed_from_material_rows():
    case = get_demo_case()

    assert case["products"][0]["result"].rvc.percentage == Decimal("35.88")
    assert case["products"][1]["result"].rvc.percentage == Decimal("40.19")
    assert case["summary"]["passed_products"] == 2


def test_evaluates_ctsh_by_six_digit_subheading():
    result = evaluate_tariff_shift("8504.40", ["8542.39", "8536.90"], "CTSH")

    assert result.finished_key == "850440"
    assert result.input_keys == ("854239", "853690")
    assert result.passed is True


def test_form_update_recomputes_rvc_from_edited_material_value():
    case = update_products_from_form(
        {
            "customer": "Growatt",
            "case_code": "TEST",
            "product_count": "1",
            "product_0_code": "PV00.0048500",
            "product_0_name": "Model inverter PV00.0048500",
            "product_0_finished_hs": "8504.40",
            "product_0_fob": "100000",
            "product_0_rvc_threshold": "35",
            "product_0_material_count": "1",
            "product_0_material_0_source_row": "IMP-001/1",
            "product_0_material_0_hs_code": "8542.39",
            "product_0_material_0_origin_status": "non_origin",
            "product_0_material_0_available_qty": "520",
            "product_0_material_0_consumed_qty": "120",
            "product_0_material_0_non_origin_cif_value": "70000",
        }
    )

    assert case["products"][0]["result"].rvc.percentage == Decimal("30.00")
    assert case["products"][0]["result"].passed is False


def test_seed_workbook_round_trips_through_parser():
    parsed = parse_input_workbook(create_input_workbook(get_demo_case()), "roundtrip")

    assert parsed["source_label"] == "roundtrip"
    assert parsed["products"][0]["code"] == "PV00.0048500"
    assert parsed["products"][0]["materials"][0]["customs_material_code"] == "DEMO-NPL-001"
    assert parsed["products"][0]["materials"][0]["internal_material_code"] == "DEMO-NPL-001"
    assert parsed["products"][0]["result"].rvc.percentage == Decimal("35.88")


def test_evidence_workbook_is_generated():
    content = create_evidence_workbook(get_demo_case())

    assert content.startswith(b"PK")


def test_workspace_renders_interactive_controls():
    client = TestClient(app)

    response = client.get("/clients/growatt")

    assert response.status_code == 200
    assert "Growatt" in response.text
    assert "/clients/growatt/catalog" in response.text
    assert "/clients/growatt/bom" in response.text
    assert "/clients/growatt/co-stock" in response.text
    assert "/clients/growatt/bcct" in response.text
    assert "/clients/growatt/co-case" in response.text
    assert "Workspace theo công ty" in response.text


def test_theme_toggle_persists_dark_theme_cookie():
    client = TestClient(app)

    initial = client.get("/clients")
    assert initial.status_code == 200
    assert 'data-theme="light"' in initial.text

    response = client.post(
        "/settings/theme",
        data={"theme": "dark", "next_url": "/clients/growatt"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/clients/growatt"
    assert "co_theme=dark" in response.headers["set-cookie"]

    themed = client.get("/clients/growatt")
    assert themed.status_code == 200
    assert 'data-theme="dark"' in themed.text
    assert 'name="theme" value="light"' in themed.text


def test_workspace_has_single_module_navigation_layer():
    client = TestClient(app)

    response = client.get("/clients/growatt/co-case")

    assert response.status_code == 200
    assert response.text.count("/clients/growatt/catalog") == 1
    assert response.text.count("/clients/growatt/bom") == 1
    assert response.text.count("/clients/growatt/co-stock") == 1
    assert response.text.count("/clients/growatt/bcct") == 1


def test_table_view_filters_searches_sorts_and_paginates():
    rows = [
        {"code": "MAT-001", "name": "Capacitor", "status": "inactive"},
        {"code": "MAT-002", "name": "Diode bridge", "status": "active"},
        {"code": "MAT-003", "name": "Small diode", "status": "active"},
    ]

    table = build_table_view(
        rows,
        columns=[
            {"key": "code", "label": "Code"},
            {"key": "name", "label": "Name"},
            {"key": "status", "label": "Status"},
        ],
        query={"q": "diode", "status": "active", "sort": "code", "dir": "desc", "page": "2", "per_page": "1"},
        filters=[{"name": "status", "field": "status", "label": "Status"}],
    )

    assert table["total_count"] == 3
    assert table["filtered_count"] == 2
    assert table["page"] == 2
    assert table["total_pages"] == 2
    assert [row["code"] for row in table["rows"]] == ["MAT-002"]


def test_table_view_clamps_page_to_available_results():
    table = build_table_view(
        [{"code": "A"}, {"code": "B"}, {"code": "C"}],
        columns=[{"key": "code", "label": "Code"}],
        query={"page": "99", "per_page": "2"},
    )

    assert table["page"] == 2
    assert table["total_pages"] == 2
    assert [row["code"] for row in table["rows"]] == ["C"]


def test_catalog_bom_stock_bcct_and_co_case_are_separate_views():
    client = TestClient(app)

    catalog_response = client.get("/clients/growatt/catalog")
    material_catalog_response = client.get("/clients/growatt/catalog/materials")
    product_catalog_response = client.get("/clients/growatt/catalog/products")
    bom_response = client.get("/clients/growatt/bom")
    stock_response = client.get("/clients/growatt/co-stock")
    bcct_response = client.get("/clients/growatt/bcct")
    co_case_response = client.get("/clients/growatt/co-case")

    assert catalog_response.status_code == 200
    assert material_catalog_response.status_code == 200
    assert product_catalog_response.status_code == 200
    assert bom_response.status_code == 200
    assert stock_response.status_code == 200
    assert bcct_response.status_code == 200
    assert co_case_response.status_code == 200
    assert "Upload danh mục" in catalog_response.text
    assert "/clients/growatt/catalog/materials" in catalog_response.text
    assert "/clients/growatt/catalog/products" in catalog_response.text
    assert "DS NVL DK HQ" in material_catalog_response.text
    assert "DEMO-NPL-001" in material_catalog_response.text
    assert "Mã nội bộ" not in material_catalog_response.text
    assert "DS SP DK HQ" in product_catalog_response.text
    assert "PV00.0048500" in product_catalog_response.text
    assert "DEMO-NPL-001" in bom_response.text
    assert "Tồn CO khác tồn kho vật lý" in stock_response.text
    assert "BCCT nhập khẩu / xuất khẩu" in bcct_response.text
    assert "107101950210" in bcct_response.text
    assert "Upload và parse" in co_case_response.text
    assert "Quy tắc áp dụng" in co_case_response.text
    assert "Xuất evidence XLSX" in co_case_response.text
    assert "BTP" not in catalog_response.text


def test_catalog_child_route_search_limits_material_rows():
    client = TestClient(app)

    response = client.get("/clients/growatt/catalog/materials?q=DEMO-NPL-002")

    assert response.status_code == 200
    assert "DEMO-NPL-002" in response.text
    assert "DEMO-NPL-001" not in response.text
    assert "1 / 3 dòng" in response.text


def test_catalog_product_route_search_limits_product_rows():
    client = TestClient(app)

    response = client.get("/clients/growatt/catalog/products?q=PV01.0117600")

    assert response.status_code == 200
    assert "PV01.0117600" in response.text
    assert "PV00.0048500" not in response.text
    assert "1 / 2 dòng" in response.text


def test_product_catalog_does_not_render_origin_rule():
    client = TestClient(app)

    response = client.get("/clients/growatt/catalog/products")

    assert response.status_code == 200
    assert "Quy tắc" not in response.text
    assert "RVC 35% + CTSH" not in response.text


def test_product_catalog_template_does_not_include_origin_rule_column():
    workbook = load_workbook(BytesIO(create_product_catalog_template_workbook(get_client("growatt"))))
    headers = [cell.value for cell in workbook.active[1]]

    assert "Quy tắc" not in headers
    assert "origin_rule" not in headers
    assert "rule" not in headers


def test_product_catalog_upload_ignores_legacy_origin_rule_column():
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["Mã", "Tên", "Đơn vị tính", "Mã HS", "Quy tắc"])
    worksheet.append(["TP-001", "Finished product", "PCS", "85044090", "RVC 35% + CTSH"])

    result = process_catalog_upload(
        get_client("do-thanh"),
        "product",
        workbook_bytes(workbook),
        "legacy-ds-sp.xlsx",
        "full_catalog",
    )

    rows = get_source_workspace(get_client("do-thanh"))["product_catalog"]["published_rows"]
    assert result["status"] == "new_version"
    assert rows[0]["product_code"] == "TP-001"
    assert "rule" not in rows[0]
    assert rows[0]["raw_fields"]["Quy tắc"] == "RVC 35% + CTSH"


def test_bcct_route_paginates_rows_server_side():
    client = TestClient(app)

    response = client.get("/clients/growatt/bcct?per_page=1&page=2")

    assert response.status_code == 200
    assert "GIN01425L031" in response.text
    assert "107101950210" not in response.text
    assert "Trang 2 / 3" in response.text


def test_co_stock_route_search_and_status_filter():
    client = TestClient(app)

    response = client.get("/clients/growatt/co-stock?q=DEMO-NPL-001&status=available")

    assert response.status_code == 200
    assert "DEMO-NPL-001" in response.text
    assert "GIN01425L031" not in response.text
    assert "Hiển thị 1-1 / 1 dòng" in response.text


def test_clients_page_is_entry_point():
    client = TestClient(app)

    response = client.get("/clients")

    assert response.status_code == 200
    assert "Danh sách công ty" in response.text
    assert "Growatt" in response.text
    assert "Johnson" in response.text
    assert "Danh mục TP" in response.text
    assert "Danh mục NVL" in response.text
    assert "BOM" in response.text
    assert "Tồn CO" in response.text
    assert "BTP" not in response.text


def test_upload_seed_workbook_runs_parser():
    client = TestClient(app)
    content = create_input_workbook(get_demo_case())

    response = client.post(
        "/clients/growatt/upload",
        files={"file": ("growatt.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    assert "Đã parse growatt.xlsx" in response.text
    assert "PV01.0117600" in response.text


def test_download_seed_input_and_export_routes_return_xlsx():
    client = TestClient(app)

    seed_response = client.get("/clients/growatt/demo-input.xlsx")
    assert seed_response.status_code == 200
    assert seed_response.content.startswith(b"PK")

    export_response = client.post(
        "/clients/growatt/export",
        data={
            "customer": "Growatt",
            "case_code": "TEST",
            "product_count": "1",
            "product_0_code": "PV00.0048500",
            "product_0_name": "Model inverter PV00.0048500",
            "product_0_finished_hs": "8504.40",
            "product_0_fob": "100000",
            "product_0_rvc_threshold": "35",
            "product_0_material_count": "1",
            "product_0_material_0_hs_code": "8542.39",
            "product_0_material_0_origin_status": "non_origin",
            "product_0_material_0_available_qty": "520",
            "product_0_material_0_consumed_qty": "120",
            "product_0_material_0_non_origin_cif_value": "64120",
        },
    )
    assert export_response.status_code == 200
    assert export_response.content.startswith(b"PK")


def test_low_level_rvc_calculation_still_matches_formula():
    result = calculate_rvc("100000", "64120", "35")

    assert result.percentage == Decimal("35.88")
    assert result.passed is True


def test_client_seed_has_required_company_modules():
    growatt = [client for client in get_clients() if client["id"] == "growatt"][0]
    johnson = [client for client in get_clients() if client["id"] == "johnson"][0]
    case = get_client_case("growatt")

    assert growatt["counts"]["materials"] > 0
    assert growatt["counts"]["products"] > 0
    assert growatt["counts"]["bom_lines"] > 0
    assert growatt["counts"]["co_stock"] > 0
    assert growatt["counts"]["bcct"] > 0
    assert "boms" not in growatt["counts"]
    assert johnson["counts"]["products"] > 0
    assert johnson["counts"]["materials"] > 0
    assert johnson["counts"]["bom_lines"] > 0
    assert case["customer"] == "Growatt"


def test_bom_view_surfaces_company_source_profiles():
    client = TestClient(app)

    growatt_response = client.get("/clients/growatt/bom")
    johnson_response = client.get("/clients/johnson/bom")

    assert growatt_response.status_code == 200
    assert johnson_response.status_code == 200
    assert "Growatt multi-workbook technical BOM graph" in growatt_response.text
    assert "Johnson SAP exploded BOM export" in johnson_response.text
    assert "SAP WebAS" in johnson_response.text


def test_bom_template_download_and_no_change_upload_keeps_current_version():
    client = TestClient(app)

    template = client.get("/clients/growatt/bom/template.xlsx")
    assert template.status_code == 200
    assert template.content.startswith(b"PK")

    response = client.post(
        "/clients/growatt/bom/upload",
        data={"upload_mode": "direct_bom"},
        files={"file": ("growatt-bom.xlsx", template.content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    assert "Không có thay đổi BOM" in response.text
    workspace = get_bom_workspace(get_client("growatt"))
    assert workspace["latest_version"]["version_no"] == 1
    assert {row["product_version_no"] for row in workspace["product_composition"]} == {1}


def test_bom_changed_upload_creates_next_version():
    client = TestClient(app)
    template = client.get("/clients/growatt/bom/template.xlsx")
    workbook = load_workbook(BytesIO(template.content))
    worksheet = workbook["BOM"]
    worksheet["F2"] = "2.00"
    stream = BytesIO()
    workbook.save(stream)

    response = client.post(
        "/clients/growatt/bom/upload",
        data={"upload_mode": "direct_bom"},
        files={"file": ("growatt-bom-changed.xlsx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    assert "Đã tạo BOM tổng hợp v2" in response.text
    assert "BOM tổng hợp v2" in response.text
    assert "Đổi <strong>1</strong>" in response.text
    workspace = get_bom_workspace(get_client("growatt"))
    composition = {row["product_code"]: row["product_version_no"] for row in workspace["product_composition"]}
    assert workspace["latest_version"]["version_no"] == 2
    assert composition["PV00.0048500"] == 2
    assert composition["PV01.0117600"] == 1
    assert [version["product_version_no"] for version in workspace["product_versions"] if version["product_code"] == "PV00.0048500"] == [2, 1]


def test_direct_bom_full_aggregate_retires_missing_products():
    client = TestClient(app)
    template = client.get("/clients/growatt/bom/template.xlsx")
    workbook = load_workbook(BytesIO(template.content))
    worksheet = workbook["BOM"]
    for row_index in range(worksheet.max_row, 1, -1):
        if worksheet.cell(row_index, 1).value == "PV01.0117600":
            worksheet.delete_rows(row_index)
    worksheet["F2"] = "2.00"
    stream = BytesIO()
    workbook.save(stream)

    response = client.post(
        "/clients/growatt/bom/upload",
        data={"upload_mode": "direct_bom"},
        files={"file": ("growatt-bom-full.xlsx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    assert "PV01.0117600 v1 -&gt; retired" in response.text
    workspace = get_bom_workspace(get_client("growatt"))
    composition = {row["product_code"]: row["product_version_no"] for row in workspace["product_composition"]}
    assert composition == {"PV00.0048500": 2}


def test_direct_bom_partial_upload_preserves_missing_products():
    client = TestClient(app)
    template = client.get("/clients/growatt/bom/template.xlsx")
    workbook = load_workbook(BytesIO(template.content))
    worksheet = workbook["BOM"]
    for row_index in range(worksheet.max_row, 1, -1):
        if worksheet.cell(row_index, 1).value == "PV01.0117600":
            worksheet.delete_rows(row_index)
    worksheet["F2"] = "2.00"
    stream = BytesIO()
    workbook.save(stream)

    response = client.post(
        "/clients/growatt/bom/upload",
        data={"upload_mode": "direct_bom", "upload_scope": "partial_product"},
        files={"file": ("growatt-bom-partial.xlsx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    workspace = get_bom_workspace(get_client("growatt"))
    composition = {row["product_code"]: row["product_version_no"] for row in workspace["product_composition"]}
    assert composition["PV00.0048500"] == 2
    assert composition["PV01.0117600"] == 1


def test_duplicate_bom_rows_are_rejected_before_versioning():
    client = TestClient(app)
    template = client.get("/clients/growatt/bom/template.xlsx")
    workbook = load_workbook(BytesIO(template.content))
    worksheet = workbook["BOM"]
    duplicate_values = [worksheet.cell(2, column_index).value for column_index in range(1, worksheet.max_column + 1)]
    worksheet.append(duplicate_values)
    stream = BytesIO()
    workbook.save(stream)

    response = client.post(
        "/clients/growatt/bom/upload",
        data={"upload_mode": "direct_bom"},
        files={"file": ("growatt-bom-duplicate.xlsx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 400
    assert "BOM có dòng trùng khóa" in response.text
    assert get_bom_workspace(get_client("growatt"))["latest_version"]["version_no"] == 1


def test_reupload_historical_bom_can_create_new_product_version_against_current():
    client = TestClient(app)
    template = client.get("/clients/growatt/bom/template.xlsx").content
    client.post(
        "/clients/growatt/bom/upload",
        data={"upload_mode": "direct_bom"},
        files={"file": ("growatt-bom.xlsx", template, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    workbook = load_workbook(BytesIO(template))
    workbook["BOM"]["F2"] = "2.00"
    changed = BytesIO()
    workbook.save(changed)
    client.post(
        "/clients/growatt/bom/upload",
        data={"upload_mode": "direct_bom"},
        files={"file": ("growatt-bom-changed.xlsx", changed.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    response = client.post(
        "/clients/growatt/bom/upload",
        data={"upload_mode": "direct_bom"},
        files={"file": ("growatt-bom.xlsx", template, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    assert "PV00.0048500 v2 -&gt; v3" in response.text
    workspace = get_bom_workspace(get_client("growatt"))
    composition = {row["product_code"]: row["product_version_no"] for row in workspace["product_composition"]}
    assert workspace["latest_version"]["version_no"] == 3
    assert composition["PV00.0048500"] == 3
    assert composition["PV01.0117600"] == 1
    assert [version["product_version_no"] for version in workspace["product_versions"] if version["product_code"] == "PV00.0048500"] == [3, 2, 1]


def test_bom_company_config_can_be_updated():
    client = TestClient(app)

    response = client.post(
        "/clients/growatt/bom/config",
        data={
            "bom_profile": "johnson_sap_exploded",
            "default_import_mode": "technical_bom",
            "code_system_mode": "single_code",
        },
    )

    assert response.status_code == 200
    assert "Đã lưu cấu hình BOM" in response.text
    assert '<option value="johnson_sap_exploded" selected>' in response.text
    assert '<option value="technical_bom" selected>' in response.text
    assert '<option value="single_code" selected>' in response.text


def test_growatt_technical_bom_upload_requires_flatten_review_before_publish():
    client = TestClient(app)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Growatt"
    worksheet.append(["成品物料", "组件物料", "组件物料描述", "标准用量", "单位"])
    worksheet.append(["PV00.0048500", "GW-NVL-001", "Growatt board", "1.5", "PCE"])
    stream = BytesIO()
    workbook.save(stream)

    response = client.post(
        "/clients/growatt/bom/upload",
        data={"upload_mode": "technical_bom"},
        files={"file": ("growatt-technical.xlsx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    assert "cần review flatten" in response.text
    assert get_bom_workspace(get_client("growatt"))["latest_version"]["version_no"] == 1


def test_growatt_technical_bom_upload_can_be_accepted_as_flat_for_demo():
    client = TestClient(app)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Growatt"
    worksheet.append(["成品物料", "组件物料", "组件物料描述", "标准用量", "单位"])
    worksheet.append(["PV00.0048500", "GW-NVL-001", "Growatt board", "1.5", "PCE"])
    stream = BytesIO()
    workbook.save(stream)

    response = client.post(
        "/clients/growatt/bom/upload",
        data={"upload_mode": "technical_bom", "accept_review_required": "on"},
        files={"file": ("growatt-technical.xlsx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    assert "Đã tạo BOM tổng hợp v2" in response.text
    assert "GW-NVL-001" in response.text
    assert "needs_graph_flatten_review" in response.text
    workspace = get_bom_workspace(get_client("growatt"))
    composition = {row["product_code"]: row["product_version_no"] for row in workspace["product_composition"]}
    assert composition["PV00.0048500"] == 2
    assert composition["PV01.0117600"] == 1


def test_repeated_uploads_get_distinct_upload_ids():
    client = TestClient(app)
    template = client.get("/clients/growatt/bom/template.xlsx").content

    for _ in range(2):
        response = client.post(
            "/clients/growatt/bom/upload",
            data={"upload_mode": "direct_bom"},
            files={"file": ("growatt-bom.xlsx", template, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert response.status_code == 200

    uploads = get_bom_workspace(get_client("growatt"))["uploads"]
    upload_ids = [upload["upload_id"] for upload in uploads]
    assert len(upload_ids) == len(set(upload_ids))


def test_co_case_can_select_aggregate_bom_version_snapshot():
    client = TestClient(app)
    template = client.get("/clients/growatt/bom/template.xlsx")
    workbook = load_workbook(BytesIO(template.content))
    workbook["BOM"]["F2"] = "2.00"
    stream = BytesIO()
    workbook.save(stream)
    client.post(
        "/clients/growatt/bom/upload",
        data={"upload_mode": "direct_bom"},
        files={"file": ("growatt-bom-changed.xlsx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    workspace = get_bom_workspace(get_client("growatt"))
    v1 = [version for version in workspace["versions"] if version["version_no"] == 1][0]

    get_response = client.get("/clients/growatt/co-case")
    assert get_response.status_code == 200
    assert "BOM snapshot" in get_response.text
    assert "BOM tổng hợp v2" in get_response.text

    post_response = client.post(
        "/clients/growatt/evaluate",
        data={
            "case_id": "TEST",
            "customer": "Growatt",
            "case_code": "TEST",
            "document_count": "0",
            "product_count": "1",
            "bom_version_id": v1["version_id"],
            "product_0_code": "PV00.0048500",
            "product_0_name": "Model inverter PV00.0048500",
            "product_0_finished_hs": "8504.40",
            "product_0_quantity": "demo",
            "product_0_fob": "100000",
            "product_0_rvc_threshold": "35",
            "product_0_documented_result": "demo",
            "product_0_material_count": "0",
        },
    )

    assert post_response.status_code == 200
    assert f'value="{v1["version_id"]}" selected' in post_response.text
    assert "TP BOM v1" in post_response.text


def test_johnson_technical_bom_upload_keeps_sap_leaf_rows_only():
    client = TestClient(app)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Sheet1"
    worksheet.append(["Level", "Explosion level", "Component number", "Object description", "Comp. Qty (CUn)", "Component unit"])
    worksheet.append([1, 1, "ASM-001", "Assembly parent", 1, "EA"])
    worksheet.append([2, 2, "004426-00", "Screw; Flat Head; M6x1.0Px12L", 2, "EA"])
    worksheet.append([2, 2, "1000461274", "Tube; Round; 20#", 1.306, "EA"])
    stream = BytesIO()
    workbook.save(stream)

    response = client.post(
        "/clients/johnson/bom/upload",
        data={"upload_mode": "technical_bom"},
        files={"file": ("MFW0502-39.xlsx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    assert "Đã tạo BOM tổng hợp v2" in response.text
    assert "004426-00" in response.text
    assert "1000461274" in response.text
    assert "ASM-001" not in response.text
    workspace = get_bom_workspace(get_client("johnson"))
    product_versions = [version for version in workspace["product_versions"] if version["product_code"] == "MFW0502-39"]
    assert [version["product_version_no"] for version in product_versions] == [2, 1]


def test_material_catalog_full_upload_marks_omitted_code_inactive_pending_review():
    client = get_client("growatt")
    template = create_material_catalog_template_workbook(client)
    workbook = load_workbook(BytesIO(template))
    worksheet = workbook.active
    for row_index in range(worksheet.max_row, 1, -1):
        if worksheet.cell(row_index, 2).value == "DEMO-NPL-003":
            worksheet.delete_rows(row_index)

    result = process_catalog_upload(client, "material", workbook_bytes(workbook), "ds-nvl.xlsx", "full_catalog")

    assert result["status"] == "new_version"
    assert result["summary"]["inactive_pending_review"] == 1
    workspace = get_source_workspace(client)
    omitted_row = [row for row in workspace["material_catalog"]["published_rows"] if row["customs_code"] == "DEMO-NPL-003"][0]
    assert omitted_row["status"] == "inactive_pending_review"


def test_material_catalog_partial_update_does_not_deactivate_missing_codes():
    client = get_client("growatt")
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "NVL"
    worksheet.append(["customs_code", "internal_code", "name", "hs_code", "unit", "role", "origin_default", "status"])
    worksheet.append(["DEMO-NPL-001", "DEMO-NPL-001", "Main control board - edited", "8542.39", "PCS", "NVL", "Không xuất xứ", "active"])

    result = process_catalog_upload(client, "material", workbook_bytes(workbook), "ds-nvl-partial.xlsx", "partial_update")

    assert result["status"] == "new_version"
    workspace = get_source_workspace(client)
    retained_row = [row for row in workspace["material_catalog"]["published_rows"] if row["customs_code"] == "DEMO-NPL-003"][0]
    edited_row = [row for row in workspace["material_catalog"]["published_rows"] if row["customs_code"] == "DEMO-NPL-001"][0]
    assert retained_row["status"] != "inactive_pending_review"
    assert edited_row["name"] == "Main control board - edited"


def test_bcct_arbitrary_overlap_upload_adds_new_rows_without_deleting_missing_rows():
    client = get_client("do-thanh")
    first_upload = bcct_workbook([
        {
            "coverage_period": "2026-01",
            "direction": "import",
            "declaration_no": "TK-001",
            "line_no": "1",
            "item_code": "MAT-001",
            "description": "Material 1",
            "hs_code": "8542.39",
            "quantity": "100",
            "unit": "PCS",
            "customs_value": "1000",
        }
    ])
    second_upload = bcct_workbook([
        {
            "coverage_period": "2026-02",
            "direction": "import",
            "declaration_no": "TK-002",
            "line_no": "1",
            "item_code": "MAT-002",
            "description": "Material 2",
            "hs_code": "8536.90",
            "quantity": "50",
            "unit": "PCS",
            "customs_value": "500",
        }
    ])

    process_bcct_upload(client, first_upload, "bcct-jan.xlsx")
    result = process_bcct_upload(client, second_upload, "bcct-feb.xlsx")

    assert result["status"] == "new_version"
    assert result["summary"]["added_rows"] == 1
    workspace = get_source_workspace(client)
    assert {row["transaction_key"] for row in workspace["bcct"]["published_rows"]} == {
        "import||TK-001||1||MAT-001",
        "import||TK-002||1||MAT-002",
    }


def test_bcct_reupload_identical_row_with_unit_alias_is_noop():
    client = get_client("do-thanh")
    first_upload = bcct_workbook([
        {"direction": "import", "declaration_no": "TK-001", "line_no": "1", "item_code": "MAT-001", "quantity": "100", "unit": "PCS"}
    ])
    alias_upload = bcct_workbook([
        {"direction": "import", "declaration_no": "TK-001", "line_no": "1", "item_code": "MAT-001", "quantity": "100", "unit": "PCE"}
    ])

    process_bcct_upload(client, first_upload, "bcct-a.xlsx")
    result = process_bcct_upload(client, alias_upload, "bcct-alias.xlsx")

    assert result["status"] == "no_change"
    assert result["summary"]["unchanged_rows"] == 1
    workspace = get_source_workspace(client)
    assert workspace["bcct"]["published_rows"][0]["unit"] == "PCS"
    assert workspace["bcct"]["correction_candidates"] == []


def test_bcct_changed_unit_same_key_creates_correction_candidate():
    client = get_client("do-thanh")
    first_upload = bcct_workbook([
        {"direction": "import", "declaration_no": "TK-001", "line_no": "1", "item_code": "MAT-001", "quantity": "100", "unit": "PCS"}
    ])
    changed_upload = bcct_workbook([
        {"direction": "import", "declaration_no": "TK-001", "line_no": "1", "item_code": "MAT-001", "quantity": "100", "unit": "KG"}
    ])

    process_bcct_upload(client, first_upload, "bcct-a.xlsx")
    result = process_bcct_upload(client, changed_upload, "bcct-conflict.xlsx")

    assert result["status"] == "review_required"
    assert result["summary"]["correction_candidates"] == 1
    workspace = get_source_workspace(client)
    assert workspace["bcct"]["published_rows"][0]["unit"] == "PCS"
    assert workspace["bcct"]["correction_candidates"][0]["incoming_row"]["unit"] == "KG"


def test_bcct_parser_infers_configured_import_types_when_direction_is_blank():
    rows = parse_bcct_workbook(bcct_workbook([
        {"direction": "", "declaration_type": "E21", "declaration_no": "GC-001", "line_no": "1", "item_code": "MAT-GC-1", "quantity": "10", "unit": "PCS"},
        {"direction": "", "declaration_type": "E23", "declaration_no": "GC-002", "line_no": "1", "item_code": "MAT-GC-2", "quantity": "20", "unit": "PCS"},
        {"direction": "", "declaration_type": "E31", "declaration_no": "SXXK-001", "line_no": "1", "item_code": "MAT-SX-1", "quantity": "30", "unit": "PCS"},
        {"direction": "", "declaration_type": "E62", "declaration_no": "XK-001", "line_no": "1", "item_code": "TP-1", "quantity": "5", "unit": "PCS"},
    ]))

    assert {row["declaration_type"]: row["direction"] for row in rows} == {
        "E21": "import",
        "E23": "import",
        "E31": "import",
        "E62": "export",
    }


def test_growatt_client_config_defaults_to_dncx_and_description_allocation():
    config = get_client_config(get_client("growatt"))

    assert config["bcct"]["eligible_import_declaration_types"] == ["E11", "E15"]
    assert config["bcct"]["relevant_export_declaration_types"] == ["E42"]
    assert config["co_stock"]["lot_policy"] == "line_level"
    assert config["allocation_code"]["strategy"] == "description_regex"
    assert config["allocation_code"]["fallback"] == "same_as_customs_code"
    assert config["config_hash"]


def test_allocation_code_resolver_handles_regex_fallback_and_ambiguity():
    config = get_client_config(get_client("growatt"))

    resolved = resolve_allocation_code(
        {"item_code": "DIENTRO", "description": "DIENTRO#&Điện trở. Hàng mới 100% (001.0001400)"},
        config,
    )
    fallback = resolve_allocation_code(
        {"item_code": "DIENTRO", "description": "DIENTRO#&Điện trở không có mã trong ngoặc"},
        config,
    )
    ambiguous = resolve_allocation_code(
        {"item_code": "DIENTRO", "description": "DIENTRO#&Điện trở (001.0001400) hoặc (001.0001500)"},
        config,
    )

    assert resolved["allocation_code"] == "001.0001400"
    assert resolved["status"] == "resolved"
    assert resolved["source"] == "description_regex"
    assert fallback["allocation_code"] == "DIENTRO"
    assert fallback["source"] == "same_as_customs_code"
    assert ambiguous["allocation_code"] == ""
    assert ambiguous["status"] == "requires_review"
    assert ambiguous["reason"] == "multiple_regex_matches"


def test_client_config_rejects_invalid_regex():
    client = get_client("do-thanh")
    config = get_client_config(client)
    config["allocation_code"]["strategy"] = "description_regex"
    config["allocation_code"]["description_regex"] = "("

    with pytest.raises(ValueError, match="Invalid allocation code regex"):
        save_client_config(client, config)


def test_bcct_import_rows_create_immutable_co_stock_source_rows():
    client = get_client("do-thanh")
    upload = bcct_workbook([
        {"direction": "import", "declaration_no": "TK-001", "line_no": "1", "item_code": "MAT-001", "quantity": "100", "unit": "PCS"},
        {"direction": "export", "declaration_no": "XK-001", "line_no": "1", "item_code": "TP-001", "quantity": "10", "unit": "PCS"},
    ])

    process_bcct_upload(client, upload, "bcct.xlsx")

    workspace = get_source_workspace(client)
    import_rows = [row for row in workspace["bcct"]["published_rows"] if row["direction"] == "import"]
    assert len(import_rows) == 1
    assert import_rows[0]["import_row_id"].startswith("import-row-")
    assert len(workspace["co_stock_rows"]) == 1
    stock_row = workspace["co_stock_rows"][0]
    assert stock_row["source_row"] == import_rows[0]["import_row_id"]
    assert stock_row["source_line_ids"] == [import_rows[0]["import_row_id"]]
    assert stock_row["import_declaration_no"] == "TK-001"
    assert stock_row["line_no"] == "1"
    assert stock_row["customs_item_code"] == "MAT-001"
    assert stock_row["allocation_code"] == "MAT-001"
    assert stock_row["material_code"] == "MAT-001"
    assert stock_row["allocation_code_source"] == "same_as_customs_code"
    assert stock_row["allocation_code_status"] == "resolved"
    assert stock_row["available_qty"] == "100"
    assert stock_row["used_qty"] == "0"
    assert stock_row["remaining_qty"] == "100"


def test_co_stock_line_level_keeps_duplicate_codes_as_separate_lots():
    client = get_client("do-thanh")
    config = get_client_config(client)
    config["bcct"]["eligible_import_declaration_types"] = ["E11"]
    config["allocation_code"] = {
        "strategy": "description_regex",
        "description_regex": r"\(([A-Z0-9][A-Z0-9._/-]{3,})\)",
        "fallback": "same_as_customs_code",
    }
    config["co_stock"]["lot_policy"] = "line_level"
    save_client_config(client, config)
    upload = bcct_workbook([
        {"direction": "import", "declaration_type": "E11", "declaration_no": "TK-001", "line_no": "1", "item_code": "DIENTRO", "description": "DIENTRO#&Điện trở (001.0001400)", "quantity": "100", "unit": "PCS"},
        {"direction": "import", "declaration_type": "E11", "declaration_no": "TK-001", "line_no": "2", "item_code": "DIENTRO", "description": "DIENTRO#&Điện trở (001.0001400)", "quantity": "50", "unit": "PCS"},
    ])

    process_bcct_upload(client, upload, "bcct.xlsx")

    stock_rows = get_source_workspace(client)["co_stock_rows"]
    assert len(stock_rows) == 2
    assert [row["line_no"] for row in stock_rows] == ["1", "2"]
    assert {row["customs_item_code"] for row in stock_rows} == {"DIENTRO"}
    assert {row["allocation_code"] for row in stock_rows} == {"001.0001400"}


def test_co_stock_can_aggregate_within_one_declaration_without_losing_source_lines():
    client = get_client("do-thanh")
    config = get_client_config(client)
    config["bcct"]["eligible_import_declaration_types"] = ["E11"]
    config["allocation_code"] = {
        "strategy": "description_regex",
        "description_regex": r"\(([A-Z0-9][A-Z0-9._/-]{3,})\)",
        "fallback": "same_as_customs_code",
    }
    config["co_stock"]["lot_policy"] = "aggregate_by_declaration_and_allocation_code"
    save_client_config(client, config)
    upload = bcct_workbook([
        {"direction": "import", "declaration_type": "E11", "declaration_no": "TK-001", "line_no": "1", "item_code": "DIENTRO", "description": "DIENTRO#&Điện trở (001.0001400)", "quantity": "100", "unit": "PCS"},
        {"direction": "import", "declaration_type": "E11", "declaration_no": "TK-001", "line_no": "2", "item_code": "DIENTRO", "description": "DIENTRO#&Điện trở (001.0001400)", "quantity": "50", "unit": "PCS"},
        {"direction": "import", "declaration_type": "E11", "declaration_no": "TK-002", "line_no": "1", "item_code": "DIENTRO", "description": "DIENTRO#&Điện trở (001.0001400)", "quantity": "25", "unit": "PCS"},
    ])

    process_bcct_upload(client, upload, "bcct.xlsx")

    stock_rows = get_source_workspace(client)["co_stock_rows"]
    assert len(stock_rows) == 2
    grouped = [row for row in stock_rows if row["import_declaration_no"] == "TK-001"][0]
    assert grouped["line_no"] == "1,2"
    assert grouped["allocation_code"] == "001.0001400"
    assert grouped["available_qty"] == "150"
    assert len(grouped["source_line_ids"]) == 2


def test_co_stock_aggregation_handles_thousands_separators():
    client = get_client("do-thanh")
    config = get_client_config(client)
    config["bcct"]["eligible_import_declaration_types"] = ["E11"]
    config["co_stock"]["lot_policy"] = "aggregate_by_declaration_and_allocation_code"
    save_client_config(client, config)
    upload = bcct_workbook([
        {"direction": "import", "declaration_type": "E11", "declaration_no": "TK-001", "line_no": "1", "item_code": "MAT-001", "quantity": "1,000", "unit": "PCS"},
        {"direction": "import", "declaration_type": "E11", "declaration_no": "TK-001", "line_no": "2", "item_code": "MAT-001", "quantity": "250.5", "unit": "PCS"},
    ])

    process_bcct_upload(client, upload, "bcct.xlsx")

    stock_rows = get_source_workspace(client)["co_stock_rows"]
    assert len(stock_rows) == 1
    assert stock_rows[0]["available_qty"] == "1250.5"


def test_client_config_declaration_types_marks_excluded_import_stock_inactive():
    client = get_client("do-thanh")
    config = get_client_config(client)
    config["bcct"]["eligible_import_declaration_types"] = ["E11", "E15"]
    save_client_config(client, config)
    upload = bcct_workbook([
        {"direction": "import", "declaration_type": "E11", "declaration_no": "TK-001", "line_no": "1", "item_code": "MAT-001", "quantity": "100", "unit": "PCS"},
        {"direction": "import", "declaration_type": "E13", "declaration_no": "TK-002", "line_no": "1", "item_code": "TOOL-001", "quantity": "1", "unit": "PCS"},
        {"direction": "export", "declaration_type": "E42", "declaration_no": "XK-001", "line_no": "1", "item_code": "TP-001", "quantity": "10", "unit": "PCS"},
    ])

    process_bcct_upload(client, upload, "bcct.xlsx")

    stock_rows = get_source_workspace(client)["co_stock_rows"]
    assert [row["customs_item_code"] for row in stock_rows] == ["MAT-001", "TOOL-001"]
    active_row = [row for row in stock_rows if row["customs_item_code"] == "MAT-001"][0]
    inactive_row = [row for row in stock_rows if row["customs_item_code"] == "TOOL-001"][0]
    assert active_row["eligibility_status"] == "active"
    assert active_row["remaining_qty"] == "100"
    assert inactive_row["eligibility_status"] == "inactive"
    assert inactive_row["eligibility_reason"] == "excluded_by_declaration_type_config"
    assert inactive_row["available_qty"] == "1"
    assert inactive_row["remaining_qty"] == "0"


def test_config_change_deactivates_and_reactivates_existing_stock_candidate():
    client = get_client("do-thanh")
    config = get_client_config(client)
    config["bcct"]["eligible_import_declaration_types"] = ["E11", "E15"]
    save_client_config(client, config)
    upload = bcct_workbook([
        {"direction": "import", "declaration_type": "E15", "declaration_no": "TK-001", "line_no": "1", "item_code": "MAT-001", "quantity": "100", "unit": "PCS"},
    ])
    process_bcct_upload(client, upload, "bcct.xlsx")

    initial_stock = get_source_workspace(client)["co_stock_rows"][0]
    source_row = initial_stock["source_row"]
    assert initial_stock["eligibility_status"] == "active"

    config = get_client_config(client)
    config["bcct"]["eligible_import_declaration_types"] = ["E11"]
    save_client_config(client, config)
    deactivated_stock = get_source_workspace(client)["co_stock_rows"][0]
    assert deactivated_stock["source_row"] == source_row
    assert deactivated_stock["eligibility_status"] == "inactive"
    assert deactivated_stock["remaining_qty"] == "0"

    config = get_client_config(client)
    config["bcct"]["eligible_import_declaration_types"] = ["E11", "E15"]
    save_client_config(client, config)
    reactivated_stock = get_source_workspace(client)["co_stock_rows"][0]
    assert reactivated_stock["source_row"] == source_row
    assert reactivated_stock["eligibility_status"] == "active"
    assert reactivated_stock["remaining_qty"] == "100"


def test_co_stock_aggregation_keeps_active_and_inactive_candidates_separate():
    client = get_client("do-thanh")
    config = get_client_config(client)
    config["bcct"]["eligible_import_declaration_types"] = ["E11"]
    config["co_stock"]["lot_policy"] = "aggregate_by_declaration_and_allocation_code"
    save_client_config(client, config)
    upload = bcct_workbook([
        {"direction": "import", "declaration_type": "E11", "declaration_no": "TK-001", "line_no": "1", "item_code": "MAT-001", "quantity": "100", "unit": "PCS"},
        {"direction": "import", "declaration_type": "E13", "declaration_no": "TK-001", "line_no": "2", "item_code": "MAT-001", "quantity": "50", "unit": "PCS"},
    ])

    process_bcct_upload(client, upload, "bcct.xlsx")

    stock_rows = get_source_workspace(client)["co_stock_rows"]
    assert len(stock_rows) == 2
    assert {row["eligibility_status"] for row in stock_rows} == {"active", "inactive"}
    assert sorted(row["remaining_qty"] for row in stock_rows) == ["0", "100"]


def test_co_stock_declaration_type_filter_normalizes_uploaded_case():
    client = get_client("do-thanh")
    config = get_client_config(client)
    config["bcct"]["eligible_import_declaration_types"] = ["E11"]
    save_client_config(client, config)
    upload = bcct_workbook([
        {"direction": "", "declaration_type": "e11", "declaration_no": "TK-001", "line_no": "1", "item_code": "MAT-001", "quantity": "100", "unit": "PCS"},
    ])

    process_bcct_upload(client, upload, "bcct.xlsx")

    workspace = get_source_workspace(client)
    assert workspace["bcct"]["published_rows"][0]["declaration_type"] == "E11"
    assert [row["customs_item_code"] for row in workspace["co_stock_rows"]] == ["MAT-001"]
    assert workspace["co_stock_rows"][0]["eligibility_status"] == "active"


def test_unresolved_allocation_code_is_review_only_stock():
    client = get_client("do-thanh")
    config = get_client_config(client)
    config["bcct"]["eligible_import_declaration_types"] = ["E11"]
    config["allocation_code"] = {
        "strategy": "description_regex",
        "description_regex": r"\(([A-Z0-9][A-Z0-9._/-]{3,})\)",
        "fallback": "requires_review",
    }
    save_client_config(client, config)
    upload = bcct_workbook([
        {"direction": "import", "declaration_type": "E11", "declaration_no": "TK-001", "line_no": "1", "item_code": "DIENTRO", "description": "DIENTRO không có mã nội bộ", "quantity": "100", "unit": "PCS"},
    ])

    process_bcct_upload(client, upload, "bcct.xlsx")

    stock_row = get_source_workspace(client)["co_stock_rows"][0]
    assert stock_row["allocation_code_status"] == "requires_review"
    assert stock_row["allocation_code"] == ""
    assert stock_row["material_code"] == ""
    response = TestClient(app).get("/clients/do-thanh/co-stock")
    assert response.status_code == 200
    assert "Cần review" in response.text


def test_manual_review_lot_policy_keeps_stock_rows_unusable_until_review():
    client = get_client("do-thanh")
    config = get_client_config(client)
    config["bcct"]["eligible_import_declaration_types"] = ["E11"]
    config["co_stock"]["lot_policy"] = "manual_review"
    save_client_config(client, config)
    upload = bcct_workbook([
        {"direction": "import", "declaration_type": "E11", "declaration_no": "TK-001", "line_no": "1", "item_code": "MAT-001", "quantity": "100", "unit": "PCS"},
    ])

    process_bcct_upload(client, upload, "bcct.xlsx")

    stock_row = get_source_workspace(client)["co_stock_rows"][0]
    assert stock_row["allocation_code_status"] == "requires_review"
    assert stock_row["allocation_code_reason"] == "manual_stock_review"
    assert stock_row["material_code"] == ""


def test_export_bcct_view_filters_to_relevant_configured_types():
    client = TestClient(app)
    config = get_client_config(get_client("do-thanh"))
    config["bcct"]["relevant_export_declaration_types"] = ["E42"]
    save_client_config(get_client("do-thanh"), config)
    upload = bcct_workbook([
        {"direction": "export", "declaration_type": "E42", "declaration_no": "XK-001", "line_no": "1", "item_code": "TP-CO", "quantity": "10", "unit": "PCS"},
        {"direction": "export", "declaration_type": "B11", "declaration_no": "XK-002", "line_no": "1", "item_code": "TP-NORMAL", "quantity": "20", "unit": "PCS"},
    ])
    client.post(
        "/clients/do-thanh/bcct/upload",
        files={"file": ("bcct.xlsx", upload, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    response = client.get("/clients/do-thanh/bcct/exports")

    assert response.status_code == 200
    assert "TP-CO" in response.text
    assert "TP-NORMAL" not in response.text


def test_config_and_bcct_child_routes_render():
    client = TestClient(app)

    config_response = client.get("/clients/growatt/config")
    imports_response = client.get("/clients/growatt/bcct/imports")
    exports_response = client.get("/clients/growatt/bcct/exports")

    assert config_response.status_code == 200
    assert imports_response.status_code == 200
    assert exports_response.status_code == 200
    assert "Cấu hình công ty" in config_response.text
    assert "E11" in config_response.text
    assert "BCCT nhập khẩu" in imports_response.text
    assert "BCCT xuất khẩu" in exports_response.text


def test_co_case_snapshots_client_config_hash():
    client = TestClient(app)
    upload = bcct_workbook([
        {"direction": "import", "declaration_type": "E11", "declaration_no": "TK-001", "line_no": "1", "item_code": "MAT-001", "quantity": "100", "unit": "PCS"}
    ])
    client.post(
        "/clients/do-thanh/bcct/upload",
        files={"file": ("bcct.xlsx", upload, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    response = client.get("/clients/do-thanh/co-case")

    assert response.status_code == 200
    assert "Config snapshot" in response.text
    assert get_client_config(get_client("do-thanh"))["config_hash"] in response.text


def test_catalog_and_bcct_routes_offer_templates_and_upload_forms():
    client = TestClient(app)

    material_template = client.get("/clients/growatt/catalog/material-template.xlsx")
    bcct_template = client.get("/clients/growatt/bcct/template.xlsx")
    catalog_page = client.get("/clients/growatt/catalog")
    bcct_page = client.get("/clients/growatt/bcct")

    assert material_template.status_code == 200
    assert material_template.content.startswith(b"PK")
    assert bcct_template.status_code == 200
    assert bcct_template.content.startswith(b"PK")
    assert "Upload danh mục" in catalog_page.text
    assert "Upload BCCT" in bcct_page.text
    assert "append_or_review_by_transaction_key" in bcct_page.text


def test_catalog_upload_renders_selected_child_table():
    client = TestClient(app)
    content = create_material_catalog_template_workbook(get_client("growatt"))

    response = client.post(
        "/clients/do-thanh/catalog/upload",
        data={"catalog_type": "material", "upload_scope": "full_catalog"},
        files={"file": ("ds-nvl.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    assert "DS NVL DK HQ" in response.text
    assert "DEMO-NPL-001" in response.text
    assert "Mã nội bộ" not in response.text


def test_real_customs_material_catalog_xls_preserves_hq_schema_fields():
    rows = parse_catalog_workbook(customs_zip_entry("DANH MUC NPL DK HQ MOI.xls"), "material_catalog")

    assert rows[0]["customs_code"] == "DIOT"
    assert rows[0]["name"] == "Đi ốt"
    assert rows[0]["unit"] == "PCS"
    assert rows[0]["source_schema"] == "customs_material_catalog"
    assert rows[0]["source_row_number"] == 2
    assert rows[0]["raw_fields"]["Mã"] == "DIOT"
    assert "Mã biểu thuế NK" in rows[0]["raw_fields"]
    assert "import_tariff_code" in rows[0]


def test_real_customs_product_catalog_xls_preserves_hq_schema_fields():
    rows = parse_catalog_workbook(customs_zip_entry("DANH MUC SP DK HQ MOI.xls"), "product_catalog")

    assert rows[0]["product_code"] == "BIENTAN.01"
    assert rows[0]["hs_code"] == "85044090"
    assert rows[0]["unit"] == "PCS"
    assert rows[0]["source_schema"] == "customs_product_catalog"
    assert rows[0]["raw_fields"]["Mã định danh của lệnh SX"] == ""
    assert "production_order_identifier" in rows[0]


def test_real_customs_bcct_xlsx_reads_header_row_10_and_preserves_hq_fields():
    rows = parse_bcct_workbook(customs_zip_entry("BaoCaoHangChiTiet 01.01.2025 - 31.12.2025 08.01 or.xlsx"))

    assert len(rows) == 19898
    assert rows[0]["declaration_no"] == "106865355330"
    assert rows[0]["declaration_date"] == "2025-01-07"
    assert rows[0]["declaration_type"] == "E15"
    assert rows[0]["direction"] == "import"
    assert rows[0]["line_no"] == "1"
    assert rows[0]["item_code"] == "LKN-VO"
    assert rows[0]["quantity"] == "2000"
    assert rows[0]["unit"] == "PCS"
    assert rows[0]["origin_country"] == "VIETNAM"
    assert rows[0]["customs_value"] == "1288209000"
    assert rows[0]["invoice_ref"] == "00000020"
    assert rows[0]["raw_fields"]["Số To Khai"] == "106865355330"
    assert rows[0]["source_header_row"] == 10
    assert any(row["direction"] == "export" and row["declaration_type"] == "E42" for row in rows)


def test_bcct_upload_route_surfaces_correction_candidates():
    client = TestClient(app)
    first_upload = bcct_workbook([
        {"direction": "import", "declaration_no": "TK-001", "line_no": "1", "item_code": "MAT-001", "quantity": "100", "unit": "PCS"}
    ])
    changed_upload = bcct_workbook([
        {"direction": "import", "declaration_no": "TK-001", "line_no": "1", "item_code": "MAT-001", "quantity": "100", "unit": "KG"}
    ])
    client.post(
        "/clients/do-thanh/bcct/upload",
        files={"file": ("bcct.xlsx", first_upload, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    response = client.post(
        "/clients/do-thanh/bcct/upload",
        files={"file": ("bcct-conflict.xlsx", changed_upload, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    assert "correction_candidate" in response.text
    assert "TK-001" in response.text


def test_co_case_snapshots_reviewed_source_versions_without_correction_candidates():
    client = TestClient(app)
    upload = bcct_workbook([
        {"direction": "import", "declaration_no": "TK-001", "line_no": "1", "item_code": "MAT-001", "quantity": "100", "unit": "PCS"}
    ])
    client.post(
        "/clients/do-thanh/bcct/upload",
        files={"file": ("bcct.xlsx", upload, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    response = client.get("/clients/do-thanh/co-case")

    assert response.status_code == 200
    assert "Source evidence snapshot" in response.text
    assert "BCCT reviewed rows: 1" in response.text
    assert "correction_candidate" not in response.text
