from __future__ import annotations


from fastapi import APIRouter
from app import changelog, co_auth, co_stock_eligibility, co_stock_materializer
from app import version as appver
from app.bcct_aggregates import declaration_type_counts, excluded_types_with_rows
from app.origin_country import ISO_TO_VI, RAW_TO_ISO, country_label_vi, is_unknown_origin, normalize_column9_mode
from app.web.co_case_context import bang_ke_settings
from app.app_state_store import get_app_state_store
from app.co_case_store import co_case_is_completed, co_case_status_view, get_case_workspace, update_case_record
from app.demo_data import update_products_from_form
from app.portfolio import portfolio_service
from app.web.client_context import _data_hub_overview_context, client_case, client_context, resolve_client
from app.web.co_case_context import co_case_context, enrich_client_with_source_summary
from app.web.deps import large_request_form, require_local_source_writes
from app.web.templating import templates
from app.workbook_io import WorkbookParseError, create_evidence_workbook, create_input_workbook, parse_input_workbook
from fastapi import File, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse


router = APIRouter()

@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
@router.get("/version")
async def version() -> dict[str, str]:
    # Unauthenticated like /healthz (leaks nothing sensitive) — sister apps +
    # monitoring poll it to assert which CO build they're talking to.
    return {"app": "barry-co", **appver.version_info()}
@router.get("/whats-new", response_class=HTMLResponse)
async def whats_new(request: Request):
    # Auth-gated in prod via co_auth.should_guard_path; open in local/no-auth
    # mode. Renders the curated CHANGELOG.md + the running version.
    return templates.TemplateResponse(
        request=request,
        name="whats-new.html",
        context={"releases": changelog.load_changelog()},
    )
def config_context(client_id: str, **extra) -> dict:
    # /config only renders client identity + client_config knobs. It does NOT
    # need source_workspace / bom_workspace, so skip the full pagination that
    # client_context triggers (Johnson: ~65k BCCT rows over HTTP per render).
    lean = _data_hub_overview_context(client_id, "config", dh_path="")
    context = lean if lean is not None else client_context(client_id, "config", **extra)
    if lean is not None:
        context.update(extra)
    # Per-declaration-type BCCT counts from the materialized tồn snapshot (cheap,
    # local) so a filtering mistake is visible before it produces false shortages.
    context.update(_declaration_type_count_context(context.get("client") or {}, context.get("client_config") or {}))
    return context
def _declaration_type_count_context(client: dict, client_config: dict) -> dict:
    stock_rows = co_stock_materializer.read_co_stock_rows_cached(str(client.get("id") or ""))
    counts = declaration_type_counts(stock_rows)
    eligible = (client_config.get("bcct") or {}).get("eligible_import_declaration_types") or []
    return {
        "bcct_declaration_type_counts": counts,
        "bcct_excluded_type_rows": excluded_types_with_rows(counts, eligible),
        "bang_ke_settings": bang_ke_settings(client),
        "origin_country_mapping": [
            {"raw": raw, "iso": iso, "label_vi": ISO_TO_VI.get(iso, "")}
            for raw, iso in sorted(RAW_TO_ISO.items())
        ],
        "origin_country_unmapped": _unmapped_origin_strings(stock_rows),
    }
def _unmapped_origin_strings(stock_rows: list[dict]) -> list[str]:
    seen: list[str] = []
    for row in stock_rows or []:
        raw = str(row.get("origin_country") or "").strip()
        if not raw or is_unknown_origin(raw):
            continue
        if not country_label_vi(raw)[1] and raw not in seen:
            seen.append(raw)
    return sorted(seen)
def _apply_client_column9_mode_flip(client: dict) -> str:
    """Client-default column-9 mode changed (ticket #10): sweep the client's
    cases, mark mismatched CALCULATED sheets stale, never touch locked ones
    (they get the mismatch chip at render time). Returns a message suffix
    naming the consequences."""
    from app.web.co_case_context import apply_column9_mode_flip

    stale_total = 0
    locked_total = 0
    failed_total = 0
    try:
        cases = get_case_workspace(client).get("cases") or []
    except Exception:  # noqa: BLE001
        cases = []
    for record in cases:
        case_id = str(record.get("case_id") or "")
        if not case_id:
            continue
        try:
            from app.co_case_store import case_from_record
            case = case_from_record({}, client, record)
            flip = apply_column9_mode_flip(case, client)
            if flip["stale_codes"]:
                update_case_record(client, flip["case"])
            stale_total += len(flip["stale_codes"])
            locked_total += len(flip["locked_codes"])
        except Exception:  # noqa: BLE001
            failed_total += 1
            continue
    if not stale_total and not locked_total and not failed_total:
        return ""
    parts = []
    if stale_total:
        parts.append(f"{stale_total} bảng kê đã tính chuyển 'Cần tính lại'")
    if locked_total:
        parts.append(f"{locked_total} bảng kê đã chốt gắn nhãn lệch quy ước (giữ như đã nộp)")
    if failed_total:
        parts.append(f"{failed_total} hồ sơ KHÔNG cập nhật được (đã đóng/lỗi) — kiểm tra lại")
    return " Đổi quy ước cột (9): " + "; ".join(parts) + "."
