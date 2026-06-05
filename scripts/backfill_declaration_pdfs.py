"""Backfill rendered declaration PDFs into the render cache.

Pre-renders every stored declaration `.xls` (the ECUS print form) to the
print-standard PDF and caches it content-addressed by sha256, so the
merge endpoint `/v1/hub/clients/{cid}/declarations/download.pdf` just
concatenates cached PDFs instead of rendering on the request path.

Idempotent: files already cached (and unsupported / missing-blob files)
are skipped. Safe to re-run after a bulk-ZIP upload or `RENDER_VERSION`
bump. Renders in batches (one soffice invocation per batch) to amortize
LibreOffice cold-start.

Usage:
  uv run python scripts/backfill_declaration_pdfs.py
  uv run python scripts/backfill_declaration_pdfs.py --client johnson-vn
  uv run python scripts/backfill_declaration_pdfs.py --batch 25 --limit 500
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from app.database import connect
from app.declarations_pdf import get_cached_pdf
from app.declarations_pdf import ensure_pdfs
from app.storage import get_backend
from app.stores.customs_declaration_files import DeclarationFile


def _fetch_xls_files(client_id: str | None) -> list[DeclarationFile]:
    sql = (
        "select * from hub.customs_declaration_files "
        "where file_kind in ('xls','xlsx')"
    )
    params: list = []
    if client_id:
        sql += " and client_id=%s"
        params.append(client_id)
    sql += " order by client_id, declaration_no, original_filename, id"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        return [DeclarationFile(**dict(zip(cols, r))) for r in cur.fetchall()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--client", default=None, help="restrict to one client_id")
    ap.add_argument("--batch", type=int, default=25,
                    help="files per soffice invocation (default 25)")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap total files processed (0 = all)")
    args = ap.parse_args()

    backend = get_backend()
    files = _fetch_xls_files(args.client)

    # Skip already-cached files up front so re-runs are cheap.
    pending = [
        f for f in files
        if not (f.sha256 and get_cached_pdf(f.sha256, backend))
    ]
    already = len(files) - len(pending)
    if args.limit:
        pending = pending[: args.limit]

    print(
        f"declaration .xls files: {len(files)} total, "
        f"{already} already cached, {len(pending)} to render"
    )

    rendered = failed = 0
    for i in range(0, len(pending), args.batch):
        chunk = pending[i : i + args.batch]
        out = ensure_pdfs(chunk, backend)
        for f in chunk:
            if out.get(f.id):
                rendered += 1
            else:
                failed += 1
                print(f"  FAILED id={f.id} {f.client_id}/{f.original_filename}")
        print(
            f"  ...{min(i + args.batch, len(pending))}/{len(pending)} "
            f"(rendered={rendered} failed={failed})"
        )

    print(f"done: rendered={rendered} failed={failed} skipped={already}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
