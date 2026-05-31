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
from fastapi.responses import JSONResponse

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


_MATERIALS_SELECT_WITH_ROLES = """
    select m.client_id, m.material_code, m.name,
           m.category,
           m.status,
           -- Post-mig-063: `materials.unit` was consolidated into `uom`.
           -- Emit BOTH keys in JSON for the sister-app grace window: `uom`
           -- is the new canonical, `unit` is the deprecated alias kept so
           -- existing CO consumers (data_hub_client.normalize_material_row
           -- / normalize_product_row) keep working. Sunset date for the
           -- `unit` alias: see docs/API_CONTRACT.md.
           m.uom, m.uom as unit,
           m.hs_code, m.updated_at,
           m.btp_sourcing,
           coalesce(vmr.has_imports, false) as has_imports,
           coalesce(vmr.has_exports, false) as has_exports,
           coalesce(vmr.is_consumed_in_bom, false) as is_consumed_in_bom,
           coalesce(vmr.has_own_bom, false) as has_own_bom,
           coalesce(vmr.observed_roles, '{}'::text[]) as observed_roles,
           coalesce(vmr.is_multi_role, false) as is_multi_role,
           coalesce(vmr.declared_observed_conflict, false) as declared_observed_conflict
    from hub.materials m
    left join hub.v_material_roles vmr
           on vmr.client_id = m.client_id
          and vmr.material_code = m.material_code
"""


@router.get("/materials")
async def api_list_materials(
    client_id: str,
    category: str | None = None,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = 200,
    authorization: str | None = Header(None),
):
    """List materials with observed-role signals joined from v_material_roles.

    Brief: .ai/features/2026-05-07-catalog-roles-refactor/brief.md (rev 5).
    """
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    offset, safe_limit = _page_args(cursor, limit)
    sql = _MATERIALS_SELECT_WITH_ROLES + " where m.client_id = %s"
    params: list = [client_id]
    if category:
        sql += " and m.category = %s"
        params.append(category)
    if status:
        sql += " and m.status = %s"
        params.append(status)
    sql += " order by m.material_code limit %s offset %s"
    params.extend([safe_limit + 1, offset])
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            items = [dict(zip(cols, r)) for r in cur.fetchall()]
    for it in items:
        # Postgres text[] arrays come back as Python lists already, but
        # normalize empty arrays to [] (psycopg may return None).
        if it.get("observed_roles") is None:
            it["observed_roles"] = []
    return _json(_paged(items, offset=offset, limit=safe_limit))


@router.get("/materials/{material_code}")
async def api_get_material(
    material_code: str, client_id: str,
    authorization: str | None = Header(None),
):
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                _MATERIALS_SELECT_WITH_ROLES + " where m.client_id = %s and m.material_code = %s",
                (client_id, material_code),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "material not found")
            cols = [d[0] for d in cur.description]
            item = dict(zip(cols, row))
            if item.get("observed_roles") is None:
                item["observed_roles"] = []
            return _json(item)


def _parse_since(value: str | None) -> "datetime | None":
    """Parse `since` query param per CO incremental-pull contract
    (`barry-CO-main/.ai/api-requests/2026-05-28-bcct-incremental-since-filter.md`).
    Required to be ISO-8601 with explicit timezone (UTC).
    Returns None when caller omitted the param; raises 400 otherwise.
    """
    from datetime import datetime
    if value is None or value == "":
        return None
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, "invalid_since")
    if ts.tzinfo is None:
        # Spec requires explicit UTC; reject timezone-naive strings so
        # callers can't accidentally drift across server local time zones.
        raise HTTPException(400, "invalid_since")
    return ts


def _parse_include_tombstones(value: str | None) -> bool:
    if value is None or value == "":
        return False
    if value == "true":
        return True
    if value == "false":
        return False
    raise HTTPException(400, "invalid_include_tombstones")


