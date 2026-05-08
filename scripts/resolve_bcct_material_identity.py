"""Backfill script for `hub.bcct_rows.material_identity`.

Brief: .ai/features/2026-05-07-bcct-product-identity/brief.md (D10)

Use cases:
  - One-shot post-deploy fill for rows ingested before the column existed.
  - Refresh after parser_version bumps (drop-and-rebuild for a client).
  - Refresh after BOM/code-mappings churn that would change resolver output.

Idempotent: re-running yields identical output for unchanged inputs.

CLI:
    # Backfill only NULL rows (default — fastest, safest).
    uv run python -m scripts.resolve_bcct_material_identity --client-id growatt-vn

    # Recompute ALL rows for a client (drops cached parser_version).
    uv run python -m scripts.resolve_bcct_material_identity --client-id growatt-vn --recompute

    # Dry-run (no writes).
    uv run python -m scripts.resolve_bcct_material_identity --client-id growatt-vn --dry-run

    # All clients.
    uv run python -m scripts.resolve_bcct_material_identity --all-clients
"""
from __future__ import annotations

import argparse
import json
import sys

from app.database import connect
from app.parsers.derivations import compute_internal_code
from app.resolvers.bcct_material_identity import (
    ResolverContext, resolve_material_identity,
)


def _load_client(cur, client_id: str) -> dict | None:
    cur.execute(
        "select client_id, code_resolution_mode from hub.clients where client_id = %s",
        (client_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {"client_id": row[0], "code_resolution_mode": row[1]}


def _all_client_ids(cur) -> list[str]:
    cur.execute("select client_id from hub.clients order by client_id")
    return [r[0] for r in cur.fetchall()]


def resolve_for_client(client_id: str, *, recompute: bool, dry_run: bool,
                       batch_size: int = 1000) -> dict:
    """Walk every BCCT row for a client, computing material_identity.

    Returns a stats dict for reporting.
    """
    stats = {
        "client_id": client_id,
        "rows_examined": 0,
        "rows_updated": 0,
        "by_status": {},
    }
    with connect() as conn:
        with conn.cursor() as cur:
            client = _load_client(cur, client_id)
            if client is None:
                raise SystemExit(f"unknown client_id: {client_id}")
            ctx = ResolverContext.from_db(client_id, cur)
            where_clause = "" if recompute else " and material_identity is null"
            # mig 035: bcct_rows.internal_code dropped; computed per row via
            # compute_internal_code(row, client=client) at runtime.
            cur.execute(
                f"""
                select transaction_key, line_no, declaration_no,
                       customs_code, goods_name
                from hub.bcct_rows
                where client_id = %s{where_clause}
                order by registration_date, transaction_key, line_no
                """,
                (client_id,),
            )
            rows = cur.fetchall()
        stats["rows_examined"] = len(rows)

        def _resolve_row(txkey, line_no, decl, customs, gname):
            pid_row = {
                "transaction_key": txkey, "line_no": line_no,
                "declaration_no": decl, "customs_code": customs,
                "goods_name": gname,
            }
            pid_row["internal_code"] = compute_internal_code(pid_row, client=client)
            return resolve_material_identity(pid_row, ctx=ctx)

        if dry_run:
            for txkey, line_no, decl, customs, gname in rows:
                pid = _resolve_row(txkey, line_no, decl, customs, gname)
                s = pid["resolution_status"]
                stats["by_status"][s] = stats["by_status"].get(s, 0) + 1
            return stats
        with conn.cursor() as wcur:
            buf: list[tuple] = []
            for txkey, line_no, decl, customs, gname in rows:
                pid = _resolve_row(txkey, line_no, decl, customs, gname)
                s = pid["resolution_status"]
                stats["by_status"][s] = stats["by_status"].get(s, 0) + 1
                buf.append((json.dumps(pid, ensure_ascii=False),
                            client_id, txkey, line_no))
                if len(buf) >= batch_size:
                    _flush(wcur, buf)
                    stats["rows_updated"] += len(buf)
                    buf.clear()
            if buf:
                _flush(wcur, buf)
                stats["rows_updated"] += len(buf)
        conn.commit()
    return stats


def _flush(cur, buf: list[tuple]) -> None:
    cur.executemany(
        """
        update hub.bcct_rows
           set material_identity = %s::jsonb,
               indexed_at = now()
         where client_id = %s and transaction_key = %s and line_no = %s
        """,
        buf,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--client-id")
    g.add_argument("--all-clients", action="store_true")
    p.add_argument("--recompute", action="store_true",
                   help="Re-resolve every row (default: only NULL rows).")
    p.add_argument("--dry-run", action="store_true",
                   help="Show counts without writing.")
    args = p.parse_args(argv)

    if args.all_clients:
        with connect() as conn, conn.cursor() as cur:
            client_ids = _all_client_ids(cur)
    else:
        client_ids = [args.client_id]

    for cid in client_ids:
        stats = resolve_for_client(
            cid, recompute=args.recompute, dry_run=args.dry_run,
        )
        action = "would update" if args.dry_run else "updated"
        by_status = ", ".join(
            f"{k}={v}" for k, v in sorted(stats["by_status"].items())
        )
        print(
            f"[{cid}] examined={stats['rows_examined']} "
            f"{action}={stats['rows_updated']} status[{by_status}]"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
