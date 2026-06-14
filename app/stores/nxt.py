"""Store for hub.nxt_artifacts / hub.nxt_lines (mig 082).

Immutable: edit = new artifact (see BOM immutable principle). Closing-implied is
derived at read time, never stored. Template render delegates to the
system_template adapter so the canonical schema lives in one place.
"""
from __future__ import annotations

import json
import secrets

from app.database import connect
from app.parsers.nxt_adapters._common import NUMERIC_FIELDS, closing_implied
from app.parsers.nxt_adapters.system_template import render_template_xlsx  # noqa: F401

_LINE_FIELDS = (
    "internal_code", "customs_code", "name", "uom", "reported_role",
    *NUMERIC_FIELDS, "note",
)


def create_artifact(
    *, client_id: str, lines: list[dict],
    period_from=None, period_to=None,
    source_kind: str = "manual", adapter_name: str | None = None,
    file_sha256: str | None = None, file_path: str | None = None,
    note: str | None = None, created_by: str | None = None,
) -> str:
    artifact_id = "nxt_" + secrets.token_urlsafe(12)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.nxt_artifacts
              (id, client_id, period_from, period_to, source_kind,
               adapter_name, file_sha256, file_path, note, created_by)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (artifact_id, client_id, period_from, period_to, source_kind,
             adapter_name, file_sha256, file_path, note, created_by),
        )
        for i, line in enumerate(lines, start=1):
            cur.execute(
                """
                insert into hub.nxt_lines
                  (artifact_id, line_no, internal_code, customs_code, name, uom,
                   reported_role, opening, inbound_total, out_tai_xuat,
                   out_chuyen_mdsd, out_xuat_sx, out_xuat_khac, closing_reported,
                   note, raw)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s::jsonb)
                """,
                (
                    artifact_id, i,
                    line.get("internal_code"), line.get("customs_code"),
                    line.get("name"), line.get("uom"), line.get("reported_role"),
                    line.get("opening"), line.get("inbound_total"),
                    line.get("out_tai_xuat"), line.get("out_chuyen_mdsd"),
                    line.get("out_xuat_sx"), line.get("out_xuat_khac"),
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
            select id, client_id, period_from, period_to, source_kind,
                   adapter_name, file_sha256, file_path, note, created_at,
                   superseded_by
            from hub.nxt_artifacts where id=%s
            """,
            (artifact_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        art = {
            "id": row[0], "client_id": row[1], "period_from": row[2],
            "period_to": row[3], "source_kind": row[4], "adapter_name": row[5],
            "file_sha256": row[6], "file_path": row[7], "note": row[8],
            "created_at": row[9], "superseded_by": row[10],
        }
        cur.execute(
            """
            select line_no, internal_code, customs_code, name, uom,
                   reported_role, opening, inbound_total, out_tai_xuat,
                   out_chuyen_mdsd, out_xuat_sx, out_xuat_khac, closing_reported,
                   note
            from hub.nxt_lines where artifact_id=%s order by line_no
            """,
            (artifact_id,),
        )
        cols = ("line_no", "internal_code", "customs_code", "name", "uom",
                "reported_role", "opening", "inbound_total", "out_tai_xuat",
                "out_chuyen_mdsd", "out_xuat_sx", "out_xuat_khac",
                "closing_reported", "note")
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


def list_artifacts(client_id: str, *, include_superseded: bool = False) -> list[dict]:
    sql = (
        "select a.id, a.period_from, a.period_to, a.source_kind, a.adapter_name, "
        "       a.created_at, a.superseded_by, count(l.id) as n_lines "
        "from hub.nxt_artifacts a "
        "left join hub.nxt_lines l on l.artifact_id = a.id "
        "where a.client_id=%s "
    )
    if not include_superseded:
        sql += "and a.superseded_by is null "
    sql += ("group by a.id, a.period_from, a.period_to, a.source_kind, "
            "a.adapter_name, a.created_at, a.superseded_by "
            "order by a.period_to desc nulls last, a.created_at desc")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (client_id,))
        cols = ("id", "period_from", "period_to", "source_kind", "adapter_name",
                "created_at", "superseded_by", "n_lines")
        return [dict(zip(cols, r)) for r in cur.fetchall()]
