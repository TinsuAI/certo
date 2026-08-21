"""Store for hub.nxt_artifacts / hub.nxt_lines (mig 082).

Immutable: edit = new artifact (see BOM immutable principle). Closing-implied is
derived at read time, never stored. Template render delegates to the
system_template adapter so the canonical schema lives in one place.
"""
from __future__ import annotations

import json
import secrets
from datetime import date

from app.database import connect
from app.parsers.nxt_adapters._common import NUMERIC_FIELDS, closing_implied
from app.parsers.nxt_adapters.system_template import render_template_xlsx  # noqa: F401

_LINE_FIELDS = (
    "internal_code", "customs_code", "name", "uom", "reported_role",
    *NUMERIC_FIELDS, "note",
)


def create_artifact(
    *, client_id: str, lines: list[dict],
    period_year: int | None = None, period_from=None, period_to=None,
    source_kind: str = "manual", adapter_name: str | None = None,
    file_sha256: str | None = None, file_path: str | None = None,
    note: str | None = None, created_by: str | None = None,
) -> str:
    # The settlement period is annual: year is the dedup key. Derive it from
    # period_to when a caller omits it so legacy call sites still supersede.
    if period_year is None and period_to is not None:
        period_year = period_to.year
    # Date-keyed consumers (settlement_link.period_end_link → BCQT) join on
    # period_from/period_to, not period_year. Default the exact range to the
    # calendar year so a year-only upload stays visible to them; the form still
    # lets the user override for off-calendar fiscal years.
    if period_year is not None:
        period_from = period_from or date(period_year, 1, 1)
        period_to = period_to or date(period_year, 12, 31)
    artifact_id = "nxt_" + secrets.token_urlsafe(12)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.nxt_artifacts
              (id, client_id, period_year, period_from, period_to, source_kind,
               adapter_name, file_sha256, file_path, note, created_by)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (artifact_id, client_id, period_year, period_from, period_to,
             source_kind, adapter_name, file_sha256, file_path, note,
             created_by),
        )
        # Supersede the prior current artifact for this (client, year): a
        # year-end NXT is one consolidated file per year, so a re-upload
        # replaces it. Without this, period_end_link would sum across both.
        # period_year is the dedup key; skip when absent (can't dedup).
        if period_year is not None:
            cur.execute(
                "update hub.nxt_artifacts set superseded_by=%s "
                "where client_id=%s and period_year=%s and superseded_by is null "
                "and id<>%s",
                (artifact_id, client_id, period_year, artifact_id),
            )
        for i, line in enumerate(lines, start=1):
            cur.execute(
                """
                insert into hub.nxt_lines
                  (artifact_id, line_no, internal_code, customs_code, name, uom,
                   reported_role, opening, inbound_total, out_tai_xuat,
                   out_chuyen_mdsd, out_xuat_sx, out_xuat_khac, outbound_total,
                   closing_reported, note, raw)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s::jsonb)
                """,
                (
                    artifact_id, i,
                    line.get("internal_code"), line.get("customs_code"),
                    line.get("name"), line.get("uom"), line.get("reported_role"),
                    line.get("opening"), line.get("inbound_total"),
                    line.get("out_tai_xuat"), line.get("out_chuyen_mdsd"),
                    line.get("out_xuat_sx"), line.get("out_xuat_khac"),
                    line.get("outbound_total"),
                    line.get("closing_reported"), line.get("note"),
                    json.dumps(line.get("raw"), ensure_ascii=False, default=str)
                    if line.get("raw") is not None else None,
                ),
            )
    return artifact_id