@router.get("/bcct")
async def api_list_bcct(
    client_id: str, year: int | None = None,
    direction: str | None = None,
    declaration_no: str | None = None,
    cursor: str | None = None, limit: int = 200,
    include_material_identity: bool = False,
    material_identity_candidate_limit: str | None = None,
    since: str | None = None,
    include_tombstones: str | None = None,
    authorization: str | None = Header(None),
):
    """List BCCT rows with optional `material_identity` per CO API request
    2026-05-07. Default `include_material_identity=false` for broad list
    views (D7). Persisted column wins; lazy-fill at read for legacy rows.

    Incremental pull (CO API request 2026-05-28):
    - `since` (ISO-8601 UTC): filter to rows whose `indexed_at > since`.
    - `include_tombstones=true` (requires `since`): include a
      `tombstones[]` array of transaction_keys deleted since that
      timestamp, sourced from `hub.bcct_row_history`.
    - `server_time` is always present in the response so callers can
      use it as the high-water mark for their next call.
    """
    from datetime import datetime, timezone
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    cand_limit = _validate_pid_candidate_limit(material_identity_candidate_limit)
    since_ts = _parse_since(since)
    want_tombstones = _parse_include_tombstones(include_tombstones)
    if want_tombstones and since_ts is None:
        # Tombstones need a time window — without `since`, "deleted when?"
        # has no answer and the response would be unbounded.
        raise HTTPException(400, "include_tombstones_requires_since")
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    offset, safe_limit = _page_args(cursor, limit)
    sql = """
        select client_id, year, transaction_key, line_no, declaration_no,
               declaration_type, direction, registration_date,
               customs_code, goods_name, hs_code,
               quantity, unit,
               unit_price, unit_price_nt,
               total_value, total_value_nt,
               currency_nt, total_tax, unloading_location,
               origin, invoice_ref,
               exporter_name, exporter_tax_code, consignee_name, incoterms,
               weight, weight_unit, package_count, package_unit,
               invoice_date, departure_date,
               destination_code, destination_name,
               transport_mode, exchange_rate,
               artifact_id, indexed_at
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
    if since_ts is not None:
        sql += " and indexed_at > %s"
        params.append(since_ts)
    sql += " order by registration_date desc nulls last, declaration_no, line_no limit %s offset %s"
    params.extend([safe_limit + 1, offset])
    server_time = datetime.now(timezone.utc)
    tombstones: list[dict] = []
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            items = [dict(zip(cols, r)) for r in cur.fetchall()]
            if want_tombstones and offset == 0:
                # Spec: tombstones are returned in full on the first page.
                # Subsequent pages have tombstones=[] (kept as empty array
                # only when include_tombstones=true was requested).
                cur.execute(
                    """
                    select transaction_key, changed_at, changed_by
                      from hub.bcct_row_history
                     where client_id = %s
                       and action = 'delete'
                       and changed_at > %s
                     order by changed_at desc
                    """,
                    (client_id, since_ts),
                )
                tombstones = [
                    {
                        "transaction_key": tk,
                        "removed_at": removed_at,
                        "reason": changed_by or "system",
                    }
                    for tk, removed_at, changed_by in cur.fetchall()
                ]
    if include_material_identity:
        _attach_material_identity(
            items, client_id=client_id, candidate_limit=cand_limit,
        )
    else:
        for it in items:
            it.pop("material_identity", None)
    payload = _paged(items, offset=offset, limit=safe_limit)
    payload["server_time"] = server_time
    if want_tombstones:
        payload["tombstones"] = tombstones
    return _json(payload)


_DECLARATION_TYPE_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")

_PID_CANDIDATE_LIMIT_MAX = 20
_PID_CANDIDATE_LIMIT_DEFAULT = 5


def _validate_pid_candidate_limit(value: str | None) -> int:
    """Validate `material_identity_candidate_limit` per CO contract.

    Spec: default 5, max 20. Out-of-range or non-integer → 400.
    Param is `str | None` (not `int | None`) so non-integer input
    surfaces as 400 here instead of FastAPI's default 422."""
    if value is None or value == "":
        return _PID_CANDIDATE_LIMIT_DEFAULT
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise HTTPException(400, "invalid_material_identity_candidate_limit")
    if n < 1 or n > _PID_CANDIDATE_LIMIT_MAX:
        raise HTTPException(400, "invalid_material_identity_candidate_limit")
    return n


