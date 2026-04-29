from __future__ import annotations

from pathlib import Path

from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.bom_store import (
    attach_case_bom_snapshot,
    create_bom_template_workbook,
    get_bom_workspace,
    process_bom_upload,
    update_bom_config,
)
from app.client_config_store import get_client_config, save_client_config
from app.co_case_store import (
    MAX_SUPPORTING_FILE_BYTES,
    build_case_criteria_rows,
    case_from_record,
    create_case_record,
    create_case_workbook,
    get_case_record,
    get_case_workspace,
    match_case_bcct_exports,
    safe_filename,
    save_supporting_file,
    update_case_record,
)
from app.co_forms import form_candidates_for_market
from app.demo_data import (
    SOURCE_NOTES,
    get_client,
    get_client_case,
    get_clients,
    update_products_from_form,
)
from app.source_store import (
    attach_case_source_snapshot,
    create_bcct_template_workbook,
    create_material_catalog_template_workbook,
    create_product_catalog_template_workbook,
    enrich_client_with_source_modules,
    get_source_workspace,
    load_module_state,
    process_bcct_upload,
    process_catalog_upload,
    source_summary_from_states,
)
from app.source_index_store import get_source_index_store, rebuild_source_index_if_configured
from app.table_view import build_table_view
from app.workbook_io import (
    WorkbookParseError,
    create_evidence_workbook,
    create_input_workbook,
    parse_input_workbook,
)

ROOT = Path(__file__).resolve().parent

THEME_COOKIE = "co_theme"
SUPPORTED_THEMES = {"light", "dark"}


def normalize_theme(value: str | None) -> str:
    return value if value in SUPPORTED_THEMES else "light"


def theme_context(request: Request) -> dict[str, str]:
    theme = normalize_theme(request.cookies.get(THEME_COOKIE))
    return {"theme": theme, "next_theme": "light" if theme == "dark" else "dark"}


app = FastAPI(title="Barry CO Demo")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

templates = Jinja2Templates(directory=ROOT / "templates", context_processors=[theme_context])

CATALOG_VIEWS = {
    "materials": {
        "module": "material_catalog",
        "title": "DS NVL DK HQ",
        "subtitle": "Nguyên vật liệu theo danh mục đăng ký hải quan.",
        "template_url": "material-template.xlsx",
        "template_label": "Tải template DS NVL",
        "columns": [
            {"key": "customs_code", "label": "Mã HQ", "class": "mono"},
            {"key": "name", "label": "Tên"},
            {"key": "unit", "label": "ĐVT", "class": "mono"},
            {"key": "hs_code", "label": "HS", "class": "mono"},
            {"key": "purpose", "label": "Mục đích"},
            {"key": "origin_default", "label": "Xuất xứ mặc định"},
            {"key": "status", "label": "Trạng thái"},
        ],
        "filters": [
            {"name": "status", "field": "status", "label": "Trạng thái"},
            {"name": "unit", "field": "unit", "label": "ĐVT"},
            {"name": "hs", "field": "hs_code", "label": "HS"},
            {"name": "purpose", "field": "purpose", "label": "Mục đích"},
        ],
        "summary_fields": [
            {"field": "status", "label": "Trạng thái"},
            {"field": "unit", "label": "ĐVT"},
        ],
        "default_sort": "customs_code",
    },
    "products": {
        "module": "product_catalog",
        "title": "DS SP DK HQ",
        "subtitle": "Thành phẩm theo danh mục đăng ký hải quan.",
        "template_url": "product-template.xlsx",
        "template_label": "Tải template DS SP",
        "columns": [
            {"key": "product_code", "label": "Mã SP", "class": "mono"},
            {"key": "name", "label": "Tên"},
            {"key": "unit", "label": "ĐVT", "class": "mono"},
            {"key": "hs_code", "label": "HS", "class": "mono"},
            {"key": "purpose", "label": "Mục đích"},
            {"key": "status", "label": "Trạng thái"},
        ],
        "filters": [
            {"name": "status", "field": "status", "label": "Trạng thái"},
            {"name": "unit", "field": "unit", "label": "ĐVT"},
            {"name": "hs", "field": "hs_code", "label": "HS"},
            {"name": "purpose", "field": "purpose", "label": "Mục đích"},
        ],
        "summary_fields": [
            {"field": "status", "label": "Trạng thái"},
            {"field": "unit", "label": "ĐVT"},
        ],
        "default_sort": "product_code",
    },
}

