from __future__ import annotations

from pathlib import Path

from fastapi import File, Form, Request, UploadFile
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
    process_bcct_upload,
    process_catalog_upload,
)
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
        "source_notes": SOURCE_NOTES,
        **extra,
    }


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
    return templates.TemplateResponse(
        request=request,
        name="catalog.html",
        status_code=status_code,
        context=client_context(
            client_id,
            "catalog",
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
        context=client_context(client_id, "co-stock"),
    )


@app.get("/clients/{client_id}/bcct", response_class=HTMLResponse)
async def bcct(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="bcct.html",
        context=client_context(client_id, "bcct"),
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
        context=client_context(
            client_id,
            "bcct",
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
        context=client_context(client_id, "co-case"),
    )


@app.post("/clients/{client_id}/evaluate", response_class=HTMLResponse)
async def evaluate(request: Request, client_id: str):
    form = await request.form()
    case = update_products_from_form({key: str(value) for key, value in form.items()})
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=client_context(client_id, "co-case", case=case, message="Đã tính lại theo dữ liệu đang sửa."),
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
            context=client_context(client_id, "co-case", error=str(exc)),
        )
    case["customer"] = client["name"]
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=client_context(client_id, "co-case", case=case, message=f"Đã parse {file.filename}."),
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