def _attach_material_identity(items: list[dict], *, client_id: str,
                              candidate_limit: int) -> None:
    """Attach `material_identity` to each item in-place.

    mig 038: column dropped — every row resolves at read time against
    current materials catalog + parser rules. Single ResolverContext +
    client lookup per request, reused across rows.
    """
    if not items:
        return
    from app.parsers.derivations import compute_internal_code
    from app.resolvers.bcct_material_identity import (
        ResolverContext, resolve_material_identity,
    )
    with connect() as conn, conn.cursor() as cur:
        ctx = ResolverContext.from_db(
            client_id, cur, candidate_limit=candidate_limit,
        )
        cur.execute(
            "select code_resolution_mode from hub.clients where client_id=%s",
            (client_id,),
        )
        row = cur.fetchone()
        client = {
            "client_id": client_id,
            "code_resolution_mode": row[0] if row else "simple_mapping",
        }
    for it in items:
        it["internal_code"] = compute_internal_code(it, client=client)
        it["material_identity"] = resolve_material_identity(it, ctx=ctx)


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
    include_material_identity: bool = True,
    material_identity_candidate_limit: str | None = None,
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
    cand_limit = _validate_pid_candidate_limit(material_identity_candidate_limit)
    relevant_types = _parse_declaration_types(declaration_types)
    invoice_tokens = _invoice_tokens(invoice_no)
    if not invoice_tokens:
        return _json({"items": [], "next_cursor": None, "total_estimate": 0})

    offset, safe_limit = _page_args(cursor, limit)
    safe_limit = min(safe_limit, 500)  # contract: max 500

    sql = """
        select transaction_key, line_no, declaration_no, declaration_type,
               registration_date, customs_code,
               goods_name, hs_code, quantity, unit, invoice_ref,
               invoice_date, departure_date, incoterms,
               consignee_name, exporter_name,
               destination_code, destination_name,
               unloading_location,
               unit_price, unit_price_nt,
               total_value, total_value_nt,
               currency_nt
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
        # item_code starts as customs_code; re-set to material_identity
        # display_code post-lazy-fill below.
        item: dict = {
            "declaration_no": row.get("declaration_no", ""),
            "line_no": row.get("line_no", ""),
            "declaration_type": row.get("declaration_type", ""),
            "item_code": row.get("customs_code", ""),
            "customs_code": row.get("customs_code", ""),
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
        }
        if include_market_hint:
            hint = markets.unloading_location_to_market_hint(item["unloading_location"])
            item["market_hint"] = hint.to_dict() if hint else None
        matches.append(item)

    page = matches[offset : offset + safe_limit]
    if include_material_identity:
        _attach_material_identity(
            page, client_id=client_id, candidate_limit=cand_limit,
        )
        # item_code now reads from the just-resolved material_identity.
        for it in page:
            mid = it.get("material_identity") or {}
            it["item_code"] = (
                mid.get("display_code") or it.get("customs_code") or ""
            )
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
                       customs_code, goods_name, hs_code,
                       quantity, unit,
                       unit_price, unit_price_nt,
                       total_value, total_value_nt,
                       currency_nt, total_tax, unloading_location,
                       origin, invoice_ref,
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


_BY_CODES_MAX = 100


def _parse_codes_param(value: str) -> list[str]:
    """Split + dedupe + uppercase the comma-separated `codes` param.

    Order preserved (callers paginate per-request and have no contract
    on ordering, but stable order helps logs). Empty → 400; >100 → 400.
    """
    if value is None:
        raise HTTPException(400, "missing codes")
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in value.split(","):
        token = raw.strip().upper()
        if not token:
            continue
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    if not tokens:
        raise HTTPException(400, "missing codes")
    if len(tokens) > _BY_CODES_MAX:
        raise HTTPException(400, "too many codes")
    return tokens


@router.get("/clients/{client_id}/bcct/by-codes")
async def api_list_bcct_by_codes(
    client_id: str,
    codes: str = "",
    direction: str | None = None,
    include_material_identity: bool = False,
    material_identity_candidate_limit: str | None = None,
    cursor: str | None = None,
    limit: int = 200,
    authorization: str | None = Header(None),
):
    """BCCT slice filtered by customs_code IN (codes). Sister-app entry
    for CO's substitute-stock derivation which only needs ~20 candidate
    codes' worth of rows, not the full 65k Johnson catalog.

    Contract spec:
    `barry-CO-main/.ai/api-requests/2026-05-13-bcct-by-codes-lookup.md`.
    Row shape mirrors `/v1/hub/bcct`. `codes` is case-insensitive exact
    match against `customs_code`; max 100 per request. Unknown codes →
    200 with empty items (not 404)."""
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    cand_limit = _validate_pid_candidate_limit(material_identity_candidate_limit)
    code_list = _parse_codes_param(codes)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    offset, safe_limit = _page_args(cursor, limit)
    sql = """
        select client_id, year, transaction_key, line_no, declaration_no,
               declaration_type, direction, registration_date,
               customs_code, goods_name, hs_code,
               quantity, unit,
               unit_price, unit_price_nt,
               total_value, total_value_nt,
               currency_nt, total_tax, unloading_location,
               origin, invoice_ref,
               exporter_name, exporter_tax_code, consignee_name, incoterms,
               weight, weight_unit, package_count, package_unit,
               invoice_date, departure_date,
               destination_code, destination_name,
               transport_mode, exchange_rate,
               artifact_id, indexed_at
        from hub.bcct_rows
        where client_id = %s and upper(customs_code) = any(%s)
    """
    params: list = [client_id, code_list]
    if direction:
        sql += " and direction = %s"
        params.append(direction)
    sql += " order by registration_date desc nulls last, declaration_no, line_no limit %s offset %s"
    params.extend([safe_limit + 1, offset])
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            items = [dict(zip(cols, r)) for r in cur.fetchall()]
    if include_material_identity:
        _attach_material_identity(
            items, client_id=client_id, candidate_limit=cand_limit,
        )
    else:
        for it in items:
            it.pop("material_identity", None)
    return _json(_paged(items, offset=offset, limit=safe_limit))


_DECLARATIONS_NOS_MAX = 500


def _parse_declaration_nos_param(value: str | None) -> list[str] | None:
    """Split + dedupe comma-separated declaration numbers, preserving
    case (declaration numbers are typically digits but the source-of-
    truth is exact string match per `(client_id, declaration_no,
    direction)` identity). None / empty → None (no filter applied).
    Order preserved for log stability. >500 → 400."""
    if value is None or not value.strip():
        return None
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in value.split(","):
        token = raw.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    if not tokens:
        return None
    if len(tokens) > _DECLARATIONS_NOS_MAX:
        raise HTTPException(400, "too many declaration_nos")
    return tokens


@router.get("/clients/{client_id}/declarations")
async def api_list_declarations(
    client_id: str,
    direction: str | None = None,
    declaration_nos: str | None = None,
    has_files: str | None = None,
    cursor: str | None = None,
    limit: int = 200,
    authorization: str | None = Header(None),
):
    """Per-declaration summary with file_count from
    hub.customs_declaration_files. Sister-app entry for CO's TKX/TKN
    "có tờ khai / thiếu tờ khai" status. File presence is what staff
    care about — BCCT row presence alone is not equivalent.

    Contract spec:
    `barry-CO-main/.ai/api-requests/2026-05-15-declaration-file-status.md`.

    Identity is `(client_id, declaration_no, direction)`. Same
    declaration_no can exist in both directions and ships as two rows.
    `declaration_nos` is exact-match (no normalization) — preserves
    Data Hub's canonical declaration_no string."""
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    if direction is not None and direction not in ("import", "export"):
        raise HTTPException(400, "invalid_direction")
    has_files_filter: bool | None = None
    if has_files is not None:
        if has_files == "yes":
            has_files_filter = True
        elif has_files == "no":
            has_files_filter = False
        else:
            raise HTTPException(400, "invalid_has_files")
    decl_nos = _parse_declaration_nos_param(declaration_nos)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")

    from app.stores.customs_declaration_files import (
        list_declarations_with_status,
    )

    # When declaration_nos is provided: single-page return, no cursor.
    # Cap at the declaration_nos length (CO contract: "return all
    # requested matches up to the maximum request size and no cursor").
    if decl_nos is not None:
        summaries = list_declarations_with_status(
            client_id,
            direction=direction,
            has_files=has_files_filter,
            declaration_nos=decl_nos,
            limit=_DECLARATIONS_NOS_MAX,
            offset=0,
        )
        return _json({
            "items": [
                {
                    "declaration_no": s.declaration_no,
                    "direction": s.direction,
                    "bcct_line_count": s.bcct_line_count,
                    "file_count": s.file_count,
                    "earliest_bcct_date": (
                        s.earliest_bcct_date.isoformat()
                        if s.earliest_bcct_date else None
                    ),
                }
                for s in summaries
            ],
            "next_cursor": None,
        })

    offset, safe_limit = _page_args(cursor, limit)
    safe_limit = min(safe_limit, _DECLARATIONS_NOS_MAX)
    summaries = list_declarations_with_status(
        client_id,
        direction=direction,
        has_files=has_files_filter,
        limit=safe_limit + 1,
        offset=offset,
    )
    items = [
        {
            "declaration_no": s.declaration_no,
            "direction": s.direction,
            "bcct_line_count": s.bcct_line_count,
            "file_count": s.file_count,
            "earliest_bcct_date": (
                s.earliest_bcct_date.isoformat()
                if s.earliest_bcct_date else None
            ),
        }
        for s in summaries
    ]
    return _json(_paged(items, offset=offset, limit=safe_limit))


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


