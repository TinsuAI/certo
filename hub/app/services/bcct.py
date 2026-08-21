"""BCCT query — shared by GET /v1/hub/bcct and the in-process client."""
from __future__ import annotations

from datetime import datetime, timezone

from hub.app.database import connect
from hub.app.services.materials import serialize

_BCCT_SELECT = """
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

_ORDER = " order by registration_date desc nulls last, declaration_no, line_no"


def list_bcct(
    client_id: str,
    *,
    year: int | None = None,
    direction: str | None = None,
    declaration_no: str | None = None,
    since_ts=None,
    offset: int = 0,
    limit: int | None = None,
    fetch_extra: bool = False,
    include_material_identity: bool = False,
    candidate_limit: int = 5,
    want_tombstones: bool = False,
) -> dict:
    """BCCT rows plus `server_time`, and `tombstones` when asked for.

    Returns an envelope rather than a bare list because callers use
    `server_time` as the high-water mark for their next incremental pull.

    `limit=None` returns every matching row in one query. The route passes an
    explicit limit; skipping the OFFSET walk is worth 5.62s -> 2.66s on
    johnson-vn's 65,846 rows.
    """
    sql = _BCCT_SELECT
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
    sql += _ORDER
    if limit is not None:
        sql += " limit %s offset %s"
        params.extend([limit + 1 if fetch_extra else limit, offset])

    server_time = datetime.now(timezone.utc)
    tombstones: list[dict] = []
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            items = [dict(zip(cols, r)) for r in cur.fetchall()]
            if want_tombstones and offset == 0:
                # Spec: tombstones are returned in full on the first page.
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
        from hub.app.routes.api import _attach_material_identity

        _attach_material_identity(items, client_id=client_id, candidate_limit=candidate_limit)
    else:
        for it in items:
            it.pop("material_identity", None)
    return {
        "items": items,
        "server_time": server_time,
        "tombstones": tombstones,
    }
