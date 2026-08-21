"""Period-end reconciliation: links NXT closing ↔ next-period opening ↔ the
year-end inventory snapshot, per code, for a given date.

For settlement (BCQT consumer) the three should agree per material:
  NXT `tồn cuối kỳ` at period_to == date
  ≈ inventory snapshot `qty_book` at snapshot_date == date
  ≈ next period's NXT `tồn đầu kỳ` (period_from == date).
This is a read-only analytics join over the current (non-superseded) artifacts.
"""
from __future__ import annotations

from hub.app.database import connect


def _agg(cur, sql: str, params: tuple) -> dict[str, float]:
    cur.execute(sql, params)
    return {r[0]: float(r[1]) for r in cur.fetchall() if r[0] is not None}


def period_end_link(client_id: str, on_date) -> list[dict]:
    """Per-code {code, nxt_closing, next_opening, snapshot_book,
    snapshot_physical} joined on the material code, for `on_date`.

    Join is BEST-EFFORT on the raw code: NXT collapses to
    coalesce(internal_code, customs_code) while the snapshot uses its single
    `code` column. When the two sides carry different code systems they won't
    match and a code appears with values on only one side. A future pass can
    resolve both through the catalog / code_mappings to a canonical code.
    Aggregates only current (superseded_by is null) artifacts; create_artifact
    supersedes the prior upload per period so re-uploads don't double-count."""
    code_expr = "coalesce(nullif(l.internal_code,''), l.customs_code)"
    with connect() as conn, conn.cursor() as cur:
        closing = _agg(cur, f"""
            select {code_expr} as code, sum(l.closing_reported)
            from hub.nxt_lines l join hub.nxt_artifacts a on a.id = l.artifact_id
            where a.client_id = %s and a.period_to = %s and a.superseded_by is null
            group by code
        """, (client_id, on_date))
        opening = _agg(cur, f"""
            select {code_expr} as code, sum(l.opening)
            from hub.nxt_lines l join hub.nxt_artifacts a on a.id = l.artifact_id
            where a.client_id = %s and a.period_from = %s and a.superseded_by is null
            group by code
        """, (client_id, on_date))
        cur.execute("""
            select sl.code, sum(sl.qty_book), sum(sl.qty_physical)
            from hub.inventory_snapshot_lines sl
            join hub.inventory_snapshots s on s.id = sl.snapshot_id
            where s.client_id = %s and s.snapshot_date = %s
              and s.superseded_by is null
            group by sl.code
        """, (client_id, on_date))
        snap = {r[0]: (float(r[1]) if r[1] is not None else None,
                       float(r[2]) if r[2] is not None else None)
                for r in cur.fetchall() if r[0] is not None}

    codes = set(closing) | set(opening) | set(snap)
    out = []
    for code in sorted(codes):
        book, physical = snap.get(code, (None, None))
        out.append({
            "code": code,
            "nxt_closing": closing.get(code),
            "next_opening": opening.get(code),
            "snapshot_book": book,
            "snapshot_physical": physical,
        })
    return out
