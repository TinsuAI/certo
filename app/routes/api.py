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
import os
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import jwt as pyjwt
from psycopg import errors as psycopg_errors
from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from app import auth
from app import jwt_issuer, markets, settings_store
from app.database import connect
from app.routes.clients import get_client, list_clients
from app.stores import client_config as client_config_store
from app.stores.bom import (
    ProposalNotFound,
    ProposalNotPending,
    ResolverError,
    get_proposal,
    get_artifact_with_rows,
    list_artifacts_for_product,
    list_products_with_bom,
    resolve_bom_artifact,
    submit_proposal,
    validate_proposal_contract,
    withdraw_proposal,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/hub", tags=["api"])


def _strict_mode() -> bool:
    """Read api_auth_strict from app_settings. Default False (dev-friendly)."""
    return (settings_store.get("api_auth_strict") or "").lower() in {"1", "true", "yes"}


def _auth_disabled() -> bool:
    """Dev-only kill-switch: skip every bearer check on /v1/hub/* when
    `DATA_HUB_API_AUTH_DISABLED=1` is set. Suppressed automatically when
    `api_auth_strict=true` so prod can never accidentally turn it on.
    Loud warning is logged at startup (see app/main.py)."""
    if _strict_mode():
        return False
    return os.environ.get("DATA_HUB_API_AUTH_DISABLED", "") == "1"


def _require_token(authorization: str | None, *, scope: str = "hub:read") -> dict | None:
    """Verify bearer auth. Returns claims dict on JWT success, None on
    permissive fallback (legacy bearer-anything in dev). Raises 401 in
    strict mode or when no bearer at all.

    `scope`: required for service tokens (`typ=service`). Default
    'hub:read' covers all read endpoints. User tokens ignore the scope
    arg; their access is role-gated per `_require_can_view_client`.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        if _auth_disabled():
            return None
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bearer token required")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "empty bearer token")

    # Try JWT verify first.
    try:
        claims = jwt_issuer.verify_token(token)
    except pyjwt.ExpiredSignatureError:
        # Always reject expired tokens regardless of strict mode.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "token expired",
        )
    except jwt_issuer.ServiceTokenInvalid as e:
        # A revoked/deleted/malformed service token MUST NEVER fall back
        # to permissive mode — that would grant unauthenticated access on
        # a revoked token in dev. Always 401.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, f"invalid service token: {e}",
        )
    except pyjwt.InvalidTokenError as e:
        if _strict_mode():
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}",
            )
        # Permissive: accept any non-empty bearer for dev / legacy callers.
        logger.warning("api: permissive accept of non-JWT bearer: %s", e)
        return None
    _require_scope(claims, scope)
    return claims


def _require_jwt_claims(authorization: str | None, *, scope: str = "hub:read") -> dict | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        if _auth_disabled():
            return None
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bearer token required")
    token = authorization[7:].strip()
    if not token:
        if _auth_disabled():
            return None
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "empty bearer token")
    try:
        claims = jwt_issuer.verify_token(token)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired")
    except jwt_issuer.ServiceTokenInvalid as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid service token: {e}")
    except pyjwt.InvalidTokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}")
    _require_scope(claims, scope)
    return claims


def _is_service_claims(claims: dict | None) -> bool:
    return bool(claims) and claims.get("typ") == "service"


def _user_from_claims(claims: dict | None) -> auth.User | None:
    if not claims or _is_service_claims(claims):
        return None
    return auth.User(
        user_id=str(claims.get("sub", "")),
        email=str(claims.get("email", "")),
        display_name=str(claims.get("name", "")),
        role=str(claims.get("role", "")),
        status="active",
    )


def _visible_clients_from_claims(claims: dict | None) -> list[str] | None:
    if claims is None:
        return None
    if _is_service_claims(claims):
        # Service tokens with a client_ids whitelist see only those.
        # client_ids=null = all clients (no filtering).
        wl = claims.get("client_ids")
        return list(wl) if wl is not None else None
    return auth.visible_clients(_user_from_claims(claims))


def _require_scope(claims: dict | None, scope: str) -> None:
    """Service tokens must carry the named scope. User tokens are
    role-gated separately and don't go through this check."""
    if not _is_service_claims(claims):
        return
    granted = claims.get("scopes") or []
    # Defense in depth against a malformed token — `"x" in "csv,string"` is
    # True for substring matches, so refuse anything that isn't a list.
    if not isinstance(granted, list):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "service token scopes claim malformed",
        )
    if scope not in granted:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"service token missing required scope: {scope}",
        )


