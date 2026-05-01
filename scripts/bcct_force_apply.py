"""Ops bypass: apply a BCCT file directly, ignoring the route's confirm gate.

The web route requires staff confirmation for any UPDATE on existing rows
(see Stage C1 of .ai/features/2026-05-04-bcct-overhaul-and-llm-parsing.md).
That's intentional UX safety, but ops/data-fix work needs a sanctioned
escape hatch — this script runs locally with DB access, sets the audit-log
GUC to a synthetic actor (so the trigger writes 'ops:script' rather than
'system'), and applies the file as-if it had been confirmed.

Usage:
    uv run python scripts/bcct_force_apply.py \
        --client growatt-vn \
        --file ~/path/to/BCCT.xls

By default the script does NOT delete orphan rows. Pass --confirm-orphans
to enable that.

This is a developer-only tool. Not meant to be invoked from any automation
that customers / agency staff have access to.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the app package importable when run from repo root.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from app.database import connect  # noqa: E402
from app.parsers.bcct import parse_bcct_workbook  # noqa: E402
from app.parsers.goods_name import internal_code_parser_for  # noqa: E402
from app.routes.bcct import (  # noqa: E402
    _apply_bcct_rows,
    _classify_rows,
)
from app.routes.clients import get_client  # noqa: E402


OPS_ACTOR_ID = "ops:script"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply a BCCT file bypassing the route confirm gate.",
    )
    parser.add_argument("--client", required=True, help="client_id")
    parser.add_argument("--file", required=True, help="path to BCCT .xlsx/.xls")
    parser.add_argument(
        "--confirm-orphans", action="store_true",
        help="also DELETE rows in DB scope that are missing from this file",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="parse + classify; print summary; don't apply",
    )
    args = parser.parse_args()

    client_id = args.client
    file_path = Path(args.file).expanduser().resolve()
    if not file_path.exists():
        sys.stderr.write(f"file not found: {file_path}\n")
        return 2

    client = get_client(client_id)
    if not client:
        sys.stderr.write(f"client not found: {client_id}\n")
        return 2

    blob = file_path.read_bytes()
    rows = parse_bcct_workbook(blob)
    rows_with_date = [r for r in rows if r.get("registration_date")]
    skipped = len(rows) - len(rows_with_date)

    parser_fn = internal_code_parser_for(client_id, client["code_resolution_mode"])

    summary = _classify_rows(client_id=client_id, parsed=rows_with_date,
                             parser=parser_fn)

    print(f"client_id  = {client_id}")
    print(f"file       = {file_path.name}  ({len(blob):,} bytes)")
    print(f"parsed     = {len(rows)} rows  ({skipped} skipped, no date)")
    print(f"  NEW    = {summary['new']}")
    print(f"  NOOP   = {summary['noop']}")
    print(f"  DIFF   = {len(summary['diff'])}")
    print(f"  ORPHAN = {len(summary['orphan'])}")

    if args.dry_run:
        print("(dry-run: nothing applied)")
        return 0

    n = _apply_bcct_rows(
        client_id=client_id, rows=rows_with_date,
        upload_id=None, parser=parser_fn,
        orphans_to_delete=summary["orphan"] if args.confirm_orphans else [],
        user_id=OPS_ACTOR_ID,
    )
    print(f"applied    = {n} rows; "
          f"orphans deleted = {len(summary['orphan']) if args.confirm_orphans else 0}")
    print(f"audit log  = changed_by={OPS_ACTOR_ID!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
