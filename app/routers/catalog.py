from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse

from app.portfolio import portfolio_service
from app.table_view import build_table_view
from app.web.client_context import _data_hub_overview_context, client_context, resolve_client
from app.web.templating import templates


router = APIRouter()


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


def catalog_table_context(request: Request, client_id: str, view_name: str, **extra) -> dict:
    view = CATALOG_VIEWS[view_name]
    lean = _data_hub_overview_context(client_id, "catalog", dh_path="catalog")
    if lean is not None and not extra.get("catalog_result"):
        # DH mode and no upload result to surface → skip the table build entirely.
        lean["catalog_view"] = {**view, "name": view_name}
        return lean
    context = client_context(client_id, "catalog", **extra)
    rows = context["source_workspace"][view["module"]]["published_rows"]
    if context["source_backend"] == "data-hub":
        view = {
            **view,
            "columns": [
                {**column, "key": "uom"} if column.get("key") == "unit" else column
                for column in view["columns"]
            ],
            "filters": [
                {**filter_row, "field": "uom"} if filter_row.get("field") == "unit" else filter_row
                for filter_row in view["filters"]
            ],
            "summary_fields": [
                {**summary_row, "field": "uom"} if summary_row.get("field") == "unit" else summary_row
                for summary_row in view["summary_fields"]
            ],
        }
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


@router.get("/clients/{client_id}/catalog", response_class=HTMLResponse)
async def catalog(request: Request, client_id: str):
    context = _data_hub_overview_context(client_id, "catalog", dh_path="catalog") \
        or client_context(client_id, "catalog")
    return templates.TemplateResponse(
        request=request,
        name="catalog.html",
        context=context,
    )


@router.get("/clients/{client_id}/catalog/materials", response_class=HTMLResponse)
async def material_catalog(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="catalog_table.html",
        context=catalog_table_context(request, client_id, "materials"),
    )


@router.get("/clients/{client_id}/catalog/products", response_class=HTMLResponse)
async def product_catalog(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="catalog_table.html",
        context=catalog_table_context(request, client_id, "products"),
    )

# Source-data writes belong to Data Hub.
#
# Uploading catalog / BOM / BCCT through CO was the local file-store backend,
# which production has not used for a long time and which the suite has now
# stopped using too. These routes answered 409 in Data Hub mode — the only mode
# there is — so they were unreachable code guarding a mode that no longer
# exists. The read views above stay: they render whatever the source of truth
# holds.
