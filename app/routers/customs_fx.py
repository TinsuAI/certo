from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.customs_fx_store import CUSTOMS_FX_CLIENT_ID, get_customs_fx_store, refresh_customs_exchange_rates
from app.table_view import build_table_view
from app.web.templating import templates


router = APIRouter()


CUSTOMS_FX_COLUMNS = [
    {"key": "currency_code", "label": "Nguyên tệ", "class": "mono"},
    {"key": "currency_name", "label": "Tên ngoại tệ"},
    {"key": "effective_date", "label": "Ngày hiệu lực", "class": "mono"},
    {"key": "rate_display", "label": "Tỷ giá", "class": "num", "sortable": False},
    {"key": "source_endpoint", "label": "Nguồn API", "class": "mono"},
    {"key": "fetched_at", "label": "Lần lấy", "class": "mono"},
]


def customs_exchange_rate_context(request: Request, **extra) -> dict:
    context = dict(extra)
    store = get_customs_fx_store()
    rows = store.rows(CUSTOMS_FX_CLIENT_ID)
    query = dict(request.query_params)
    if "sort" not in query:
        query["sort"] = "effective_date"
        query["dir"] = "desc"
    context["customs_fx_scope"] = CUSTOMS_FX_CLIENT_ID
    context["customs_fx_summary"] = store.summary(CUSTOMS_FX_CLIENT_ID)
    context["source_table"] = build_table_view(
        rows,
        columns=CUSTOMS_FX_COLUMNS,
        query=query,
        filters=[
            {"name": "currency", "field": "currency_code", "label": "Nguyên tệ"},
            {"name": "endpoint", "field": "source_endpoint", "label": "Nguồn API"},
        ],
        summary_fields=[
            {"field": "currency_code", "label": "Nguyên tệ"},
            {"field": "source_endpoint", "label": "Nguồn API"},
        ],
        default_sort="effective_date",
    )
    return context


@router.get("/customs-exchange-rates", response_class=HTMLResponse)
async def customs_exchange_rates(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="customs_exchange_rates.html",
        context=customs_exchange_rate_context(request),
    )


@router.post("/customs-exchange-rates/refresh", response_class=HTMLResponse)
async def refresh_customs_exchange_rates_route(request: Request):
    try:
        result = refresh_customs_exchange_rates(client_id=CUSTOMS_FX_CLIENT_ID)
    except Exception as exc:
        return templates.TemplateResponse(
            request=request,
            name="customs_exchange_rates.html",
            status_code=502,
            context=customs_exchange_rate_context(
                request,
                error=f"Không cập nhật được tỷ giá hải quan: {exc}",
            ),
        )
    return templates.TemplateResponse(
        request=request,
        name="customs_exchange_rates.html",
        context=customs_exchange_rate_context(
            request,
            customs_fx_result=result,
            message=(
                f"Đã cập nhật {result['fetched_row_count']} dòng tỷ giá hải quan; "
                f"đang lưu {result['saved_row_count']} dòng."
            ),
        ),
    )


@router.get("/clients/{client_id}/customs-exchange-rates")
async def client_customs_exchange_rates_redirect(client_id: str):
    return RedirectResponse("/customs-exchange-rates", status_code=303)
