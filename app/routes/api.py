"""Public read API for sister apps (BCQT, CO).

All routes under /v1/hub/. Bearer token auth.

Two-mode auth (per `api_auth_strict` setting):
- Default: try JWT verify against the SSO issuer (Sprint B3); fall
  back to permissive (any-non-empty) on JWT failure with a warning
  so legacy callers + tests keep working in dev.
- Strict (`api_auth_strict=true`): require valid JWT only. Set this
  for production.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import jwt as pyjwt
from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app import jwt_issuer, settings_store
from app.database import connect
from app.routes.clients import get_client, list_clients
from app.stores.bom import (
    get_version_with_rows,
    list_versions_for_product,
    list_products_with_bom,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/hub", tags=["api"])


def _strict_mode() -> bool:
    """Read api_auth_strict from app_settings. Default False (dev-friendly)."""
    return (settings_store.get("api_auth_strict") or "").lower() in {"1", "true", "yes"}


def _require_token(authorization: str | None) -> dict | None:
    """Verify bearer auth. Returns claims dict on JWT success, None on
    permissive fallback (legacy bearer-anything in dev). Raises 401 in
    strict mode or when no bearer at all.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bearer token required")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "empty bearer token")

    # Try JWT verify first.
    try:
        claims = jwt_issuer.verify_token(token)
        return claims
    except pyjwt.ExpiredSignatureError:
        # Always reject expired tokens regardless of strict mode.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "token expired",
        )
    except pyjwt.InvalidTokenError as e:
        if _strict_mode():
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}",
            )
        # Permissive: accept any non-empty bearer for dev / legacy callers.
        logger.warning("api: permissive accept of non-JWT bearer: %s", e)
        return None


def _serialize(v: Any):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: _serialize(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_serialize(x) for x in v]
    return v


def _json(payload: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=_serialize(payload), status_code=status_code)


@router.get("/dncxs")
async def api_list_dncxs(authorization: str | None = Header(None)):
    _require_token(authorization)
    return _json({"items": list_clients(), "total_estimate": None})


@router.get("/dncxs/{client_id}")
async def api_get_dncx(client_id: str, authorization: str | None = Header(None)):
    _require_token(authorization)
    dncx = get_client(client_id)
    if not dncx:
        raise HTTPException(404, "Client not found")
    return _json(dncx)


@router.get("/materials")
async def api_list_materials(
    client_id: str,
    category: str | None = None,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = 200,
    authorization: str | None = Header(None),
):
    _require_token(authorization)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    sql = """
        select client_id, customs_code, internal_code, name, category, category_override,
               status, unit, hs_code, updated_at
        from hub.materials where client_id = %s
    """
    params: list = [client_id]
    if category:
        sql += " and category = %s"
        params.append(category)
    if status:
        sql += " and status = %s"
        params.append(status)
    sql += " order by customs_code limit %s"
    params.append(min(max(limit, 1), 1000))
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            items = [dict(zip(cols, r)) for r in cur.fetchall()]
    return _json({"items": items, "total_estimate": len(items)})