BCCT_COLUMNS = [
    {"key": "coverage_period", "label": "Kỳ"},
    {"key": "declaration_no", "label": "Tờ khai", "class": "mono"},
    {"key": "line_no", "label": "STT", "class": "mono"},
    {"key": "declaration_type", "label": "LH", "class": "mono"},
    {"key": "direction_label", "label": "Luồng"},
    {"key": "item_code", "label": "Mã hàng", "class": "mono"},
    {"key": "hs_code", "label": "HS", "class": "mono"},
    {"key": "quantity", "label": "Số lượng", "class": "num"},
    {"key": "unit", "label": "ĐVT", "class": "mono"},
    {"key": "customs_value", "label": "Trị giá", "class": "num"},
    {"key": "invoice_ref", "label": "Hóa đơn", "class": "mono"},
]

CO_CASE_WORKFLOW_STEPS = [
    {
        "key": "shipment",
        "label": "Lô hàng",
        "short_label": "1",
        "description": "Thông tin shipment, invoice, B/L và thị trường.",
    },
    {
        "key": "documents",
        "label": "Chứng từ",
        "short_label": "2",
        "description": "Upload invoice, vận đơn, packing list và bằng chứng kèm theo.",
    },
    {
        "key": "exports",
        "label": "Tờ khai xuất",
        "short_label": "3",
        "description": "Đối chiếu tờ khai xuất đã review theo invoice.",
    },
    {
        "key": "guidance",
        "label": "Form & PSR",
        "short_label": "4",
        "description": "Gợi ý form, thông tư và trạng thái tra cứu quy tắc.",
    },
    {
        "key": "origin",
        "label": "Xuất xứ",
        "short_label": "5",
        "description": "Chạy RVC/CTSH và xem preview phân bổ.",
    },
    {
        "key": "review",
        "label": "Review & xuất",
        "short_label": "6",
        "description": "Kiểm tra dossier và xuất workbook.",
    },
]
CO_CASE_WORKFLOW_STEP_KEYS = {step["key"] for step in CO_CASE_WORKFLOW_STEPS}

CO_STOCK_COLUMNS = [
    {"key": "source_row", "label": "Dòng nguồn", "class": "mono"},
    {"key": "import_declaration_no", "label": "Tờ khai nhập", "class": "mono"},
    {"key": "line_no", "label": "STT", "class": "mono"},
    {"key": "declaration_type", "label": "LH", "class": "mono"},
    {"key": "customs_item_code", "label": "Mã HQ", "class": "mono"},
    {"key": "allocation_code", "label": "Mã phân bổ", "class": "mono"},
    {"key": "available_qty", "label": "Tồn CO", "class": "num"},
    {"key": "used_qty", "label": "Đã dùng", "class": "num"},
    {"key": "remaining_qty", "label": "Còn lại", "class": "num"},
    {"key": "status_label", "label": "Trạng thái"},
    {"key": "stock_reason_label", "label": "Lý do"},
]


@app.post("/settings/theme")
async def set_theme(theme: str = Form("light"), next_url: str = Form("/clients")):
    target = next_url if next_url.startswith("/") and not next_url.startswith("//") else "/clients"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        THEME_COOKIE,
        normalize_theme(theme),
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        samesite="lax",
    )
    return response


def client_context(client_id: str, active: str, **extra):
    client = enrich_client_with_source_modules(get_client(client_id))
    case = extra.pop("case", get_client_case(client_id))
    source_workspace = get_source_workspace(client)
    bom_workspace = get_bom_workspace(client)
    case = attach_case_bom_snapshot(case, bom_workspace)
    case = attach_case_source_snapshot(case, source_workspace)
    return {
        "client": client,
        "case": case,
        "active": active,
        "bom_workspace": bom_workspace,
        "source_workspace": source_workspace,
        "client_config": source_workspace["client_config"],
        "case_workspace": extra.pop("case_workspace", get_case_workspace(client)),
        "form_candidates": extra.pop("form_candidates", form_candidates_for_market(case.get("destination_market", ""))),
        "invoice_matches": extra.pop("invoice_matches", []),
        "criteria_rows": extra.pop("criteria_rows", []),
        "source_notes": SOURCE_NOTES,
        **extra,
    }


