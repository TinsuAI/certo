"""Store for hub.inventory_snapshots / hub.inventory_snapshot_lines (mig 082).

Immutable: edit = new snapshot. Variance derived at read time, never stored.
Template render delegates to the system_template adapter.
"""
from __future__ import annotations

import json
import secrets

from hub.app.database import connect
from hub.app.parsers.inventory_adapters._common import NUMERIC_FIELDS, variance
from hub.app.parsers.inventory_adapters.system_template import (  # noqa: F401
    render_template_xlsx,
)


def create_snapshot(
    *, client_id: str, lines: list[dict], snapshot_date=None,
    source_kind: str = "manual", adapter_name: str | None = None,
    file_sha256: str | None = None, file_path: str | None = None,
    note: str | None = None, created_by: str | None = None,
) -> str:
    snapshot_id = "inv_" + secrets.token_urlsafe(12)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.inventory_snapshots
              (id, client_id, snapshot_date, source_kind, adapter_name,
               file_sha256, file_path, note, created_by)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (snapshot_id, client_id, snapshot_date, source_kind, adapter_name,
             file_sha256, file_path, note, created_by),
        )
        # Supersede the prior current snapshot at this date (a re-upload of the
        # period-end stocktake replaces it). snapshot_date is the dedup key.
        if snapshot_date is not None:
            cur.execute(
                "update hub.inventory_snapshots set superseded_by=%s "
                "where client_id=%s and snapshot_date=%s and superseded_by is null "
                "and id<>%s",
                (snapshot_id, client_id, snapshot_date, snapshot_id),
            )
        for i, line in enumerate(lines, start=1):
            cur.execute(
                """
                insert into hub.inventory_snapshot_lines
                  (snapshot_id, line_no, code, name, uom, warehouse, batch,
                   qty_book, qty_physical, note, raw)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    snapshot_id, i, line.get("code"), line.get("name"),
                    line.get("uom"), line.get("warehouse"), line.get("batch"),
                    line.get("qty_book"), line.get("qty_physical"),
                    line.get("note"),
                    json.dumps(line.get("raw"), ensure_ascii=False, default=str)
                    if line.get("raw") is not None else None,
                ),
            )
    return snapshot_id


def get_snapshot(snapshot_id: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select id, client_id, snapshot_date, source_kind, adapter_name,
                   file_sha256, file_path, note, created_at, superseded_by
            from hub.inventory_snapshots where id=%s
            """,
            (snapshot_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        snap = {
            "id": row[0], "client_id": row[1], "snapshot_date": row[2],
            "source_kind": row[3], "adapter_name": row[4], "file_sha256": row[5],
            "file_path": row[6], "note": row[7], "created_at": row[8],
            "superseded_by": row[9],
        }
        cur.execute(
            """
            select line_no, code, name, uom, warehouse, batch,
                   qty_book, qty_physical, note
            from hub.inventory_snapshot_lines where snapshot_id=%s
            order by line_no
            """,
            (snapshot_id,),
        )
        cols = ("line_no", "code", "name", "uom", "warehouse", "batch",
                "qty_book", "qty_physical", "note")
        lines = []
        for r in cur.fetchall():
            line = dict(zip(cols, r))
            for f in NUMERIC_FIELDS:
                if line[f] is not None:
                    line[f] = float(line[f])
            line["variance"] = variance(line)
            lines.append(line)
    snap["lines"] = lines
    return snap


def list_snapshots(client_id: str, *, include_superseded: bool = False,
                   year: int | None = None) -> list[dict]:
    sql = (
        "select s.id, s.snapshot_date, s.source_kind, s.adapter_name, "
        "       s.created_at, s.superseded_by, count(l.id) as n_lines "
        "from hub.inventory_snapshots s "
        "left join hub.inventory_snapshot_lines l on l.snapshot_id = s.id "
        "where s.client_id=%s "
    )
    params: list = [client_id]
    if not include_superseded:
        sql += "and s.superseded_by is null "
    if year is not None:
        sql += "and extract(year from s.snapshot_date) = %s "
        params.append(year)
    sql += ("group by s.id, s.snapshot_date, s.source_kind, s.adapter_name, "
            "s.created_at, s.superseded_by "
            "order by s.snapshot_date desc nulls last, s.created_at desc")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = ("id", "snapshot_date", "source_kind", "adapter_name",
                "created_at", "superseded_by", "n_lines")
        return [dict(zip(cols, r)) for r in cur.fetchall()]


# ── Header + paged lines (detail view) ──────────────────────────────────

def get_snapshot_meta(snapshot_id: str) -> dict | None:
    """Snapshot header without its lines, plus the line count."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select s.id, s.client_id, s.snapshot_date, s.source_kind,
                   s.adapter_name, s.file_sha256, s.note, s.created_at,
                   s.superseded_by, count(l.id) as n_lines
            from hub.inventory_snapshots s
            left join hub.inventory_snapshot_lines l on l.snapshot_id = s.id
            where s.id=%s
            group by s.id
            """,
            (snapshot_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    cols = ("id", "client_id", "snapshot_date", "source_kind", "adapter_name",
            "file_sha256", "note", "created_at", "superseded_by", "n_lines")
    return dict(zip(cols, row))


def _line_filter_sql(code: str | None, warehouse: str | None) -> tuple[str, list]:
    """Optional WHERE fragment (and params) shared by list/count. `code`
    matches case-insensitively; `warehouse` matches exactly. Fragments are
    literal — values stay bound."""
    sql = ""
    params: list = []
    if code:
        sql += " and upper(code) = upper(%s)"
        params.append(code)
    if warehouse:
        sql += " and warehouse = %s"
        params.append(warehouse)
    return sql, params


def list_lines(snapshot_id: str, *, limit: int, offset: int,
               code: str | None = None,
               warehouse: str | None = None) -> list[dict]:
    cols = ("line_no", "code", "name", "uom", "warehouse", "batch",
            "qty_book", "qty_physical", "note")
    where, fparams = _line_filter_sql(code, warehouse)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            select line_no, code, name, uom, warehouse, batch,
                   qty_book, qty_physical, note
            from hub.inventory_snapshot_lines where snapshot_id=%s{where}
            order by line_no limit %s offset %s
            """,
            (snapshot_id, *fparams, limit, offset),
        )
        lines = []
        for r in cur.fetchall():
            line = dict(zip(cols, r))
            for f in NUMERIC_FIELDS:
                if line[f] is not None:
                    line[f] = float(line[f])
            line["variance"] = variance(line)
            lines.append(line)
    return lines


def count_lines(snapshot_id: str, *, code: str | None = None,
                warehouse: str | None = None) -> int:
    where, fparams = _line_filter_sql(code, warehouse)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.inventory_snapshot_lines "
            f"where snapshot_id=%s{where}",
            (snapshot_id, *fparams),
        )
        return cur.fetchone()[0]
