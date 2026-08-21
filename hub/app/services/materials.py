"""Materials query — shared by GET /v1/hub/materials and the in-process client."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from hub.app.database import connect


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
           m.material_group,
           mgmap.item_category,
           -- customs_relevance computed inline (mirrors hub.v_material_classification,
           -- which is the canonical def + parity-tested) to avoid re-joining the
           -- heavy v_material_roles aggregation a second time via the view.
           -- placeholder-only comes first (mig 091): those codes have real
           -- has_imports via paren lines and must not read as declarable.
           -- Then has_imports precedes the rác check: a real import wins over
           -- the MG heuristic (mig 079).
           case
             when po.material_code is not null then 'excluded_non_material'
             when m.material_group is null then null
             when coalesce(vmr.has_imports, false) then 'declarable'
             when mgmap.material_group is null then 'review'
             when mgmap.is_declarable = false then 'excluded_non_material'
             else 'declarable_unmatched'
           end as customs_relevance,
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
    left join hub.client_material_group_map mgmap
           on mgmap.client_id = m.client_id
          and mgmap.material_group = m.material_group
    left join hub.v_placeholder_only_codes po
           on po.client_id = m.client_id
          and po.material_code = m.material_code
"""

def _status_filter_sql(status: str | None, params: list) -> str:
    """Issue #31: alive-only by default — NOT `='active'`: approval is
    `source` promotion + the candidates queue, so `deprecated` marks a live
    material CO depends on. An explicit `?status=` selects exactly that one
    status. (#49 dropped `under_review`; the default set is unchanged.)"""
    if status:
        params.append(status)
        return " and m.status = %s"
    return " and m.status not in ('tombstoned', 'inactive')"


def serialize(v: Any):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: serialize(x) for k, x in v.items()}
    if isinstance(v, list):
        return [serialize(x) for x in v]
    return v


def list_materials(
    client_id: str,
    *,
    category: str | None = None,
    status: str | None = None,
    offset: int = 0,
    limit: int | None = None,
    fetch_extra: bool = False,
) -> list[dict]:
    """Materials for a client, JSON-shaped.

    `limit=None` returns every row in a single query — no OFFSET walk. The HTTP
    route passes an explicit limit plus `fetch_extra=True` to get the one
    lookahead row it needs for `next_cursor`.
    """
    sql = _MATERIALS_SELECT_WITH_ROLES + " where m.client_id = %s"
    params: list = [client_id]
    if category:
        sql += " and m.category = %s"
        params.append(category)
    sql += _status_filter_sql(status, params)
    sql += " order by m.material_code"
    if limit is not None:
        sql += " limit %s offset %s"
        params.extend([limit + 1 if fetch_extra else limit, offset])
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
    return serialize(items)