def co_case_light_context(client_id: str, case: dict, current_step: str, **extra) -> dict:
    client = get_client(client_id)
    source_context = co_case_source_context(client, case)
    source_summary = source_context["source_summary"]
    bom_workspace = get_bom_workspace(client) if current_step == "origin" else minimal_bom_workspace()
    client = enrich_client_with_source_summary(client, source_summary)
    case = attach_case_source_summary_snapshot(case, source_summary)
    if current_step == "origin":
        case = attach_case_bom_snapshot(case, bom_workspace)
    context = {
        "client": client,
        "case": case,
        "active": "co-case",
        "bom_workspace": bom_workspace,
        "source_workspace": {},
        "client_config": source_summary["client_config"],
        "case_workspace": extra.pop("case_workspace"),
        "form_candidates": extra.pop("form_candidates"),
        "invoice_matches": source_context["invoice_matches"],
        "criteria_rows": extra.pop("criteria_rows"),
        "source_notes": SOURCE_NOTES,
        "source_backend": source_context["source_backend"],
        **extra,
    }
    context["co_case_active_step"] = current_step
    context["co_case_steps"] = co_case_workflow_steps(client_id, context["case"], current_step)
    return context


def co_case_source_context(client: dict, case: dict) -> dict:
    client_config = get_client_config(client)
    store = get_source_index_store()
    invoice_no = case.get("shipment", {}).get("invoice_no", "")
    if store and store.has_client(client["id"]):
        relevant_types = client_config.get("bcct", {}).get("relevant_export_declaration_types", [])
        return {
            "source_backend": "postgres",
            "source_summary": store.source_summary(client["id"], client_config),
            "invoice_matches": store.match_bcct_exports(client["id"], invoice_no, relevant_types),
        }

    material = load_module_state(client, "material_catalog")
    product = load_module_state(client, "product_catalog")
    bcct = load_module_state(client, "bcct")
    return {
        "source_backend": "files",
        "source_summary": source_summary_from_states(material, product, bcct, client_config),
        "invoice_matches": match_case_bcct_exports(
            case,
            {"bcct": {"published_rows": bcct["published_rows"]}},
            client_config,
        ),
    }


def enrich_client_with_source_summary(client: dict, source_summary: dict) -> dict:
    client["counts"] = {
        **client.get("counts", {}),
        "materials": source_summary["material_catalog"]["published_row_count"],
        "products": source_summary["product_catalog"]["published_row_count"],
        "bcct": source_summary["bcct"]["published_row_count"],
        "co_stock": source_summary["co_stock_row_count"],
    }
    return client


def attach_case_source_summary_snapshot(case: dict, source_summary: dict) -> dict:
    material = source_summary["material_catalog"].get("latest_version") or {}
    product = source_summary["product_catalog"].get("latest_version") or {}
    bcct = source_summary["bcct"].get("latest_version") or {}
    case["source_snapshot"] = {
        "material_catalog_version_id": material.get("version_id", ""),
        "material_catalog_version_no": material.get("version_no", ""),
        "product_catalog_version_id": product.get("version_id", ""),
        "product_catalog_version_no": product.get("version_no", ""),
        "bcct_version_id": bcct.get("version_id", ""),
        "bcct_version_no": bcct.get("version_no", ""),
        "bcct_reviewed_row_count": source_summary["bcct"].get("reviewed_row_count", 0),
        "correction_candidate_count": source_summary["bcct"].get("correction_candidate_count", 0),
        "client_config_version": source_summary["client_config"].get("config_version", ""),
        "client_config_hash": source_summary["client_config"].get("config_hash", ""),
    }
    return case


def minimal_bom_workspace() -> dict:
    return {
        "versions": [],
        "product_versions": [],
        "product_version_options_by_code": {},
        "latest_version": {},
    }


def catalog_table_context(request: Request, client_id: str, view_name: str, **extra) -> dict:
    view = CATALOG_VIEWS[view_name]
    context = client_context(client_id, "catalog", **extra)
    rows = context["source_workspace"][view["module"]]["published_rows"]
    context["catalog_view"] = {**view, "name": view_name}
    context["source_table"] = build_table_view(
        rows,
        columns=view["columns"],
        query=request.query_params,
        filters=view["filters"],
        summary_fields=view["summary_fields"],
        default_sort=view["default_sort"],
    )
    return context


