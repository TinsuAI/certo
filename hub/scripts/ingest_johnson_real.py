"""Ingest Johnson real BCCT NK + XK from canonical source path.

Usage:
    uv run python scripts/ingest_johnson_real.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from hub.app.parsers.bcct import parse_bcct_workbook
from hub.app.routes.bcct import _insert_bcct
from hub.scripts.ingest_curated_xlsx_direct import _stub_upload


CLIENT_ID = "johnson-vn"
SOURCE_ROOT = Path(__file__).resolve().parent.parent / "data" / "source_inventory" / "johnson-vn" / "2026-05-07-updated" / "Johnson"
NK_FILE = SOURCE_ROOT / "BaoCaoHangChiTietNK - JOHNSON - ALL (06.05.2026).xls"
XK_FILE = SOURCE_ROOT / "BaoCaoHangChiTietXK JOHNSON - ALL (06.05.2026).xls"


def _ingest_one(path: Path) -> int:
    """Parse + filter null-date rows (gen-col year requires not-null) +
    insert. Returns row count actually inserted."""
    parsed = parse_bcct_workbook(path.read_bytes())
    if not parsed:
        print(f"  {path.name}: 0 rows parsed, skipped")
        return 0

    valid = [r for r in parsed if r.get("registration_date") is not None]
    skipped = len(parsed) - len(valid)
    if skipped:
        bad_decls = sorted({
            r.get("declaration_no") for r in parsed
            if r.get("registration_date") is None
        })
        print(f"  WARN: skipped {skipped} rows with null Ngày ĐK "
              f"(declarations: {bad_decls})")

    upload_id = _stub_upload(CLIENT_ID, "bcct", path.name)
    n = _insert_bcct(
        client_id=CLIENT_ID, rows=valid, upload_id=upload_id,
        client={"client_id": CLIENT_ID,
                "code_resolution_mode": "identity"},
    )
    print(f"  {path.name}: {n} rows inserted (upload_id={upload_id})")
    return n


def main() -> int:
    if not NK_FILE.exists():
        print(f"ERROR: NK not found: {NK_FILE}", file=sys.stderr)
        return 2
    if not XK_FILE.exists():
        print(f"ERROR: XK not found: {XK_FILE}", file=sys.stderr)
        return 2

    print("=== Johnson real BCCT ingest ===")
    print(f"NK: {NK_FILE}")
    print(f"XK: {XK_FILE}")
    print()

    t0 = time.monotonic()
    nk_n = _ingest_one(NK_FILE)
    t1 = time.monotonic()
    print(f"  → NK done in {t1 - t0:.1f}s")

    xk_n = _ingest_one(XK_FILE)
    t2 = time.monotonic()
    print(f"  → XK done in {t2 - t1:.1f}s")

    print()
    print(f"Total: {nk_n + xk_n} rows in {t2 - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
