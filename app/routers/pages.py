from __future__ import annotations


from fastapi import APIRouter
from app import co_auth, co_stock_eligibility, co_stock_materializer
from app.app_state_store import get_app_state_store
from app.co_case_store import acquire_origin_calculation_lock, co_case_is_completed, get_case_workspace, update_case_record
from app.demo_data import update_products_from_form
from app.portfolio import portfolio_service
from app.web.client_context import _data_hub_overview_context, client_case, client_context, resolve_client
from app.web.co_case_context import co_case_context, enrich_client_with_source_summary, origin_lock_actor
from app.web.deps import large_request_form, require_local_source_writes
from app.web.templating import templates
from app.workbook_io import WorkbookParseError, create_evidence_workbook, create_input_workbook, parse_input_workbook
from fastapi import File, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse


router = APIRouter()

@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
def config_context(client_id: str, **extra) -> dict:
    # /config only renders client identity + client_config knobs. It does NOT
    # need source_workspace / bom_workspace, so skip the full pagination that
    # client_context triggers (Johnson: ~65k BCCT rows over HTTP per render).
    lean = _data_hub_overview_context(client_id, "config", dh_path="")
    if lean is not None:
        lean.update(extra)
        return lean
    return client_context(client_id, "config", **extra)
@router.get("/", response_class=HTMLResponse)
@router.get("/clients", response_class=HTMLResponse)
async def clients(request: Request):
    clients = portfolio_service.clients()
    if co_auth.auth_required():
        clients = co_auth.filter_visible_clients(clients, co_auth.current_user(request))
    for client in clients:
        client["co_summary"] = _client_co_case_summary(client)
        client["monogram"] = _client_monogram(client.get("name", ""))
    portfolio_summary = {
        "clients": len(clients),
        "open": sum(c["co_summary"]["open"] for c in clients),
        "attention": sum(1 for c in clients if c["co_summary"]["open"]),
        "active_data": sum(1 for c in clients if (c.get("counts", {}) or {}).get("bcct")),
    }
    return templates.TemplateResponse(
        request=request,
        name="clients.html",
        context={"clients": clients, "portfolio_summary": portfolio_summary},
    )
def _client_monogram(name: str) -> str:
    parts = [p for p in name.split() if p[:1].isalnum()]
    if not parts:
        return (name[:2] or "?").upper()
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][:1] + parts[1][:1]).upper()
def _client_co_case_summary(client: dict) -> dict:
    # Cheap: get_case_workspace only loads the case state (JSON/PG), no Data Hub.
    try:
        cases = get_case_workspace(client, "").get("cases", [])
    except Exception:  # noqa: BLE001
        cases = []
    total = len(cases)
    open_count = sum(1 for case in cases if not co_case_is_completed(case))
    return {"total": total, "open": open_count, "done": total - open_count}
@router.get("/clients/{client_id}", response_class=HTMLResponse)
async def workspace(request: Request, client_id: str):
    # Workspace overview only renders client.counts tiles. Avoid the full
    # source_workspace + bom_service.workspace pagination here — those would
    # paginate every BCCT/material/BOM row from Data Hub on each render.
    return templates.TemplateResponse(
        request=request,
        name="workspace.html",
        context=client_overview_context(client_id),
    )
def _dashboard_case_view(case: dict) -> dict:
    """Cheap per-case status for the dashboard (mirrors co_case.html dossier_status)."""
    shipment = case.get("shipment") or {}
    invoice_no = (shipment.get("invoice_no") or "").strip()
    declarations = shipment.get("export_declaration_nos") or []
    bill_no = (shipment.get("bill_of_lading_no") or "").strip()
    completed = co_case_is_completed(case)
    if completed:
        status_key, label = "done", "Hoàn tất"
    elif not invoice_no and not declarations:
        status_key, label = "attention", "Thiếu invoice/tờ khai"
    elif not bill_no:
        status_key, label = "attention", "Thiếu B/L"
    elif not (case.get("products") or []):
        status_key, label = "attention", "Cần tính xuất xứ"
    else:
        status_key, label = "progress", "Đang xử lý"
    if invoice_no:
        reference = f"Invoice {invoice_no}"
    elif declarations:
        reference = "Tờ khai " + ", ".join(str(d) for d in declarations)
    else:
        reference = "Chưa nhập tham chiếu"
    return {
        "case_id": case.get("case_id"),
        "case_code": case.get("case_code") or case.get("case_id"),
        "title": case.get("title") or "",
        "destination_market": case.get("destination_market") or "",
        "reference": reference,
        "status_key": status_key,
        "status_label": label,
        "completed": completed,
        "updated_at": case.get("updated_at") or "",
    }