def bcct_table_context(request: Request, client_id: str, direction: str | None = None, **extra) -> dict:
    context = client_context(client_id, "bcct", **extra)
    rows = [bcct_table_row(row) for row in context["source_workspace"]["bcct"]["published_rows"]]
    if direction:
        rows = [row for row in rows if row.get("direction") == direction]
    if direction == "export":
        relevant_types = set(context["client_config"]["bcct"].get("relevant_export_declaration_types", []))
        if relevant_types:
            rows = [row for row in rows if row.get("declaration_type") in relevant_types]
    context["bcct_view"] = direction or "all"
    title_by_direction = {"import": "BCCT nhập khẩu", "export": "BCCT xuất khẩu"}
    context["bcct_title"] = title_by_direction.get(direction, "BCCT nhập khẩu / xuất khẩu")
    context["source_table"] = build_table_view(
        rows,
        columns=BCCT_COLUMNS,
        query=request.query_params,
        filters=[
            {
                "name": "direction",
                "field": "direction",
                "label": "Luồng",
                "options": [
                    {"value": "import", "label": "Nhập khẩu"},
                    {"value": "export", "label": "Xuất khẩu"},
                ],
            },
            {"name": "type", "field": "declaration_type", "label": "Loại hình"},
            {"name": "hs", "field": "hs_code", "label": "HS"},
            {"name": "origin", "field": "origin_country", "label": "Xuất xứ"},
        ],
        summary_fields=[
            {"field": "direction_label", "label": "Luồng"},
            {"field": "declaration_type", "label": "Loại hình"},
        ],
        default_sort="declaration_no",
    )
    return context


def co_stock_table_context(request: Request, client_id: str) -> dict:
    context = client_context(client_id, "co-stock")
    rows = [co_stock_table_row(row) for row in context["client"]["co_stock"]]
    context["source_table"] = build_table_view(
        rows,
        columns=CO_STOCK_COLUMNS,
        query=request.query_params,
        filters=[
            {
                "name": "status",
                "field": "status",
                "label": "Trạng thái",
                "options": [
                    {"value": "available", "label": "Khả dụng"},
                    {"value": "review_required", "label": "Cần review"},
                    {"value": "inactive", "label": "Không dùng"},
                    {"value": "depleted", "label": "Hết tồn"},
                ],
            }
        ],
        summary_fields=[
            {"field": "status_label", "label": "Trạng thái"},
            {"field": "declaration_type", "label": "Loại hình"},
        ],
        default_sort="import_declaration_no",
    )
    return context


def co_case_context(client_id: str, case_id: str = "", current_step: str = "index", **extra) -> dict:
    client = get_client(client_id)
    case = extra.pop("case", None)
    effective_case_id = case_id or (case or {}).get("persisted_case_id", "")
    workspace = get_case_workspace(client, effective_case_id)
    record = get_case_record(client, effective_case_id) if effective_case_id else None
    if case is None:
        case = get_client_case(client_id)
        if record:
            case = case_from_record(case, client, record)
    elif record:
        case.setdefault("persisted_case_id", record["case_id"])
        case["supporting_files"] = [dict(file_row) for file_row in record.get("supporting_files", [])]
    case.setdefault("persisted_case_id", "")
    case.setdefault("shipment", {"invoice_no": "", "bill_of_lading_no": ""})
    case["shipment"].setdefault("invoice_no", "")
    case["shipment"].setdefault("bill_of_lading_no", "")
    case.setdefault("supporting_files", [])
    form_candidates = form_candidates_for_market(case.get("destination_market", ""))
    criteria_rows = build_case_criteria_rows(case, form_candidates)
    return co_case_light_context(
        client_id,
        case=case,
        current_step=current_step,
        case_workspace=workspace,
        form_candidates=form_candidates,
        criteria_rows=criteria_rows,
        **extra,
    )


def co_case_workflow_steps(client_id: str, case: dict, current_step: str) -> list[dict]:
    case_id = case.get("persisted_case_id", "")
    base_url = f"/clients/{client_id}/co-case/{case_id}" if case_id else ""
    steps = []
    for step in CO_CASE_WORKFLOW_STEPS:
        href = base_url if step["key"] == "shipment" else f"{base_url}/{step['key']}"
        steps.append({
            **step,
            "href": href,
            "active": current_step == step["key"],
            "status": co_case_step_status(case, step["key"]),
        })
    return steps