def _require_can_view_client(claims: dict | None, client_id: str) -> None:
    if claims is None:
        return
    if _is_service_claims(claims):
        wl = claims.get("client_ids")
        if wl is not None and client_id not in wl:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "client not in service-account whitelist",
            )
        return
    if not auth.can_view_client(_user_from_claims(claims), client_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")


def _require_can_edit_client(claims: dict | None, client_id: str) -> None:
    if claims is None:
        return
    if _is_service_claims(claims):
        wl = claims.get("client_ids")
        if wl is not None and client_id not in wl:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "client not in service-account whitelist",
            )
        return
    if not auth.can_edit_client(_user_from_claims(claims), client_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")


def _page_args(cursor: str | None, limit: int) -> tuple[int, int]:
    try:
        offset = int(cursor or 0)
    except ValueError as exc:
        raise HTTPException(400, "invalid cursor") from exc
    if offset < 0:
        raise HTTPException(400, "invalid cursor")
    return offset, min(max(limit, 1), 1000)


def _paged(items: list[dict], *, offset: int, limit: int) -> dict:
    has_next = len(items) > limit
    page = items[:limit]
    return {
        "items": page,
        "total_estimate": None,
        "next_cursor": str(offset + limit) if has_next else None,
    }


def _co_config(client: dict) -> dict:
    updated_at = client.get("updated_at") or client.get("created_at") or ""
    return {
        "schema_version": 1,
        "client_id": client["client_id"],
        "config_version": 1,
        "config_hash": f"data-hub:{client['client_id']}:{updated_at}",
        "source": "data-hub",
        "bcct": {
            "declaration_type_preset": "data_hub",
            "declaration_type_filter_status": "unconfigured",
            "eligible_import_declaration_types": [],
            "relevant_export_declaration_types": [],
        },
        "co_stock": {
            "lot_policy": "line_level",
        },
        "allocation_code": {
            "strategy": "same_as_customs_code",
            "description_regex": "",
            "fallback": "same_as_customs_code",
            "data_hub_code_resolution_mode": client.get("code_resolution_mode", ""),
        },
    }


def _module_summary(module: str, count: int) -> dict:
    return {
        "module": module,
        "published_row_count": count,
        "latest_version": {},
        "version_count": 0,
        "upload_count": 0,
        "correction_candidate_count": 0,
    }


def _invoice_tokens(value: str) -> set[str]:
    return {part for part in re.split(r"[^A-Za-z0-9]+", (value or "").upper()) if part}


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
    claims = _require_token(authorization)
    rows = list_clients()
    visible = _visible_clients_from_claims(claims)
    if visible is not None:
        allowed = set(visible)
        rows = [row for row in rows if (row.get("id") or row.get("client_id")) in allowed]
    return _json({"items": rows, "total_estimate": len(rows)})


@router.get("/dncxs/{client_id}")
async def api_get_dncx(client_id: str, authorization: str | None = Header(None)):
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    dncx = get_client(client_id)
    if not dncx:
        raise HTTPException(404, "Client not found")
    return _json(dncx)


@router.get("/dncxs/{client_id}/client-config")
async def api_client_config(client_id: str, authorization: str | None = Header(None)):
    """Consumer-agnostic master config for a DNCX.

    Replaces the deprecated `/co-config` endpoint. Owns only true master
    data: declaration-type registry + fiscal year start month. CO-runtime
    fields (lot_policy, allocation_code) live in CO; settlement column
    mappings live in BCQT.
    """
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    cfg_row = client_config_store.get_or_default(client_id)
    return _json(client_config_store.to_api_payload(cfg_row))


@router.get("/dncxs/{client_id}/co-config", deprecated=True)
async def api_co_config(client_id: str, authorization: str | None = Header(None)):
    """DEPRECATED 2026-05-02. Use /client-config + CO local config.

    Sunset: 2026-05-16 (deploy + 14 days). After that, this endpoint
    returns 410 Gone. Master fields (declaration types + fiscal year)
    are now sourced from hub.client_config; CO-runtime placeholders
    (co_stock.lot_policy, allocation_code.*) keep returning the legacy
    shape during the grace window so existing CO calls don't 500.
    """
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    cfg_row = client_config_store.get_or_default(client_id)
    payload = _co_config(client)
    payload["bcct"]["eligible_import_declaration_types"] = list(
        cfg_row.get("eligible_import_declaration_types") or []
    )
    payload["bcct"]["relevant_export_declaration_types"] = list(
        cfg_row.get("relevant_export_declaration_types") or []
    )
    if cfg_row.get("config_version", 0) > 0:
        payload["bcct"]["declaration_type_filter_status"] = "configured"
        payload["config_version"] = cfg_row["config_version"]
        payload["config_hash"] = cfg_row.get("config_hash", "")
    response = _json(payload)
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "Sat, 16 May 2026 00:00:00 GMT"
    response.headers["Link"] = (
        f'</v1/hub/dncxs/{client_id}/client-config>; rel="successor-version"'
    )
    return response


@router.get("/dncxs/{client_id}/source-summary")
async def api_source_summary(client_id: str, authorization: str | None = Header(None)):
    """Row-count summaries for Data Hub source records.

    `client_config` carries the new `/client-config` shape (master data
    only). CO-specific stock counters were removed 2026-05-02 — CO
    computes its own stock from raw filterable BCCT.
    """
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                  count(*) filter (where coalesce(category, '') <> 'tp') as n_materials,
                  count(*) filter (where category = 'tp') as n_products
                from hub.materials where client_id = %s
                """,
                (client_id,),
            )
            n_materials, n_products = cur.fetchone()
            cur.execute(
                """
                select
                  count(*) as n_bcct,
                  count(*) filter (where direction = 'export') as n_exports
                from hub.bcct_rows where client_id = %s
                """,
                (client_id,),
            )
            n_bcct, n_exports = cur.fetchone()
    cfg_row = client_config_store.get_or_default(client_id)
    return _json({
        "client_config": client_config_store.to_api_payload(cfg_row),
        "material_catalog": _module_summary("material_catalog", int(n_materials or 0)),
        "product_catalog": _module_summary("product_catalog", int(n_products or 0)),
        "bcct": {
            **_module_summary("bcct", int(n_bcct or 0)),
            "reviewed_row_count": int(n_bcct or 0),
            "export_row_count": int(n_exports or 0),
        },
    })


@router.get("/materials")
async def api_list_materials(
    client_id: str,
    category: str | None = None,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = 200,
    authorization: str | None = Header(None),
):
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    offset, safe_limit = _page_args(cursor, limit)
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
    sql += " order by customs_code limit %s offset %s"
    params.extend([safe_limit + 1, offset])
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            items = [dict(zip(cols, r)) for r in cur.fetchall()]
    return _json(_paged(items, offset=offset, limit=safe_limit))


@router.get("/materials/{customs_code}")
async def api_get_material(
    customs_code: str, client_id: str,
    authorization: str | None = Header(None),
):
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
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
    include_product_identity: bool = False,
    product_identity_candidate_limit: str | None = None,
    authorization: str | None = Header(None),
):
    """List BCCT rows with optional `product_identity` per CO API request
    2026-05-07. Default `include_product_identity=false` for broad list
    views (D7). Persisted column wins; lazy-fill at read for legacy rows."""
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    cand_limit = _validate_pid_candidate_limit(product_identity_candidate_limit)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    offset, safe_limit = _page_args(cursor, limit)
    sql = """
        select client_id, year, transaction_key, line_no, declaration_no,
               declaration_type, direction, registration_date,
               customs_code, internal_code, goods_name, hs_code,
               quantity, unit, total_value, currency, origin, invoice_ref,
               exporter_name, exporter_tax_code, consignee_name, incoterms,
               weight, weight_unit, package_count, package_unit,
               invoice_date, departure_date,
               destination_code, destination_name,
               transport_mode, exchange_rate,
               artifact_id, indexed_at, product_identity
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
    sql += " order by registration_date desc nulls last, declaration_no, line_no limit %s offset %s"
    params.extend([safe_limit + 1, offset])
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            items = [dict(zip(cols, r)) for r in cur.fetchall()]
    if include_product_identity:
        _attach_product_identity(
            items, client_id=client_id, candidate_limit=cand_limit,
        )
    else:
        for it in items:
            it.pop("product_identity", None)
    return _json(_paged(items, offset=offset, limit=safe_limit))


_DECLARATION_TYPE_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")

_PID_CANDIDATE_LIMIT_MAX = 20
_PID_CANDIDATE_LIMIT_DEFAULT = 5


def _validate_pid_candidate_limit(value: str | None) -> int:
    """Validate `product_identity_candidate_limit` per CO contract.

    Spec: default 5, max 20. Out-of-range or non-integer → 400.
    Param is `str | None` (not `int | None`) so non-integer input
    surfaces as 400 here instead of FastAPI's default 422."""
    if value is None or value == "":
        return _PID_CANDIDATE_LIMIT_DEFAULT
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise HTTPException(400, "invalid_product_identity_candidate_limit")
    if n < 1 or n > _PID_CANDIDATE_LIMIT_MAX:
        raise HTTPException(400, "invalid_product_identity_candidate_limit")
    return n


def _attach_product_identity(items: list[dict], *, client_id: str,
                              candidate_limit: int) -> None:
    """Attach `product_identity` to each item in-place.

    Rows where the column is already populated (DB NOT NULL) keep that
    value as-is (parser_version preserved per spec idempotency rule).
    Rows where the column is NULL get lazily resolved against the
    current resolver state. We do NOT write the lazy result back —
    backfill runs separately (D9).
    """
    if not items:
        return
    from app.resolvers.bcct_product_identity import (
        ResolverContext, resolve_product_identity,
    )
    needs_resolve = [it for it in items if it.get("product_identity") is None]
    if not needs_resolve:
        # Apply candidate_limit to pre-stored values too — we want the
        # response to honor the caller's limit even when row is from cache.
        for it in items:
            pid = it.get("product_identity")
            if pid and isinstance(pid.get("candidates"), list):
                pid["candidates"] = pid["candidates"][:candidate_limit]
        return
    with connect() as conn, conn.cursor() as cur:
        ctx = ResolverContext.from_db(
            client_id, cur, candidate_limit=candidate_limit,
        )
    for it in items:
        if it.get("product_identity") is None:
            it["product_identity"] = resolve_product_identity(it, ctx=ctx)
        elif isinstance(it["product_identity"].get("candidates"), list):
            it["product_identity"]["candidates"] = \
                it["product_identity"]["candidates"][:candidate_limit]


def _parse_declaration_types(value: str) -> set[str]:
    """Parse comma-separated declaration-type filter. Empty → no filter.
    Each token must be alphanumeric/underscore (max 16 chars) — anything
    else surfaces a 422 to the caller per the invoice-matches contract."""
    if not value:
        return set()
    tokens = {part.strip() for part in value.split(",") if part.strip()}
    for tok in tokens:
        if not _DECLARATION_TYPE_RE.match(tok):
            raise HTTPException(422, f"invalid_declaration_types: {tok!r}")
    return tokens


@router.get("/bcct/invoice-matches")
async def api_invoice_matches(
    client_id: str,
    invoice_no: str,
    declaration_types: str = "",
    limit: int = 100,
    cursor: str | None = None,
    include_market_hint: bool = True,
    include_product_identity: bool = True,
    product_identity_candidate_limit: str | None = None,
    authorization: str | None = Header(None),
):
    """Match BCCT export rows by invoice-token equivalence + return the
    fields CO needs for C/O case creation, including a `market_hint`
    derived from `unloading_location` (UN/LOCODE prefix → ISO country).

    Contract spec lives at
    `barry-CO-main/.ai/api-requests/2026-05-03-bcct-invoice-market-fields.md`
    (mirrored as `.ai/features/2026-05-03-bcct-invoice-market-fields/brief.md`
    in this repo)."""
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    if not invoice_no or not invoice_no.strip():
        raise HTTPException(400, "missing_invoice_no")
    if not get_client(client_id):
        raise HTTPException(404, "unknown_client")
    cand_limit = _validate_pid_candidate_limit(product_identity_candidate_limit)
    relevant_types = _parse_declaration_types(declaration_types)
    invoice_tokens = _invoice_tokens(invoice_no)
    if not invoice_tokens:
        return _json({"items": [], "next_cursor": None, "total_estimate": 0})

    offset, safe_limit = _page_args(cursor, limit)
    safe_limit = min(safe_limit, 500)  # contract: max 500

    sql = """
        select transaction_key, line_no, declaration_no, declaration_type,
               registration_date, customs_code, internal_code,
               goods_name, hs_code, quantity, unit, invoice_ref,
               invoice_date, departure_date, incoterms,
               consignee_name, exporter_name,
               destination_code, destination_name,
               product_identity,
               nullif(payload->>'Địa điểm dỡ hàng', '') as unloading_location
        from hub.bcct_rows
        where client_id = %s and direction = 'export' and coalesce(invoice_ref, '') <> ''
    """
    params: list = [client_id]
    if relevant_types:
        sql += " and declaration_type = any(%s)"
        params.append(list(relevant_types))
    for token in sorted(invoice_tokens):
        sql += " and upper(invoice_ref) like %s"
        params.append(f"%{token}%")
    sql += (
        " order by registration_date desc nulls last,"
        "          declaration_no asc nulls last,"
        "          nullif(line_no, '')::numeric asc nulls last,"
        "          transaction_key asc"
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    matches: list[dict] = []
    for row in rows:
        row_tokens = _invoice_tokens(row.get("invoice_ref") or "")
        if not invoice_tokens.issubset(row_tokens):
            continue
        item_code = row.get("internal_code") or row.get("customs_code") or ""
        # Existing fields keep None-on-NULL semantics so legacy consumers
        # see the same shape; new additive fields likewise pass None through.
        item: dict = {
            "declaration_no": row.get("declaration_no", ""),
            "line_no": row.get("line_no", ""),
            "declaration_type": row.get("declaration_type", ""),
            "item_code": item_code,
            "customs_code": row.get("customs_code", ""),
            "internal_code": row.get("internal_code", ""),
            "description": row.get("goods_name", ""),
            "goods_name": row.get("goods_name", ""),
            "hs_code": row.get("hs_code", ""),
            "quantity": row.get("quantity", ""),
            "unit": row.get("unit", ""),
            "invoice_ref": row.get("invoice_ref", ""),
            "transaction_key": row.get("transaction_key", ""),
            "invoice_date": row.get("invoice_date"),
            "departure_date": row.get("departure_date"),
            "incoterms": row.get("incoterms"),
            "consignee_name": row.get("consignee_name"),
            "exporter_name": row.get("exporter_name"),
            "unloading_location": row.get("unloading_location"),
            "destination_location_code": row.get("destination_code"),
            "destination_location_name": row.get("destination_name"),
            "product_identity": row.get("product_identity"),
        }
        if include_market_hint:
            hint = markets.unloading_location_to_market_hint(item["unloading_location"])
            item["market_hint"] = hint.to_dict() if hint else None
        matches.append(item)

    page = matches[offset : offset + safe_limit]
    if include_product_identity:
        _attach_product_identity(
            page, client_id=client_id, candidate_limit=cand_limit,
        )
    else:
        for it in page:
            it.pop("product_identity", None)
    next_cursor = (
        str(offset + safe_limit) if offset + safe_limit < len(matches) else None
    )
    return _json({
        "items": page,
        "next_cursor": next_cursor,
        "total_estimate": len(matches),
    })


@router.get("/bcct/{transaction_key}")
async def api_get_bcct(
    transaction_key: str, client_id: str,
    authorization: str | None = Header(None),
):
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select client_id, year, transaction_key, line_no, declaration_no,
                       declaration_type, direction, registration_date,
                       customs_code, internal_code, goods_name, hs_code,
                       quantity, unit, total_value, currency, origin, invoice_ref,
                       exporter_name, exporter_tax_code, consignee_name, incoterms,
                       weight, weight_unit, package_count, package_unit,
                       invoice_date, departure_date,
                       destination_code, destination_name,
                       transport_mode, exchange_rate,
                       artifact_id, indexed_at, payload
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
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
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
    """Latest published flattened (or manual_flat not_applicable) version
    for a product. Hardened post-2026-05-03 (BOM flattening shipped):

    - Excludes flatten_status='non_flattened' (consumers MUST NOT silently
      consume non-flattened BOMs as if they were calculation-ready).
    - When dual-source variants are published (purchased_btp_as_leaf AND
      self_produced_btp_exploded both live for the same product), responds
      409 with the variant list. Caller must re-call with explicit
      artifact_id via /v1/hub/products/{p}/bom?artifact_id=… .
    """
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    from app.stores.bom import latest_flattened_versions
    items = latest_flattened_versions(client_id=client_id, product_code=product_code)
    if not items:
        raise HTTPException(404, "no latest version found")
    if len(items) > 1:
        # Dual-source — caller must bind to a specific variant.
        return JSONResponse(
            {"error": "dual_source_variants",
             "message": "Multiple flattened variants exist for this product; "
                        "call /v1/hub/products/{product_code}/bom?artifact_id=… "
                        "to bind explicitly.",
             "variants": items},
            status_code=409,
        )
    data = get_artifact_with_rows(items[0]["artifact_id"])
    return _json(data)


@router.get("/products/{product_code}/bom/versions", include_in_schema=False)
async def _alias_api_bom_versions(product_code: str, request: Request):
    """Vocab rename alias (D9/D10, removable per BACKLOG)."""
    qs = request.url.query
    target = f"/v1/hub/products/{product_code}/bom/artifacts"
    if qs:
        target = f"{target}?{qs}"
    return RedirectResponse(url=target, status_code=308)


@router.get("/products/{product_code}/bom/artifacts")
async def api_bom_artifacts(
    product_code: str, client_id: str,
    actor: str | None = None, intent: str | None = None,
    authorization: str | None = Header(None),
):
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    versions = list_artifacts_for_product(client_id=client_id, product_code=product_code)
    if actor:
        versions = [v for v in versions if v["actor"] == actor]
    if intent:
        versions = [v for v in versions if v["intent"] == intent]
    return _json({"items": versions, "total_estimate": len(versions)})


@router.get("/products/{product_code}/bom")
async def api_bom_pinned(
    product_code: str, client_id: str,
    artifact_id: str | None = None,
    preset_id: str | None = None,
    case_id: str | None = None,
    shape: str | None = None,
    authorization: str | None = Header(None),
):
    """Single-artifact BOM read with Phase 3b resolver pinning.

    Precedence: artifact_id (raw pin, no resolution_trail) > preset_id
    > case_id > shape > default. The resolver maps shape errors to 4xx
    via _resolver_error_to_http().

    Response includes `resolution_trail` (list of strings) when any
    resolver hint was used; absent when artifact_id pin or pure
    `latest` fallthrough.
    """
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    if artifact_id:
        data = get_artifact_with_rows(artifact_id)
        if not data or data["artifact"]["client_id"] != client_id \
                or data["artifact"]["product_code"] != product_code:
            raise HTTPException(404, "artifact not found")
        return _json(data)
    if preset_id or case_id or shape:
        try:
            resolved = resolve_bom_artifact(
                client_id=client_id, product_code=product_code,
                preset_id=preset_id, case_id=case_id, shape=shape,
            )
        except ResolverError as exc:
            _raise_resolver_http(exc)
        data = get_artifact_with_rows(resolved["artifact_id"])
        if not data:
            raise HTTPException(500, "resolver picked a missing artifact")
        data["resolution_trail"] = resolved["resolution_trail"]
        data["shape"] = resolved["shape"]
        return _json(data)
    # No pin → equivalent to latest
    return await api_bom_latest(product_code, client_id, authorization)


def _raise_resolver_http(exc):
    """Map ResolverError.code → HTTP status."""
    code_to_status = {
        "preset_not_found": 404,
        "preset_scope_mismatch": 409,
        "case_not_found": 404,
        "no_artifact_for_shape": 404,
        "no_alive_artifacts": 404,
        "dual_source_variants": 409,
    }
    status_code = code_to_status.get(exc.code, 422)
    payload = {"error": exc.code, "message": exc.message, **(exc.extra or {})}
    raise HTTPException(status_code, payload)


@router.get("/products")
async def api_list_products(
    client_id: str,
    authorization: str | None = Header(None),
):
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    return _json({"items": list_products_with_bom(client_id), "total_estimate": None})


@router.post("/products/{product_code:path}/bom/proposals")
async def api_submit_bom_proposal(
    request: Request,
    product_code: str,
    authorization: str | None = Header(None),
):
    claims = _require_jwt_claims(authorization, scope="bom:propose")
    body = await request.json()
    client_id = body.get("client_id") or body.get("dncx_id")
    if not client_id or not get_client(client_id):
        raise HTTPException(404, "Client not found")
    _require_can_edit_client(claims, client_id)
    actor = body.get("actor", "co_system")
    intent = body.get("intent", "modified_for_case")
    rows = body.get("rows", [])
    if not isinstance(rows, list) or not rows:
        raise HTTPException(400, "rows required")
    try:
        validate_proposal_contract(
            actor=actor,
            intent=intent,
            parent_artifact_id=body.get("parent_artifact_id"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _json(submit_proposal(
        client_id=client_id,
        product_code=product_code,
        actor=actor,
        intent=intent,
        parent_artifact_id=body.get("parent_artifact_id"),
        context=body.get("context", {}),
        rows=rows,
    ))


@router.get("/proposals/{proposal_id}")
async def api_get_proposal(
    proposal_id: str,
    authorization: str | None = Header(None),
):
    claims = _require_token(authorization)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select proposal_id, client_id, product_code, actor, intent,
                       parent_artifact_id, context, status, decided_at, decided_by,
                       decision_reason, failed_conditions, materialized_artifact_id,
                       normalized_hash, created_at
                from hub.bom_change_requests where proposal_id = %s
                """,
                (proposal_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "proposal not found")
            cols = [d[0] for d in cur.description]
            proposal = dict(zip(cols, row))
    _require_can_view_client(claims, proposal["client_id"])
    return _json(proposal)


@router.post("/proposals/{proposal_id}/withdraw")
async def api_withdraw_proposal(
    proposal_id: str,
    authorization: str | None = Header(None),
):
    """Rescind a still-pending proposal. Allowed for any caller with the
    `bom:propose` scope (service tokens) or edit access on the client
    (human reviewers). Returns 409 if the proposal already decided."""
    claims = _require_jwt_claims(authorization, scope="bom:propose")
    proposal = get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(404, "proposal not found")
    _require_can_edit_client(claims, proposal["client_id"])
    try:
        result = withdraw_proposal(
            proposal_id=proposal_id,
            by=str(claims.get("sub", "")) if claims else "unknown",
        )
    except ProposalNotFound:
        raise HTTPException(404, "proposal not found")
    except ProposalNotPending as exc:
        raise HTTPException(
            409, f"Proposal not pending (current status: {exc})",
        )
    return _json(result)


# ─────────────────────────────────────────────────────────────────────
# Phase 3b — Preset CRUD
# ─────────────────────────────────────────────────────────────────────


def _new_preset_id() -> str:
    import secrets
    return "bp_" + secrets.token_urlsafe(12)


@router.post("/presets", status_code=201)
async def api_create_preset(
    request: Request, authorization: str | None = Header(None),
):
    """Create a BOM preset binding (client, product, artifact, name).

    Body JSON: {client_id, product_code, artifact_id, name,
                sourcing_choices?, notes?}
    """
    claims = _require_token(authorization)
    body = await request.json()
    for k in ("client_id", "product_code", "artifact_id", "name"):
        if not body.get(k):
            raise HTTPException(422, f"missing required field: {k}")
    _require_can_edit_client(claims, body["client_id"])
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select client_id, product_code from hub.bom_artifacts "
            "where artifact_id = %s",
            (body["artifact_id"],),
        )
        art = cur.fetchone()
        if not art:
            raise HTTPException(404, f"artifact_id={body['artifact_id']!r} not found")
        if art[0] != body["client_id"] or art[1] != body["product_code"]:
            raise HTTPException(
                409,
                f"artifact_id belongs to ({art[0]!r}, {art[1]!r}), not "
                f"({body['client_id']!r}, {body['product_code']!r})",
            )
        # Name uniqueness is enforced by partial unique index
        # uq_bom_presets_name (client, product, name) where tombstoned_at
        # is null. Pre-check race-prone; rely on DB + translate violation
        # to 409.
        preset_id = _new_preset_id()
        sourcing = json.dumps(body.get("sourcing_choices") or {})
        try:
            cur.execute(
                "insert into hub.bom_presets (preset_id, client_id, product_code, "
                "artifact_id, name, sourcing_choices, notes, created_by) "
                "values (%s, %s, %s, %s, %s, %s::jsonb, %s, %s) returning created_at",
                (preset_id, body["client_id"], body["product_code"],
                 body["artifact_id"], body["name"], sourcing,
                 body.get("notes"),
                 (claims or {}).get("sub")),
            )
        except psycopg_errors.UniqueViolation:
            raise HTTPException(409, f"preset name {body['name']!r} already exists")
        (created_at,) = cur.fetchone()
    return _json({
        "preset_id": preset_id,
        "client_id": body["client_id"],
        "product_code": body["product_code"],
        "artifact_id": body["artifact_id"],
        "name": body["name"],
        "sourcing_choices": body.get("sourcing_choices") or {},
        "notes": body.get("notes"),
        "created_at": created_at.isoformat() if created_at else None,
    }, status_code=201)


@router.get("/clients/{client_id}/products/{product_code:path}/presets")
async def api_list_presets(
    client_id: str, product_code: str,
    authorization: str | None = Header(None),
):
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select preset_id, name, artifact_id, sourcing_choices, notes, "
            "created_at, tombstoned_at "
            "from hub.bom_presets "
            "where client_id=%s and product_code=%s "
            "and tombstoned_at is null "
            "order by created_at desc",
            (client_id, product_code),
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
        r.pop("tombstoned_at", None)
    return _json({"items": rows})


@router.patch("/presets/{preset_id}")
async def api_patch_preset(
    preset_id: str, request: Request,
    authorization: str | None = Header(None),
):
    claims = _require_token(authorization)
    body = await request.json()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select client_id, product_code from hub.bom_presets "
            "where preset_id=%s",
            (preset_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, f"preset_id={preset_id!r} not found")
        _require_can_edit_client(claims, row[0])

        sets, params = [], []
        if "name" in body:
            sets.append("name=%s")
            params.append(body["name"])
        if "sourcing_choices" in body:
            sets.append("sourcing_choices=%s::jsonb")
            params.append(json.dumps(body["sourcing_choices"] or {}))
        if "notes" in body:
            sets.append("notes=%s")
            params.append(body["notes"])
        if not sets:
            raise HTTPException(422, "no editable fields provided")
        params.append(preset_id)
        try:
            cur.execute(
                f"update hub.bom_presets set {', '.join(sets)} where preset_id=%s "
                "returning preset_id, client_id, product_code, artifact_id, name, "
                "sourcing_choices, notes, created_at",
                params,
            )
        except psycopg_errors.UniqueViolation:
            raise HTTPException(409, "preset name conflicts with an existing alive preset")
        cols = [d[0] for d in cur.description]
        out = dict(zip(cols, cur.fetchone()))
    if out.get("created_at"):
        out["created_at"] = out["created_at"].isoformat()
    return _json(out)


@router.post("/presets/{preset_id}/tombstone")
async def api_tombstone_preset(
    preset_id: str, request: Request,
    authorization: str | None = Header(None),
):
    claims = _require_token(authorization)
    try:
        body = await request.json()
    except Exception:
        body = {}
    reason = (body or {}).get("reason")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select client_id from hub.bom_presets where preset_id=%s",
            (preset_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, f"preset_id={preset_id!r} not found")
        _require_can_edit_client(claims, row[0])
        cur.execute(
            "update hub.bom_presets set tombstoned_at=now(), tombstone_reason=%s "
            "where preset_id=%s",
            (reason, preset_id),
        )
    return _json({"preset_id": preset_id, "tombstoned": True, "reason": reason})


@router.get("/healthz")
async def api_healthz():
    return _json({"status": "ok"})