_BOM_ARTIFACT_ALLOWED_INTENTS = {
    "asserted_technical", "staff_edit", "derived",
    "customs_declared", "modified_for_case",
}


def _parse_bom_intents(value: str | None) -> set[str] | None:
    """Parse `intents` query param per CO API request 2026-05-28.
    Returns None when omitted (caller falls back to single `intent`)."""
    if value is None or value == "":
        return None
    tokens = {t.strip() for t in value.split(",") if t.strip()}
    if not tokens:
        return None
    bad = tokens - _BOM_ARTIFACT_ALLOWED_INTENTS
    if bad:
        raise HTTPException(400, "invalid_intents")
    return tokens


def _validate_lifecycle(value: str | None) -> str:
    if value is None or value == "":
        return "all"
    if value not in {"active", "all"}:
        raise HTTPException(400, "invalid_lifecycle")
    return value


def _validate_shape_filter(value: str | None) -> str:
    if value is None or value == "":
        return "any"
    if value not in {"flat", "any"}:
        raise HTTPException(400, "invalid_shape")
    return value


def _parse_bool_param(value: str | None, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    if value == "true":
        return True
    if value == "false":
        return False
    raise HTTPException(400, "invalid_boolean")


def _apply_bom_artifact_filters(
    versions: list[dict],
    *,
    lifecycle: str,
    shape: str,
    intents: set[str] | None,
    intent_singular: str | None,
    latest_per_variant: bool,
    case_id: str | None,
) -> list[dict]:
    """Apply CO picker filter chain to raw artifact history.

    Order: lifecycle → shape → intent(s) → modified_for_case scoping
    by case_id → latest-per-(variant_id, strategy) partition.
    """
    out = versions
    if lifecycle == "active":
        out = [
            v for v in out
            if v.get("status") == "published" and v.get("tombstoned_at") is None
        ]
    if shape == "flat":
        out = [
            v for v in out
            if v.get("flatten_status") in ("flattened", "not_applicable")
        ]
    if intents is not None:
        out = [v for v in out if v.get("intent") in intents]
    elif intent_singular:
        out = [v for v in out if v.get("intent") == intent_singular]
    if intents is not None and "modified_for_case" in intents:
        # modified_for_case rows only kept for matching case_id; rows for
        # other intents pass through untouched. Also exclude
        # modified_for_case rows that lack context.case_id entirely.
        def _scope_ok(v: dict) -> bool:
            if v.get("intent") != "modified_for_case":
                return True
            row_case = (v.get("context") or {}).get("case_id")
            return bool(row_case) and row_case == case_id
        out = [v for v in out if _scope_ok(v)]
    if latest_per_variant:
        # Partition by (bom_variant_id COALESCE 'default', flatten_strategy);
        # keep newest published_at, then highest artifact_no, then
        # artifact_id desc for determinism.
        def _sort_key(v: dict):
            return (
                v.get("published_at") or "",
                v.get("artifact_no") or 0,
                v.get("artifact_id") or "",
            )
        seen: dict[tuple, dict] = {}
        for v in sorted(out, key=_sort_key, reverse=True):
            key = (
                v.get("bom_variant_id") or "default",
                v.get("flatten_strategy") or "",
            )
            if key not in seen:
                seen[key] = v
        out = sorted(
            seen.values(),
            key=_sort_key,
            reverse=True,
        )
    return out


@router.get("/products/{product_code}/bom/artifacts")
async def api_bom_artifacts(
    product_code: str, client_id: str,
    actor: str | None = None, intent: str | None = None,
    intents: str | None = None,
    lifecycle: str | None = None,
    shape: str | None = None,
    latest_per_variant: str | None = None,
    case_id: str | None = None,
    authorization: str | None = Header(None),
):
    """List BOM artifacts for `(client_id, product_code)` with optional
    picker filters per CO API request 2026-05-28.

    Defaults preserve back-compat (lifecycle=all, shape=any,
    latest_per_variant=false). Picker passes explicit
    `lifecycle=active&shape=flat&latest_per_variant=true&intents=…`
    to get the curated list. Existing admin/debug callers without new
    params see the raw history unchanged.

    Response carries `filter_applied` echo so consumers can detect
    server-side support and fall back to client-side filtering when
    absent (older deployments).
    """
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    intents_set = _parse_bom_intents(intents)
    lifecycle_v = _validate_lifecycle(lifecycle)
    shape_v = _validate_shape_filter(shape)
    latest = _parse_bool_param(latest_per_variant, default=False)
    if intent and intents_set is not None and intent not in intents_set:
        raise HTTPException(400, "conflicting_intent_params")
    if intents_set is not None and "modified_for_case" in intents_set \
            and not case_id:
        raise HTTPException(400, "case_id_required")
    versions = list_artifacts_for_product(
        client_id=client_id, product_code=product_code,
    )
    if actor:
        versions = [v for v in versions if v.get("actor") == actor]
    filtered = _apply_bom_artifact_filters(
        versions,
        lifecycle=lifecycle_v, shape=shape_v,
        intents=intents_set, intent_singular=intent,
        latest_per_variant=latest, case_id=case_id,
    )
    return _json({
        "items": filtered,
        "total_estimate": len(filtered),
        "filter_applied": {
            "lifecycle": lifecycle_v,
            "shape": shape_v,
            "intents": (
                sorted(intents_set) if intents_set is not None
                else ([intent] if intent else None)
            ),
            "latest_per_variant": latest,
            "case_id": case_id,
        },
    })


_BOM_BATCH_MAX_PRODUCTS = 500
_BOM_BATCH_DEFAULT_LIMIT = 200


def _bom_batch_cursor_encode(after_product_code: str) -> str:
    import base64 as _b64
    import json as _json_mod
    raw = _json_mod.dumps({"after_pc": after_product_code}).encode("utf-8")
    return _b64.urlsafe_b64encode(raw).decode("ascii")


def _bom_batch_cursor_decode(cursor: str | None) -> str | None:
    if not cursor:
        return None
    import base64 as _b64
    import json as _json_mod
    try:
        raw = _b64.urlsafe_b64decode(cursor.encode("ascii"))
        return _json_mod.loads(raw)["after_pc"]
    except Exception:
        raise HTTPException(400, "invalid_cursor")


@router.post("/products/bom/artifacts:batch")
async def api_bom_artifacts_batch(
    request: Request,
    authorization: str | None = Header(None),
):
    """Multi-product fan-in of GET /products/{product_code}/bom/artifacts.

    One round-trip replaces CO's per-product (list + per-artifact) fan-out.
    Each results[product_code] envelope is byte-identical to calling the
    per-product endpoint with the same filters (plus embedded rows when
    include_rows=true). Reuses the SAME filter chain
    (_apply_bom_artifact_filters) and the SAME row serialization columns
    (get_rows_for_artifacts == get_artifact_with_rows row shape), so the two
    contracts cannot drift.

    Read-only, idempotent; scope hub:read; one client per request. Genuine
    fan-in: 1 artifact query + (when include_rows) 3 batched ANY queries for
    just the current page's artifacts — independent of product count.
    """
    from app.stores.bom import (
        list_artifact_meta_for_products,
        get_rows_for_artifacts,
        get_unresolved_for_artifacts,
        get_decisions_for_artifacts,
    )

    claims = _require_token(authorization)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "invalid_body")
    if not isinstance(body, dict):
        raise HTTPException(400, "invalid_body")

    client_id = body.get("client_id")
    if not client_id:
        raise HTTPException(400, "missing_client_id")

    raw_codes = body.get("product_codes")
    if not isinstance(raw_codes, list) or not raw_codes:
        raise HTTPException(400, "empty_product_codes")
    # dedupe server-side; sort ASC (pagination order is product_code ASC).
    product_codes = sorted({
        str(c) for c in raw_codes if c is not None and str(c) != ""
    })
    if not product_codes:
        raise HTTPException(400, "empty_product_codes")
    if len(product_codes) > _BOM_BATCH_MAX_PRODUCTS:
        raise HTTPException(400, "too_many_product_codes")

    _require_can_view_client(claims, client_id)

    # Batch defaults are the picker contract (active/flat/latest), unlike the
    # back-compat per-product defaults (all/any/false). Parity is "same
    # filters -> same items", not "same defaults".
    lifecycle_v = _validate_lifecycle(body.get("lifecycle") or "active")
    shape_v = _validate_shape_filter(body.get("shape") or "flat")
    latest_raw = body.get("latest_per_variant")
    latest = True if latest_raw is None else bool(latest_raw)
    include_rows_raw = body.get("include_rows")
    include_rows = True if include_rows_raw is None else bool(include_rows_raw)
    case_id = body.get("case_id")

    raw_intents = body.get("intents")
    if raw_intents is None:
        intents_set: set[str] | None = None
    else:
        if not isinstance(raw_intents, list):
            raise HTTPException(400, "invalid_intents")
        intents_set = {str(i) for i in raw_intents}
        if intents_set - _BOM_ARTIFACT_ALLOWED_INTENTS:
            raise HTTPException(400, "invalid_intents")
        if not intents_set:
            intents_set = None
    if intents_set is not None and "modified_for_case" in intents_set \
            and not case_id:
        raise HTTPException(400, "case_id_required")

    limit_raw = body.get("limit")
    try:
        limit = int(limit_raw) if limit_raw is not None else _BOM_BATCH_DEFAULT_LIMIT
    except (TypeError, ValueError):
        raise HTTPException(400, "invalid_limit")
    if limit <= 0:
        raise HTTPException(400, "invalid_limit")
    after_pc = _bom_batch_cursor_decode(body.get("cursor"))

    filter_applied = {
        "lifecycle": lifecycle_v,
        "shape": shape_v,
        "intents": sorted(intents_set) if intents_set is not None else None,
        "latest_per_variant": latest,
        "case_id": case_id,
    }

    # ONE artifact query for every requested product (fan-in), in the full
    # single-artifact shape, then the SAME per-product filter applied to each
    # product's slice. Items are therefore field-for-field identical to the
    # single-artifact GET (ARTIFACT FIELD PARITY), not the lighter list summary.
    arts_by_product = list_artifact_meta_for_products(
        client_id=client_id, product_codes=product_codes,
    )
    filtered_by_product: dict[str, list[dict]] = {}
    for pc in product_codes:
        filtered_by_product[pc] = _apply_bom_artifact_filters(
            arts_by_product.get(pc, []),
            lifecycle=lifecycle_v, shape=shape_v,
            intents=intents_set, intent_singular=None,
            latest_per_variant=latest, case_id=case_id,
        )

    # missing = requested codes with zero artifacts after filtering. Computed
    # over the full set (deterministic, complete) and returned on every page.
    missing = [pc for pc in product_codes if not filtered_by_product[pc]]

    # Pagination over product_code ASC. A product's items are never split
    # across pages; a single product whose item count exceeds `limit` is
    # emitted whole on its own page. Concatenating pages reproduces the set.
    present = [pc for pc in product_codes if filtered_by_product[pc]]
    if after_pc is not None:
        present = [pc for pc in present if pc > after_pc]
    page_products: list[str] = []
    count = 0
    for pc in present:
        n = len(filtered_by_product[pc])
        if page_products and count + n > limit:
            break
        page_products.append(pc)
        count += n
        if count >= limit:
            break
    remaining = len(page_products) < len(present)
    next_cursor = (
        _bom_batch_cursor_encode(page_products[-1])
        if remaining and page_products else None
    )

    # Embed rows only for artifacts on this page — one batched query class
    # each, regardless of product count.
    rows_by_aid: dict[str, list[dict]] = {}
    unresolved_by_aid: dict[str, list[dict]] = {}
    decisions_by_aid: dict[str, list[dict]] = {}
    if include_rows:
        page_aids = [
            it["artifact_id"]
            for pc in page_products for it in filtered_by_product[pc]
        ]
        if page_aids:
            rows_by_aid = get_rows_for_artifacts(page_aids)
            unresolved_by_aid = get_unresolved_for_artifacts(page_aids)
            decisions_by_aid = get_decisions_for_artifacts(page_aids)

    results: dict[str, dict] = {}
    for pc in page_products:
        items = []
        for v in filtered_by_product[pc]:
            if include_rows:
                aid = v["artifact_id"]
                items.append({
                    **v,
                    "rows": rows_by_aid.get(aid, []),
                    "unresolved": unresolved_by_aid.get(aid, []),
                    "decisions": decisions_by_aid.get(aid, []),
                })
            else:
                items.append(v)
        results[pc] = {"items": items, "filter_applied": filter_applied}

    return _json({
        "results": results,
        "missing": missing,
        "next_cursor": next_cursor,
    })