def client_overview_context(client_id: str) -> dict:
    client = resolve_client(client_id)
    try:
        source_summary, source_backend = portfolio_service.source_summary(client)
    except Exception:  # noqa: BLE001
        source_summary, source_backend = {
            "material_catalog": {"published_row_count": 0},
            "product_catalog": {"published_row_count": 0},
            "bcct": {"published_row_count": 0},
            "co_stock_row_count": 0,
        }, "n/a"
    bcct_rows = source_summary.get("bcct", {}).get("published_row_count", 0)
    # co_stock_row_count from source_summary is 0 in Data Hub mode; the
    # materialized snapshot is the accurate, cheap source (indexed row count).
    try:
        co_stock_rows = co_stock_materializer.row_count(client["id"])
    except Exception:  # noqa: BLE001
        co_stock_rows = source_summary.get("co_stock_row_count", 0)
    client = enrich_client_with_source_summary(client, source_summary)
    client["counts"]["co_stock"] = co_stock_rows
    client["counts"]["bom_lines"] = client["counts"].get("bom_lines", 0)
    try:
        sync_status = co_stock_materializer.compute_sync_status(client["id"], bcct_rows)
        last_refresh = co_stock_materializer.last_refresh_at(client["id"])
    except Exception:  # noqa: BLE001
        sync_status, last_refresh = {}, ""
    try:
        cases = get_case_workspace(client, "").get("cases", [])
    except Exception:  # noqa: BLE001
        cases = []
    co_cases = [_dashboard_case_view(case) for case in cases]
    return {
        "client": client,
        "active": "overview",
        "source_backend": source_backend,
        "source_versions": {
            "material_catalog": source_summary.get("material_catalog", {}).get("latest_version") or {},
            "product_catalog": source_summary.get("product_catalog", {}).get("latest_version") or {},
            "bcct": source_summary.get("bcct", {}).get("latest_version") or {},
        },
        "co_stock_sync_status": sync_status,
        "co_stock_last_refresh_at": last_refresh,
        "co_cases": co_cases,
        "co_recent": co_cases[:6],
        "co_open_count": sum(1 for case in co_cases if not case["completed"]),
        "co_attention_count": sum(1 for case in co_cases if case["status_key"] == "attention"),
    }
@router.get("/clients/{client_id}/config", response_class=HTMLResponse)
async def client_config(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="client_config.html",
        context=config_context(client_id),
    )