@router.get("/materials/{customs_code}")
async def api_get_material(
    customs_code: str, client_id: str,
    authorization: str | None = Header(None),
):
    _require_token(authorization)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select client_id, customs_code, internal_code, name, category, category_override,
                       status, unit, hs_code, updated_at
                from hub.materials where client_id = %s and customs_code = %s
                """,
                (client_id, customs_code),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "material not found")
            cols = [d[0] for d in cur.description]
            return _json(dict(zip(cols, row)))


@router.get("/bcct")
async def api_list_bcct(
    client_id: str, year: int | None = None,
    direction: str | None = None,
    declaration_no: str | None = None,
    cursor: str | None = None, limit: int = 200,
    authorization: str | None = Header(None),
):
    _require_token(authorization)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    sql = """
        select client_id, year, transaction_key, line_no, declaration_no,
               declaration_type, direction, registration_date,
               customs_code, internal_code, goods_name, hs_code,
               quantity, unit, total_value, currency, origin,
               exporter_name, exporter_tax_code, consignee_name, incoterms,
               weight, weight_unit, package_count, package_unit,
               invoice_date, departure_date,
               destination_code, destination_name,
               transport_mode, exchange_rate,
               bom_version_id, indexed_at
        from hub.bcct_rows where client_id = %s
    """
    params: list = [client_id]
    if year:
        sql += " and year = %s"
        params.append(year)
    if direction:
        sql += " and direction = %s"
        params.append(direction)
    if declaration_no:
        sql += " and declaration_no = %s"
        params.append(declaration_no)
    sql += " order by registration_date desc nulls last, declaration_no, line_no limit %s"
    params.append(min(max(limit, 1), 1000))
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            items = [dict(zip(cols, r)) for r in cur.fetchall()]
    return _json({"items": items, "total_estimate": len(items)})


@router.get("/bcct/{transaction_key}")
async def api_get_bcct(
    transaction_key: str, client_id: str,
    authorization: str | None = Header(None),
):
    _require_token(authorization)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select client_id, year, transaction_key, line_no, declaration_no,
                       declaration_type, direction, registration_date,
                       customs_code, internal_code, goods_name, hs_code,
                       quantity, unit, total_value, currency, origin,
                       exporter_name, exporter_tax_code, consignee_name, incoterms,
                       weight, weight_unit, package_count, package_unit,
                       invoice_date, departure_date,
                       destination_code, destination_name,
                       transport_mode, exchange_rate,
                       bom_version_id, indexed_at, payload
                from hub.bcct_rows
                where client_id = %s and transaction_key = %s
                order by line_no
                """,
                (client_id, transaction_key),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    if not rows:
        raise HTTPException(404, "BCCT row not found")
    if len(rows) == 1:
        return _json(rows[0])
    return _json({"transaction_key": transaction_key, "lines": rows})


@router.get("/code-mappings")
async def api_list_code_mappings(
    client_id: str,
    authorization: str | None = Header(None),
):
    _require_token(authorization)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select client_id, internal_code, customs_code, category, notes
                from hub.code_mappings where client_id = %s
                order by internal_code, customs_code
                """,
                (client_id,),
            )
            cols = [d[0] for d in cur.description]
            items = [dict(zip(cols, r)) for r in cur.fetchall()]
    return _json({"items": items, "total_estimate": len(items)})


@router.get("/products/{product_code}/bom/latest")
async def api_bom_latest(
    product_code: str, client_id: str,
    authorization: str | None = Header(None),
):
    _require_token(authorization)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select version_id from hub.bom_versions
                where client_id=%s and product_code=%s and tombstoned_at is null
                  and intent in ('asserted_technical', 'staff_edit', 'derived')
                  and status = 'published'
                order by published_at desc nulls last, version_no desc limit 1
                """,
                (client_id, product_code),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "no latest version found")
    data = get_version_with_rows(row[0])
    return _json(data)


@router.get("/products/{product_code}/bom/versions")
async def api_bom_versions(
    product_code: str, client_id: str,
    actor: str | None = None, intent: str | None = None,
    authorization: str | None = Header(None),
):
    _require_token(authorization)
    versions = list_versions_for_product(client_id=client_id, product_code=product_code)
    if actor:
        versions = [v for v in versions if v["actor"] == actor]
    if intent:
        versions = [v for v in versions if v["intent"] == intent]
    return _json({"items": versions, "total_estimate": len(versions)})


@router.get("/products/{product_code}/bom")
async def api_bom_pinned(
    product_code: str, client_id: str, version_id: str | None = None,
    authorization: str | None = Header(None),
):
    _require_token(authorization)
    if version_id:
        data = get_version_with_rows(version_id)
        if not data or data["version"]["client_id"] != client_id \
                or data["version"]["product_code"] != product_code:
            raise HTTPException(404, "version not found")
        return _json(data)
    # No pin → equivalent to latest
    return await api_bom_latest(product_code, client_id, authorization)


@router.get("/products")
async def api_list_products(
    client_id: str,
    authorization: str | None = Header(None),
):
    _require_token(authorization)
    return _json({"items": list_products_with_bom(client_id), "total_estimate": None})


@router.get("/proposals/{proposal_id}")
async def api_get_proposal(
    proposal_id: str,
    authorization: str | None = Header(None),
):
    _require_token(authorization)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select proposal_id, client_id, product_code, actor, intent,
                       parent_version_id, context, status, decided_at, decided_by,
                       decision_reason, failed_conditions, materialized_version_id,
                       normalized_hash, created_at
                from hub.bom_change_requests where proposal_id = %s
                """,
                (proposal_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "proposal not found")
            cols = [d[0] for d in cur.description]
            return _json(dict(zip(cols, row)))


@router.get("/healthz")
async def api_healthz():
    return _json({"status": "ok"})