@router.get("/products/{product_code}/bom/artifacts/{artifact_id}")
async def api_bom_artifact_single(
    product_code: str, artifact_id: str, client_id: str,
    authorization: str | None = Header(None),
):
    """Single artifact (full shape) + rows/edges/unresolved/decisions,
    scoped to (client_id, product_code).

    The `artifact` object returned here is the canonical rich shape that the
    batch endpoint's items[*] mirror field-for-field (ARTIFACT FIELD PARITY).
    404 when the id does not exist or belongs to another client/product.
    """
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    data = get_artifact_with_rows(artifact_id)
    if not data or data["artifact"]["client_id"] != client_id \
            or data["artifact"]["product_code"] != product_code:
        raise HTTPException(404, "artifact not found")
    return _json(data)


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


# ─────────────────────────────────────────────────────────────────────
# Parser rules CRUD (per .ai/features/2026-05-08-configurable-bcct-parsing)
# ─────────────────────────────────────────────────────────────────────


def _require_can_edit_client_technical(claims: dict | None, client_id: str) -> None:
    """Parser-rules edits are technical config — dev role only."""
    if claims is None:
        return
    if _is_service_claims(claims):
        # Service tokens have no role concept. Reject — humans only.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "service tokens cannot edit parser rules",
        )
    if not auth.can_edit_client_technical(_user_from_claims(claims), client_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")


_RULE_FIELDS = (
    "rule_id", "client_id", "output_field", "priority", "pattern",
    "source_field", "match_group", "match_action", "no_match_action",
    "enabled", "notes", "created_by", "created_at",
)


def _serialize_rule(row: tuple) -> dict:
    out = dict(zip(_RULE_FIELDS, row))
    if out.get("created_at"):
        out["created_at"] = out["created_at"].isoformat()
    return out


def _validate_rule_body(body: dict, *, partial: bool = False) -> dict:
    """Validate + normalize a rule body. Returns kwargs ready for SQL.
    `partial=True` for PATCH (allows missing fields)."""
    from app.parsers.client_parser_rules import compile_pattern, InvalidPatternError

    fields = {}
    if not partial:
        for k in ("output_field", "priority", "pattern"):
            if k not in body or body[k] in (None, ""):
                raise HTTPException(422, f"missing required field: {k}")
    if "pattern" in body:
        try:
            compile_pattern(body["pattern"])  # validate; discard compiled object
        except InvalidPatternError as e:
            raise HTTPException(400, str(e))
        fields["pattern"] = body["pattern"]
    if "output_field" in body:
        fields["output_field"] = body["output_field"]
    if "priority" in body:
        fields["priority"] = int(body["priority"])
    if "source_field" in body:
        fields["source_field"] = body["source_field"] or "goods_name"
    if "match_group" in body:
        fields["match_group"] = int(body["match_group"])
    if "match_action" in body:
        if body["match_action"] not in ("capture", "reject"):
            raise HTTPException(422, "match_action must be 'capture' or 'reject'")
        fields["match_action"] = body["match_action"]
    if "no_match_action" in body:
        if body["no_match_action"] not in ("next_rule", "return_null"):
            raise HTTPException(422, "no_match_action must be 'next_rule' or 'return_null'")
        fields["no_match_action"] = body["no_match_action"]
    if "notes" in body:
        fields["notes"] = body["notes"]
    if "enabled" in body:
        fields["enabled"] = bool(body["enabled"])
    return fields


@router.get("/clients/{client_id}/parser-rules")
async def api_list_parser_rules(
    client_id: str,
    output_field: str | None = None,
    include_disabled: bool = False,
    authorization: str | None = Header(None),
):
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    sql = (
        "select rule_id, client_id, output_field, priority, pattern, "
        "source_field, match_group, match_action, no_match_action, "
        "enabled, notes, created_by, created_at "
        "from hub.client_parser_rules where client_id = %s"
    )
    params: list = [client_id]
    if output_field:
        sql += " and output_field = %s"
        params.append(output_field)
    if not include_disabled:
        sql += " and enabled"
    sql += " order by output_field, priority asc"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        items = [_serialize_rule(r) for r in cur.fetchall()]
    return _json({"items": items})


@router.post("/clients/{client_id}/parser-rules", status_code=201)
async def api_create_parser_rule(
    client_id: str, request: Request,
    authorization: str | None = Header(None),
):
    claims = _require_token(authorization)
    _require_can_edit_client_technical(claims, client_id)
    body = await request.json()
    fields = _validate_rule_body(body, partial=False)
    created_by = (claims or {}).get("sub") or "system"
    with connect(user_id=created_by) as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "insert into hub.client_parser_rules "
                "(client_id, output_field, priority, pattern, source_field, "
                " match_group, match_action, no_match_action, notes, created_by) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "returning rule_id, client_id, output_field, priority, pattern, "
                "  source_field, match_group, match_action, no_match_action, "
                "  enabled, notes, created_by, created_at",
                (client_id, fields["output_field"], fields["priority"],
                 fields["pattern"], fields.get("source_field", "goods_name"),
                 fields.get("match_group", 1),
                 fields.get("match_action", "capture"),
                 fields.get("no_match_action", "next_rule"),
                 fields.get("notes"), created_by),
            )
        except psycopg_errors.UniqueViolation:
            raise HTTPException(
                409, f"rule already exists for output_field={fields['output_field']!r} "
                f"priority={fields['priority']}",
            )
        row = cur.fetchone()
    from app.parsers.client_parser_rules import clear_rules_cache
    clear_rules_cache()
    return _json(_serialize_rule(row), status_code=201)