def co_case_step_status(case: dict, step_key: str) -> str:
    shipment = case.get("shipment", {})
    if step_key == "shipment":
        return "ready" if shipment.get("invoice_no") and case.get("destination_market") else "todo"
    if step_key == "documents":
        return "ready" if case.get("supporting_files") else "todo"
    if step_key == "exports":
        return "review"
    if step_key == "guidance":
        return "review"
    if step_key == "origin":
        return "preview"
    return "todo"


def config_context(client_id: str, **extra) -> dict:
    context = client_context(client_id, "config", **extra)
    return context


def bcct_table_row(row: dict) -> dict:
    direction = row.get("direction", "")
    return {
        **row,
        "direction_label": "Nhập khẩu" if direction == "import" else "Xuất khẩu",
    }


def co_stock_table_row(row: dict) -> dict:
    remaining_qty = str(row.get("remaining_qty", ""))
    if row.get("eligibility_status") == "inactive":
        status = "inactive"
    elif row.get("allocation_code_status") != "resolved":
        status = "review_required"
    else:
        status = "depleted" if remaining_qty in {"", "0", "0.0", "0.00"} else "available"
    return {
        **row,
        "status": status,
        "status_label": {
            "available": "Khả dụng",
            "depleted": "Hết tồn",
            "inactive": "Không dùng",
            "review_required": "Cần review",
        }[status],
        "stock_reason_label": stock_reason_label(row, status),
    }


def stock_reason_label(row: dict, status: str) -> str:
    if status == "inactive" and row.get("eligibility_reason") == "excluded_by_declaration_type_config":
        return "Loại hình không active trong config"
    if status == "review_required":
        return row.get("allocation_code_reason") or "Cần review mã phân bổ"
    return row.get("eligibility_reason", "")


@app.get("/", response_class=HTMLResponse)
@app.get("/clients", response_class=HTMLResponse)
async def clients(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="clients.html",
        context={"clients": get_clients()},
    )


@app.get("/clients/{client_id}", response_class=HTMLResponse)
async def workspace(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="workspace.html",
        context=client_context(client_id, "overview"),
    )


@app.get("/clients/{client_id}/catalog", response_class=HTMLResponse)
async def catalog(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="catalog.html",
        context=client_context(client_id, "catalog"),
    )


@app.get("/clients/{client_id}/catalog/materials", response_class=HTMLResponse)
async def material_catalog(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="catalog_table.html",
        context=catalog_table_context(request, client_id, "materials"),
    )


@app.get("/clients/{client_id}/catalog/products", response_class=HTMLResponse)
async def product_catalog(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="catalog_table.html",
        context=catalog_table_context(request, client_id, "products"),
    )


@app.get("/clients/{client_id}/catalog/material-template.xlsx")
async def download_material_catalog_template(client_id: str):
    content = create_material_catalog_template_workbook(get_client(client_id))
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{client_id}-ds-nvl-template.xlsx"'},
    )


@app.get("/clients/{client_id}/catalog/product-template.xlsx")
async def download_product_catalog_template(client_id: str):
    content = create_product_catalog_template_workbook(get_client(client_id))
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{client_id}-ds-sp-template.xlsx"'},
    )


@app.post("/clients/{client_id}/catalog/upload", response_class=HTMLResponse)
async def upload_catalog_workbook(
    request: Request,
    client_id: str,
    file: UploadFile = File(...),
    catalog_type: str = Form("material"),
    upload_scope: str = Form("full_catalog"),
):
    client = get_client(client_id)
    result = process_catalog_upload(
        client,
        catalog_type,
        await file.read(),
        file.filename or "catalog.xlsx",
        upload_scope,
    )
    status_code = 400 if result["status"] == "failed" else 200
    view_name = "products" if catalog_type == "product" else "materials"
    return templates.TemplateResponse(
        request=request,
        name="catalog_table.html",
        status_code=status_code,
        context=catalog_table_context(
            request,
            client_id,
            view_name,
            catalog_result=result,
            message=result["message"] if status_code == 200 else "",
            error=result["message"] if status_code == 400 else "",
        ),
    )


@app.get("/clients/{client_id}/bom", response_class=HTMLResponse)
async def bom(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="bom.html",
        context=client_context(client_id, "bom"),
    )