@router.post("/clients/{client_id}/config", response_class=HTMLResponse)
async def save_client_config_route(request: Request, client_id: str):
    client = resolve_client(client_id)
    form = await request.form()
    # Identity fields (legal_name / tax_code) are CO-side render metadata, not
    # source data — editable even when Data Hub source-mode is enabled. The
    # `co_stock_min_days_before_export` knob is also CO-side: it controls a
    # local CO eligibility predicate, not anything DH owns, so it persists to
    # the same local overlay without going through `require_local_source_writes`.
    if "legal_name" in form or "tax_code" in form or "co_stock_min_days_before_export" in form:
        client = dict(client)
        if "legal_name" in form:
            client["legal_name"] = str(form.get("legal_name") or "").strip()
        if "tax_code" in form:
            client["tax_code"] = str(form.get("tax_code") or "").strip()
        if "co_stock_min_days_before_export" in form:
            raw = str(form.get("co_stock_min_days_before_export") or "").strip()
            overrides = dict(client.get("co_stock_overrides") or {})
            if raw == "":
                overrides.pop("min_days_before_export", None)
            else:
                try:
                    n = int(raw)
                    if n < 0:
                        n = co_stock_eligibility.DEFAULT_MIN_GAP_DAYS
                except ValueError:
                    n = co_stock_eligibility.DEFAULT_MIN_GAP_DAYS
                overrides["min_days_before_export"] = n
            client["co_stock_overrides"] = overrides
        store = get_app_state_store()
        if store:
            store.upsert_client(client)
    require_local_source_writes()
    config = portfolio_service.get_client_config(client)
    config["co_stock"]["lot_policy"] = str(form.get("co_stock_lot_policy", "line_level"))
    config["allocation_code"]["strategy"] = str(form.get("allocation_code_strategy", "same_as_customs_code"))
    config["allocation_code"]["description_regex"] = str(form.get("description_regex", ""))
    config["allocation_code"]["fallback"] = str(form.get("allocation_code_fallback", "same_as_customs_code"))
    try:
        portfolio_service.save_client_config(client, config)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="client_config.html",
            status_code=400,
            context=config_context(client_id, error=str(exc)),
        )
    portfolio_service.refresh_client_indexes(client)
    return templates.TemplateResponse(
        request=request,
        name="client_config.html",
        context=config_context(client_id, message="Đã lưu cấu hình công ty."),
    )
@router.post("/clients/{client_id}/evaluate", response_class=HTMLResponse)
async def evaluate(request: Request, client_id: str):
    form = await large_request_form(request)
    case = update_products_from_form({key: str(value) for key, value in form.items()})
    case_id = case.get("persisted_case_id", "")
    if case_id:
        client = resolve_client(client_id)
        lock_result = acquire_origin_calculation_lock(client, case_id, origin_lock_actor(request))
        if not lock_result["acquired"]:
            return templates.TemplateResponse(
                request=request,
                name="co_case.html",
                status_code=409,
                context=co_case_context(
                    client_id,
                    case=case,
                    current_step="origin",
                    error=f"Chưa thể tính lại: hồ sơ {lock_result['lock'].get('case_code') or lock_result['lock'].get('case_id')} đang giữ phiên tính tồn cho khách hàng này.",
                    origin_calculation_blocked=True,
                    preserve_origin_products=True,
                ),
            )
    context = co_case_context(
        client_id,
        case=case,
        current_step="origin",
        message="Đã tính lại theo dữ liệu đang sửa.",
        preserve_origin_products=False,
    )
    if context["case"].get("persisted_case_id"):
        try:
            update_case_record(
                resolve_client(client_id),
                case if context.get("origin_demo_active") else context["case"],
            )
        except KeyError:
            pass
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=context,
    )
@router.post("/clients/{client_id}/upload", response_class=HTMLResponse)
async def upload_workbook(request: Request, client_id: str, file: UploadFile = File(...)):
    client = resolve_client(client_id)
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
    case["customer"] = client.get("legal_name") or client["name"]
    case["customer_legal_name"] = client.get("legal_name", "")
    case["customer_tax_code"] = client.get("tax_code", "")
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(client_id, case=case, current_step="origin", message=f"Đã parse {file.filename}."),
    )
@router.get("/clients/{client_id}/demo-input.xlsx")
async def download_demo_input(client_id: str):
    content = create_input_workbook(client_case(resolve_client(client_id)))
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{client_id}-demo-input.xlsx"'},
    )
@router.post("/clients/{client_id}/export")
async def export_evidence(request: Request, client_id: str):
    resolve_client(client_id)
    form = await large_request_form(request)
    case = update_products_from_form({key: str(value) for key, value in form.items()})
    content = create_evidence_workbook(case)
    filename = f"{case['case_code'] or 'co-case'}-evidence.xlsx"
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