@router.patch("/clients/{client_id}/parser-rules/{rule_id}")
async def api_patch_parser_rule(
    client_id: str, rule_id: int, request: Request,
    authorization: str | None = Header(None),
):
    claims = _require_token(authorization)
    _require_can_edit_client_technical(claims, client_id)
    body = await request.json()
    fields = _validate_rule_body(body, partial=True)
    if not fields:
        raise HTTPException(422, "no editable fields in body")
    set_clauses = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [client_id, rule_id]
    user_id = (claims or {}).get("sub") or "system"
    with connect(user_id=user_id) as conn, conn.cursor() as cur:
        try:
            cur.execute(
                f"update hub.client_parser_rules set {set_clauses} "
                "where client_id = %s and rule_id = %s "
                "returning rule_id, client_id, output_field, priority, pattern, "
                "  source_field, match_group, match_action, no_match_action, "
                "  enabled, notes, created_by, created_at",
                values,
            )
        except psycopg_errors.UniqueViolation:
            raise HTTPException(
                409, "priority conflicts with another enabled rule",
            )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "rule not found")
    from app.parsers.client_parser_rules import clear_rules_cache
    clear_rules_cache()
    return _json(_serialize_rule(row))


@router.delete("/clients/{client_id}/parser-rules/{rule_id}")
async def api_delete_parser_rule(
    client_id: str, rule_id: int,
    authorization: str | None = Header(None),
):
    """Soft-disable: set enabled=false. Never hard DELETE the row
    (audit + history preserved per project_bom_immutable_principle.md)."""
    claims = _require_token(authorization)
    _require_can_edit_client_technical(claims, client_id)
    user_id = (claims or {}).get("sub") or "system"
    with connect(user_id=user_id) as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.client_parser_rules set enabled = false "
            "where client_id = %s and rule_id = %s and enabled "
            "returning rule_id",
            (client_id, rule_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "rule not found or already disabled")
    from app.parsers.client_parser_rules import clear_rules_cache
    clear_rules_cache()
    return _json({"rule_id": rule_id, "enabled": False})