@app.post("/clients/{client_id}/bom/config", response_class=HTMLResponse)
async def save_bom_config(request: Request, client_id: str):
    client = get_client(client_id)
    form = await request.form()
    update_bom_config(client, {key: str(value) for key, value in form.items()})
    return templates.TemplateResponse(
        request=request,
        name="bom.html",
        context=client_context(client_id, "bom", message="Đã lưu cấu hình BOM cho công ty này."),
    )


@app.get("/clients/{client_id}/config", response_class=HTMLResponse)
async def client_config(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="client_config.html",
        context=config_context(client_id),
    )


@app.post("/clients/{client_id}/config", response_class=HTMLResponse)
async def save_client_config_route(request: Request, client_id: str):
    client = get_client(client_id)
    form = await request.form()
    config = get_client_config(client)
    config["bcct"]["eligible_import_declaration_types"] = str(form.get("eligible_import_declaration_types", ""))
    config["bcct"]["relevant_export_declaration_types"] = str(form.get("relevant_export_declaration_types", ""))
    config["co_stock"]["lot_policy"] = str(form.get("co_stock_lot_policy", "line_level"))
    config["allocation_code"]["strategy"] = str(form.get("allocation_code_strategy", "same_as_customs_code"))
    config["allocation_code"]["description_regex"] = str(form.get("description_regex", ""))
    config["allocation_code"]["fallback"] = str(form.get("allocation_code_fallback", "same_as_customs_code"))
    try:
        save_client_config(client, config)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="client_config.html",
            status_code=400,
            context=config_context(client_id, error=str(exc)),
        )
    rebuild_source_index_if_configured(client)
    return templates.TemplateResponse(
        request=request,
        name="client_config.html",
        context=config_context(client_id, message="Đã lưu cấu hình công ty."),
    )


@app.post("/clients/{client_id}/bom/upload", response_class=HTMLResponse)
async def upload_bom_workbook(
    request: Request,
    client_id: str,
    file: UploadFile = File(...),
    upload_mode: str = Form("direct_bom"),
    upload_scope: str = Form(""),
    accept_review_required: str = Form(""),
):
    client = get_client(client_id)
    result = process_bom_upload(
        client,
        await file.read(),
        file.filename or "bom.xlsx",
        upload_mode,
        upload_scope or None,
        accept_review_required == "on",
    )
    status_code = 400 if result["status"] == "failed" else 200
    return templates.TemplateResponse(
        request=request,
        name="bom.html",
        status_code=status_code,
        context=client_context(
            client_id,
            "bom",
            bom_result=result,
            message=result["message"] if status_code == 200 else "",
            error=result["message"] if status_code == 400 else "",
        ),
    )


@app.get("/clients/{client_id}/bom/template.xlsx")
async def download_bom_template(client_id: str):
    content = create_bom_template_workbook(get_client(client_id))
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{client_id}-bom-template.xlsx"'},
    )


@app.get("/clients/{client_id}/co-stock", response_class=HTMLResponse)
async def co_stock(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="co_stock.html",
        context=co_stock_table_context(request, client_id),
    )


@app.get("/clients/{client_id}/bcct", response_class=HTMLResponse)
async def bcct(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="bcct.html",
        context=bcct_table_context(request, client_id),
    )


@app.get("/clients/{client_id}/bcct/imports", response_class=HTMLResponse)
async def bcct_imports(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="bcct.html",
        context=bcct_table_context(request, client_id, "import"),
    )


@app.get("/clients/{client_id}/bcct/exports", response_class=HTMLResponse)
async def bcct_exports(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="bcct.html",
        context=bcct_table_context(request, client_id, "export"),
    )


@app.get("/clients/{client_id}/bcct/template.xlsx")
async def download_bcct_template(client_id: str):
    content = create_bcct_template_workbook(get_client(client_id))
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{client_id}-bcct-template.xlsx"'},
    )


@app.post("/clients/{client_id}/bcct/upload", response_class=HTMLResponse)
async def upload_bcct_workbook(request: Request, client_id: str, file: UploadFile = File(...)):
    client = get_client(client_id)
    result = process_bcct_upload(client, await file.read(), file.filename or "bcct.xlsx")
    status_code = 400 if result["status"] == "failed" else 200
    return templates.TemplateResponse(
        request=request,
        name="bcct.html",
        status_code=status_code,
        context=bcct_table_context(
            request,
            client_id,
            bcct_result=result,
            message=result["message"] if status_code == 200 else "",
            error=result["message"] if status_code == 400 else "",
        ),
    )


