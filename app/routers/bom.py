from __future__ import annotations


from fastapi import APIRouter
from app.bom_service import bom_service
from app.table_view import build_table_view
from app.web.client_context import _data_hub_overview_context, client_context, resolve_client, source_stats
from app.web.templating import templates
from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from urllib.parse import quote


router = APIRouter()

BOM_PRODUCT_COLUMNS = [
    {"key": "product_code", "label": "Mã TP", "class": "mono", "link_key": "view_href"},
    {"key": "product_artifact_no", "label": "TP artifact", "class": "mono"},
    {"key": "row_count", "label": "Dòng BOM", "class": "num"},
    {"key": "status", "label": "Trạng thái"},
    {"key": "version_hash_short", "label": "Hash", "class": "mono"},
]
BOM_LINE_COLUMNS = [
    {"key": "material_code", "label": "Mã NVL", "class": "mono"},
    {"key": "material_name", "label": "Tên NVL"},
    {"key": "qty_per", "label": "Định mức", "class": "num"},
    {"key": "uom", "label": "ĐVT", "class": "mono"},
    {"key": "scrap_rate", "label": "Hao hụt", "class": "num"},
    {"key": "source", "label": "Nguồn"},
    {"key": "row_class", "label": "Trạng thái"},
]
def bom_context(request: Request, client_id: str, **extra) -> dict:
    lean = _data_hub_overview_context(client_id, "bom", dh_path="bom")
    if lean is not None and not extra.get("message") and not extra.get("error"):
        # DH mode: BOM is read-only and per-finished-product. The real BOM
        # metric comes from the Data Hub `bom` block on source-summary (shipped
        # 2026-06-07) — source_stats reads summary["bom"] and renders the export
        # trio. When that block is absent (older Data Hub) it falls back to a
        # qualitative card; CO never fabricates a count from the page-capped
        # products endpoint. See .ai/api-requests/2026-06-07-products-total-count.md.
        return lean
    context = client_context(client_id, "bom", **extra)
    workspace = context["bom_workspace"]
    context["source_stats"] = source_stats(
        "bom",
        counts=context["client"].get("counts", {}),
        bom_products=len({str(r.get("product_code", "")) for r in workspace.get("product_composition", []) if r.get("product_code")}),
        bom_lines=len(workspace.get("latest_rows", [])),
    )
    selected_product = selected_bom_product(workspace, request.query_params.get("product", ""))
    product_rows = bom_product_table_rows(workspace, client_id, selected_product)
    line_rows = [
        bom_line_table_row(row)
        for row in workspace.get("latest_rows", [])
        if not selected_product or row.get("product_code") == selected_product
    ]
    product_table = build_table_view(
        product_rows,
        columns=BOM_PRODUCT_COLUMNS,
        query=request.query_params,
        filters=[{"name": "status", "field": "status", "label": "Trạng thái"}],
        summary_fields=[{"field": "status", "label": "Trạng thái"}],
        default_sort="product_code",
        default_per_page=25,
        param_prefix="tp_",
    )
    product_table["search_placeholder"] = "Mã thành phẩm, version, hash..."
    line_table = build_table_view(
        line_rows,
        columns=BOM_LINE_COLUMNS,
        query=request.query_params,
        filters=[
            {"name": "uom", "field": "uom", "label": "ĐVT"},
            {"name": "source", "field": "source", "label": "Nguồn"},
            {"name": "status", "field": "row_class", "label": "Trạng thái"},
        ],
        summary_fields=[
            {"field": "row_class", "label": "Trạng thái"},
            {"field": "uom", "label": "ĐVT"},
        ],
        default_sort="material_code",
        default_per_page=50,
        param_prefix="line_",
    )
    line_table["search_placeholder"] = "Mã NVL, tên NVL, trạng thái..."
    context["selected_bom_product"] = selected_product
    context["selected_bom_product_summary"] = next(
        (row for row in product_rows if row["product_code"] == selected_product),
        {},
    )
    context["bom_product_table"] = product_table
    context["bom_line_table"] = line_table
    return context
def selected_bom_product(workspace: dict, requested_product: str = "") -> str:
    codes = sorted({str(row.get("product_code", "")) for row in workspace.get("product_composition", []) if row.get("product_code")})
    if not codes:
        codes = sorted({str(row.get("product_code", "")) for row in workspace.get("latest_rows", []) if row.get("product_code")})
    requested = str(requested_product or "").strip()
    if requested in codes:
        return requested
    return codes[0] if codes else ""
def bom_product_table_rows(workspace: dict, client_id: str, selected_product: str) -> list[dict]:
    version_index = {
        version.get("product_version_id"): version
        for version in workspace.get("product_versions", [])
        if version.get("product_version_id")
    }
    rows = []
    composition = workspace.get("product_composition", [])
    if not composition:
        composition = [
            {
                "product_code": version.get("product_code", ""),
                "product_version_id": version.get("product_version_id", ""),
                "product_version_no": version.get("product_version_no", ""),
                "row_count": version.get("row_count", 0),
                "status": version.get("status", ""),
                "version_hash": version.get("version_hash", ""),
            }
            for version in workspace.get("product_versions", [])
        ]
    for row in composition:
        version = version_index.get(row.get("product_version_id"), {})
        product_code = str(row.get("product_code", ""))
        version_hash = str(row.get("version_hash") or version.get("version_hash") or "")
        rows.append({
            "product_code": product_code,
            "product_version_no": row.get("product_version_no", version.get("product_version_no", "")),
            "row_count": row.get("row_count", version.get("row_count", 0)),
            "status": row.get("status", version.get("status", "")),
            "version_hash": version_hash,
            "version_hash_short": version_hash[:10],
            "selected": "Đang xem" if product_code == selected_product else "",
            "view_href": f"/clients/{client_id}/bom?product={quote(product_code, safe='')}#bom-lines",
        })
    return rows
def bom_line_table_row(row: dict) -> dict:
    return {
        **row,
        "material_name": row.get("material_name", ""),
        "scrap_rate": row.get("scrap_rate", ""),
        "source": row.get("source", ""),
        "row_class": row.get("row_class", ""),
    }
@router.get("/clients/{client_id}/bom", response_class=HTMLResponse)
async def bom(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="bom.html",
        context=bom_context(request, client_id),
    )

# Source-data writes belong to Data Hub.
#
# Uploading catalog / BOM / BCCT through CO was the local file-store backend,
# which production has not used for a long time and which the suite has now
# stopped using too. These routes answered 409 in Data Hub mode — the only mode
# there is — so they were unreachable code guarding a mode that no longer
# exists. The read views above stay: they render whatever the source of truth
# holds.