@router.get("/clients/{client_id}/parser-rules/{rule_id}/history")
async def api_parser_rule_history(
    client_id: str, rule_id: int,
    limit: int = 100,
    authorization: str | None = Header(None),
):
    """Audit timeline for a single rule. Newest first. Driven by the
    AFTER INSERT/UPDATE/DELETE trigger on client_parser_rules."""
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    safe_limit = max(1, min(int(limit), 500))
    with connect() as conn, conn.cursor() as cur:
        # Confirm the rule belongs to this client (tenant isolation).
        cur.execute(
            "select 1 from hub.client_parser_rules "
            "where client_id = %s and rule_id = %s",
            (client_id, rule_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "rule not found")
        cur.execute(
            "select history_id, change_kind, changed_by, changed_at, "
            "       prev_state, new_state "
            "from hub.client_parser_rules_history "
            "where rule_id = %s "
            "order by changed_at desc "
            "limit %s",
            (rule_id, safe_limit),
        )
        items = []
        for hid, kind, by, at, prev, new in cur.fetchall():
            items.append({
                "history_id": hid,
                "change_kind": kind,
                "changed_by": by,
                "changed_at": at.isoformat() if at else None,
                "prev_state": prev,
                "new_state": new,
            })
    return _json({"rule_id": rule_id, "items": items})


@router.post("/clients/{client_id}/parser-rules/test")
async def api_test_parser_rules(
    client_id: str, request: Request,
    authorization: str | None = Header(None),
):
    """Preview rule output for a sample input. Read-only — does not
    persist. Returns per-rule trace + final output.

    Body: {output_field: str, sample_input: str}
    """
    claims = _require_token(authorization)
    _require_can_edit_client_technical(claims, client_id)
    body = await request.json()
    output_field = body.get("output_field") or "internal_code"
    sample = body.get("sample_input") or ""
    if not isinstance(sample, str):
        raise HTTPException(422, "sample_input must be a string")
    from app.parsers.client_parser_rules import load_rules

    rules = load_rules(client_id=client_id, output_field=output_field)
    trace: list[dict] = []
    final: str | None = None
    final_set = False
    for rule in rules:
        m = rule.compiled.search(sample)
        entry: dict = {
            "rule_id": rule.rule_id,
            "priority": rule.priority,
            "pattern": "<compiled>",  # don't echo back the pattern; staff sees in list
            "source_field": rule.source_field,
            "matched": bool(m),
            "match_action": rule.match_action,
            "no_match_action": rule.no_match_action,
        }
        if m:
            captured = m.group(rule.match_group) if rule.match_action == "capture" else None
            entry["captured"] = captured
            entry["matched_text"] = m.group(0)
            if not final_set:
                if rule.match_action == "reject":
                    final = None
                else:
                    final = captured
                final_set = True
        else:
            entry["captured"] = None
            if not final_set and rule.no_match_action == "return_null":
                final = None
                final_set = True
        trace.append(entry)
    return _json({"final_output": final, "trace": trace})


@router.get("/clients/{client_id}/materials/{material_code:path}/substitutes")
async def api_list_substitutes_v1(
    client_id: str, material_code: str,
    min_score: float = 0.5, include_rejected: bool = False,
    limit: int = 20,
    authorization: str | None = Header(None),
):
    """Sister-app entry for material substitutes lookup. Bearer auth
    (user JWT or service token with hub:read scope). Mirrors the
    cookie-auth UI route at /api/v1/clients/{c}/materials/{m}/substitutes
    (kept for the in-app catalog detail page).
    """
    from app.stores.material_substitutes import list_for_material
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    cands = list_for_material(
        client_id=client_id, material_code=material_code,
        min_score=min_score, include_rejected=include_rejected,
        limit=min(limit, 100),
    )
    return _json({
        "client_id": client_id,
        "material_a_code": material_code,
        "count": len(cands),
        "items": [
            {
                "material_b_code": c.material_b_code,
                "name": c.name,
                "category": c.category,
                "hs_code": c.hs_code,
                "sources": c.sources,
                "raw_scores": c.raw_scores,
                "combined_score": round(c.combined_score, 4),
                "confirmed": c.confirmed,
                "confirmed_at": (
                    c.confirmed_at.isoformat() if c.confirmed_at else None
                ),
            }
            for c in cands
        ],
    })


_DECLARATIONS_ZIP_MAX_NOS = 500


@router.get("/clients/{client_id}/declarations/download.zip")
async def api_download_declarations_zip(
    client_id: str,
    direction: str | None = None,
    declaration_nos: str | None = None,
    filename: str | None = None,
    authorization: str | None = Header(None),
):
    """Bearer-auth mirror of the operator cookie route at
    `/clients/{cid}/declarations/download.zip`. Returns the same ZIP
    bytes for server-to-server callers (CO's dossier builder).

    Spec: `barry-CO-main/.ai/api-requests/2026-05-28-bcct-declarations-download-bearer.md`.

    Auth: user JWT or service token with `hub:read` scope. The cookie
    route stays for operator-browser flow (no auth-mode retrofit per
    [[project_api_routing_convention]] — mirror, not dual-mode).
    """
    from fastapi.responses import Response
    from app.routes.declarations import (
        _build_declarations_zip, _parse_zip_declaration_nos,
        _safe_archive_filename,
    )
    from app.storage import get_backend
    from app.stores.customs_declaration_files import list_files_for_declarations
    claims = _require_token(authorization)
    _require_can_view_client(claims, client_id)
    if direction not in ("import", "export"):
        raise HTTPException(400, "invalid_direction")
    decl_nos = _parse_zip_declaration_nos(declaration_nos)
    if not decl_nos:
        raise HTTPException(400, "declaration_nos_required")
    if len(decl_nos) > _DECLARATIONS_ZIP_MAX_NOS:
        raise HTTPException(400, "too_many_declaration_nos")
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    archive_filename = _safe_archive_filename(
        filename,
        fallback=f"declarations_{client_id}_{direction}.zip",
    )
    files = list_files_for_declarations(
        client_id, decl_nos, direction=direction,
    )
    files_by_decl: dict[str, list] = {d: [] for d in decl_nos}
    for f in files:
        files_by_decl.setdefault(f.declaration_no, []).append(f)
    zip_bytes = _build_declarations_zip(
        client=client, direction=direction, requested=decl_nos,
        files_by_decl=files_by_decl, backend=get_backend(),
    )
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "content-disposition": (
                f'attachment; filename="{archive_filename}"'
            ),
            "content-length": str(len(zip_bytes)),
        },
    )


@router.get("/healthz")
async def api_healthz():
    return _json({"status": "ok"})