@app.get("/clients/{client_id}/co-case", response_class=HTMLResponse)
async def co_case(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(client_id),
    )


@app.post("/clients/{client_id}/co-case/create")
async def create_co_case(request: Request, client_id: str):
    client = get_client(client_id)
    form = await request.form()
    record = create_case_record(client, {key: str(value) for key, value in form.items()})
    return RedirectResponse(f"/clients/{client_id}/co-case/{record['case_id']}", status_code=303)


@app.post("/clients/{client_id}/co-case/{case_id}/shipment")
async def update_co_case_shipment(request: Request, client_id: str, case_id: str):
    form = {key: str(value) for key, value in (await request.form()).items()}
    update_case_record(
        get_client(client_id),
        {
            **form,
            "id": case_id,
            "persisted_case_id": case_id,
            "shipment": {
                "invoice_no": form.get("invoice_no", ""),
                "bill_of_lading_no": form.get("bill_of_lading_no", ""),
            },
        },
    )
    return RedirectResponse(f"/clients/{client_id}/co-case/{case_id}", status_code=303)


@app.get("/clients/{client_id}/co-case/{case_id}", response_class=HTMLResponse)
async def co_case_detail(request: Request, client_id: str, case_id: str):
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(client_id, case_id, "shipment"),
    )


@app.get("/clients/{client_id}/co-case/{case_id}/{step}", response_class=HTMLResponse)
async def co_case_step(request: Request, client_id: str, case_id: str, step: str):
    if step not in CO_CASE_WORKFLOW_STEP_KEYS:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(client_id, case_id, step),
    )


@app.post("/clients/{client_id}/co-case/{case_id}/supporting-files")
async def upload_co_case_supporting_file(
    request: Request,
    client_id: str,
    case_id: str,
    file: UploadFile = File(...),
    document_slot: str = Form("other"),
    invoice_no: str = Form(""),
    bill_of_lading_no: str = Form(""),
):
    client = get_client(client_id)
    content = await file.read(MAX_SUPPORTING_FILE_BYTES + 1)
    try:
        save_supporting_file(
            client,
            case_id,
            content,
            file.filename or "supporting-file",
            document_slot,
            invoice_no,
            bill_of_lading_no,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=400,
            context=co_case_context(client_id, case_id, "documents", error=str(exc)),
        )
    return RedirectResponse(f"/clients/{client_id}/co-case/{case_id}/documents", status_code=303)


@app.post("/clients/{client_id}/co-case/{case_id}/export")
async def export_co_case_workbook(client_id: str, case_id: str):
    context = co_case_context(client_id, case_id)
    content = create_case_workbook(
        context["case"],
        context["form_candidates"],
        context["invoice_matches"],
        context["criteria_rows"],
    )
    filename = safe_filename(f"{context['case']['case_code'] or 'co-case'}-dossier.xlsx")
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/clients/{client_id}/evaluate", response_class=HTMLResponse)
async def evaluate(request: Request, client_id: str):
    form = await request.form()
    case = update_products_from_form({key: str(value) for key, value in form.items()})
    if case.get("persisted_case_id"):
        try:
            update_case_record(get_client(client_id), case)
        except KeyError:
            pass
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(client_id, case=case, current_step="origin", message="Đã tính lại theo dữ liệu đang sửa."),
    )


@app.post("/clients/{client_id}/upload", response_class=HTMLResponse)
async def upload_workbook(request: Request, client_id: str, file: UploadFile = File(...)):
    client = get_client(client_id)
    content = await file.read()
    try:
        case = parse_input_workbook(content, source_label=f"Upload: {file.filename}")
    except WorkbookParseError as exc:
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=400,
            context=co_case_context(client_id, error=str(exc)),
        )
    case["customer"] = client["name"]
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(client_id, case=case, current_step="origin", message=f"Đã parse {file.filename}."),
    )


@app.get("/clients/{client_id}/demo-input.xlsx")
async def download_demo_input(client_id: str):
    content = create_input_workbook(get_client_case(client_id))
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{client_id}-demo-input.xlsx"'},
    )


@app.post("/clients/{client_id}/export")
async def export_evidence(request: Request, client_id: str):
    get_client(client_id)
    form = await request.form()
    case = update_products_from_form({key: str(value) for key, value in form.items()})
    content = create_evidence_workbook(case)
    filename = f"{case['case_code'] or 'co-case'}-evidence.xlsx"
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