def get_artifact(artifact_id: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select id, client_id, period_year, period_from, period_to,
                   source_kind, adapter_name, file_sha256, file_path, note,
                   created_at, superseded_by
            from hub.nxt_artifacts where id=%s
            """,
            (artifact_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        art = {
            "id": row[0], "client_id": row[1], "period_year": row[2],
            "period_from": row[3], "period_to": row[4], "source_kind": row[5],
            "adapter_name": row[6], "file_sha256": row[7], "file_path": row[8],
            "note": row[9], "created_at": row[10], "superseded_by": row[11],
        }
        cur.execute(
            """
            select line_no, internal_code, customs_code, name, uom,
                   reported_role, opening, inbound_total, out_tai_xuat,
                   out_chuyen_mdsd, out_xuat_sx, out_xuat_khac, outbound_total,
                   closing_reported, note
            from hub.nxt_lines where artifact_id=%s order by line_no
            """,
            (artifact_id,),
        )
        cols = ("line_no", "internal_code", "customs_code", "name", "uom",
                "reported_role", "opening", "inbound_total", "out_tai_xuat",
                "out_chuyen_mdsd", "out_xuat_sx", "out_xuat_khac",
                "outbound_total", "closing_reported", "note")
        lines = []
        for r in cur.fetchall():
            line = dict(zip(cols, r))
            for f in NUMERIC_FIELDS:
                if line[f] is not None:
                    line[f] = float(line[f])
            line["closing_implied"] = closing_implied(line)
            lines.append(line)
    art["lines"] = lines
    return art


def list_artifacts(client_id: str, *, include_superseded: bool = False,
                   period_year: int | None = None) -> list[dict]:
    sql = (
        "select a.id, a.period_year, a.period_from, a.period_to, a.source_kind, "
        "       a.adapter_name, a.created_at, a.superseded_by, "
        "       count(l.id) as n_lines "
        "from hub.nxt_artifacts a "
        "left join hub.nxt_lines l on l.artifact_id = a.id "
        "where a.client_id=%s "
    )
    params: list = [client_id]
    if not include_superseded:
        sql += "and a.superseded_by is null "
    if period_year is not None:
        sql += "and a.period_year=%s "
        params.append(period_year)
    sql += ("group by a.id, a.period_year, a.period_from, a.period_to, "
            "a.source_kind, a.adapter_name, a.created_at, a.superseded_by "
            "order by a.period_year desc nulls last, a.period_to desc nulls last, "
            "a.created_at desc")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = ("id", "period_year", "period_from", "period_to", "source_kind",
                "adapter_name", "created_at", "superseded_by", "n_lines")
        return [dict(zip(cols, r)) for r in cur.fetchall()]


# ── Header + paged lines (detail view; avoid loading 20k lines per page) ──

def get_artifact_meta(artifact_id: str) -> dict | None:
    """Artifact header without its lines, plus the line count."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select a.id, a.client_id, a.period_year, a.period_from, a.period_to,
                   a.source_kind, a.adapter_name, a.file_sha256, a.note,
                   a.created_at, a.superseded_by, count(l.id) as n_lines
            from hub.nxt_artifacts a
            left join hub.nxt_lines l on l.artifact_id = a.id
            where a.id=%s
            group by a.id
            """,
            (artifact_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    cols = ("id", "client_id", "period_year", "period_from", "period_to",
            "source_kind", "adapter_name", "file_sha256", "note", "created_at",
            "superseded_by", "n_lines")
    return dict(zip(cols, row))


def _line_filter_sql(code: str | None, role: str | None) -> tuple[str, list]:
    """Build the optional WHERE fragment (and params) shared by list/count.
    `code` matches internal_code OR customs_code case-insensitively; `role`
    matches reported_role exactly. Fragments are literal — values stay bound."""
    sql = ""
    params: list = []
    if code:
        sql += (" and (upper(internal_code) = upper(%s) "
                "or upper(customs_code) = upper(%s))")
        params.extend([code, code])
    if role:
        sql += " and reported_role = %s"
        params.append(role)
    return sql, params


def list_lines(artifact_id: str, *, limit: int, offset: int,
               code: str | None = None, role: str | None = None) -> list[dict]:
    cols = ("line_no", "internal_code", "customs_code", "name", "uom",
            "reported_role", "opening", "inbound_total", "out_tai_xuat",
            "out_chuyen_mdsd", "out_xuat_sx", "out_xuat_khac", "outbound_total",
            "closing_reported", "note")
    where, fparams = _line_filter_sql(code, role)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            select line_no, internal_code, customs_code, name, uom,
                   reported_role, opening, inbound_total, out_tai_xuat,
                   out_chuyen_mdsd, out_xuat_sx, out_xuat_khac, outbound_total,
                   closing_reported, note
            from hub.nxt_lines where artifact_id=%s{where}
            order by line_no limit %s offset %s
            """,
            (artifact_id, *fparams, limit, offset),
        )
        lines = []
        for r in cur.fetchall():
            line = dict(zip(cols, r))
            for f in NUMERIC_FIELDS:
                if line[f] is not None:
                    line[f] = float(line[f])
            line["closing_implied"] = closing_implied(line)
            lines.append(line)
    return lines


def count_lines(artifact_id: str, *, code: str | None = None,
                role: str | None = None) -> int:
    where, fparams = _line_filter_sql(code, role)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"select count(*) from hub.nxt_lines where artifact_id=%s{where}",
            (artifact_id, *fparams),
        )
        return cur.fetchone()[0]