def declaration_type_exclusion_warning(client: dict, client_config: dict) -> str:
    excluded = _declaration_type_count_context(client, client_config)["bcct_excluded_type_rows"]
    if not excluded:
        return ""
    listed = "; ".join(f"{declaration_type}: {count} dòng" for declaration_type, count in excluded)
    return (
        f" Lưu ý: danh sách loại hình nhập đang LOẠI các loại hình có dữ liệu BCCT ({listed}) — "
        "các lô đó sẽ không được tính tồn CO (nguy cơ thiếu tồn giả)."
    )
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
@router.get("/clients-picker", response_class=HTMLResponse)
async def clients_picker(request: Request, current: str = ""):
    # Lazy-loaded fragment for the "Đổi công ty" modal switcher. NOT under
    # /clients/ on purpose: guard_response would read /clients/<x> as a single
    # client_id and 403 it against the user's visible set. This is a cross-client
    # resource; it is auth-guarded via the explicit /clients-picker entry in
    # co_auth.should_guard_path, and the handler filters to visible clients.
    clients = portfolio_service.clients()
    if co_auth.auth_required():
        clients = co_auth.filter_visible_clients(clients, co_auth.current_user(request))
    for client in clients:
        client["monogram"] = _client_monogram(client.get("name", ""))
    return templates.TemplateResponse(
        request=request,
        name="_picker_clients.html",
        context={"clients": clients, "current_client_id": current},
    )
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
    """Cheap per-case status for the dashboard. Shares `co_case_status_view`
    with the co-case list page so both surfaces agree on a case's status."""
    return co_case_status_view(case)


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
    flip_note = ""
    # Identity fields (legal_name / tax_code) are CO-side render metadata, not
    # source data — editable even when Data Hub source-mode is enabled. The
    # `co_stock_min_days_before_export` knob is also CO-side: it controls a
    # local CO eligibility predicate, not anything DH owns, so it persists to
    # the same local overlay without going through `require_local_source_writes`.
    # The TKN-PDF max-part size is also CO-side export behaviour (not DH source
    # data), so it persists to the client overlay alongside min-days and stays
    # editable even when Data Hub source-mode is on (which blocks the source
    # config save below).
    if (
        "legal_name" in form or "tax_code" in form
        or "co_stock_min_days_before_export" in form or "tkn_pdf_max_part_mb" in form
        or "bang_ke_column9_mode" in form or "bang_ke_unknown_origin_label" in form
    ):
        client = dict(client)
        if "legal_name" in form:
            client["legal_name"] = str(form.get("legal_name") or "").strip()
        if "tax_code" in form:
            client["tax_code"] = str(form.get("tax_code") or "").strip()
        if "bang_ke_column9_mode" in form or "bang_ke_unknown_origin_label" in form:
            # Bảng kê conventions are CO-side render metadata (like legal_name):
            # editable even when DH source-mode makes the source config read-only.
            # Editing them never rewrites persisted sheets — only re-Tính applies.
            overrides = dict(client.get("bang_ke_overrides") or {})
            previous_mode = bang_ke_settings(client)["column9_mode"]
            if "bang_ke_column9_mode" in form:
                overrides["column9_mode"] = normalize_column9_mode(form.get("bang_ke_column9_mode"))
            if "bang_ke_unknown_origin_label" in form:
                overrides["unknown_origin_label"] = str(form.get("bang_ke_unknown_origin_label") or "").strip()
            client["bang_ke_overrides"] = overrides
            if bang_ke_settings(client)["column9_mode"] != previous_mode:
                flip_note = _apply_client_column9_mode_flip(client)
        if "tkn_pdf_max_part_mb" in form:
            raw_mb = str(form.get("tkn_pdf_max_part_mb") or "").strip()
            exp = dict(client.get("export_overrides") or {})
            try:
                mb = float(raw_mb) if raw_mb else 2.0
                if mb <= 0:
                    mb = 2.0
            except ValueError:
                mb = 2.0
            exp["tkn_pdf_max_part_mb"] = int(mb) if float(mb).is_integer() else mb
            client["export_overrides"] = exp
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
        context=config_context(
            client_id,
            message="Đã lưu cấu hình công ty." + flip_note + declaration_type_exclusion_warning(client, config),
        ),
    )
@router.post("/clients/{client_id}/evaluate", response_class=HTMLResponse)
async def evaluate(request: Request, client_id: str):
    form = await large_request_form(request)
    case = update_products_from_form({key: str(value) for key, value in form.items()})
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
