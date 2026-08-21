"""Backfill bom_edges.payload->>'description' for existing Johnson BOM
TP raw artifacts.

A.7 enhanced the SAP-indented parser to capture the "Object description"
column. Existing 106 Johnson TP raw artifacts ingested before A.7 have
NULL description in payload. This script re-parses each source XLSX and
in-place UPDATEs the matching bom_edges rows (matched by (artifact_id,
source_row_no, child_code) — TP raw edges carry source_row_no).

BTP slice raw artifacts (parent_artifact_id is None, source_row_no NULL)
are not backfilled directly; they are derivable from TP raw edges, so
candidate refresh (which UNIONs across all alive artifacts) still picks
up description via the TP raw side.

Idempotent: re-running over an already-backfilled edge re-sets the same
description.

Usage:
  uv run python scripts/backfill_johnson_bom_description.py [--commit]

Without --commit, runs in dry-run mode (no DB writes; print stats).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from app.database import connect
from app.parsers.bom_edges import parse_sap_indented_raw_edges


CLIENT_ID = "johnson-vn"
SOURCE_DIR = Path(
    "data/source_inventory/johnson-vn/2026-05-07-updated/Johnson/"
    "TECHNICAL BOM - JOHNSON"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true",
                    help="actually write to DB (default: dry-run)")
    args = ap.parse_args()

    if not SOURCE_DIR.exists():
        print(f"FAIL source dir not found: {SOURCE_DIR}", file=sys.stderr)
        return 2

    files = sorted(SOURCE_DIR.glob("*.XLSX"))
    print(f"Found {len(files)} XLSX files in {SOURCE_DIR}")

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select product_code, artifact_id from hub.bom_artifacts "
            "where client_id=%s and tombstoned_at is null "
            "  and source_bom_kind='technical_raw' "
            "  and parent_artifact_id is null",
            (CLIENT_ID,),
        )
        all_raw = cur.fetchall()

    # Some rows are BTP slices that happen to have parent_artifact_id is
    # null (the 2026-05-11 dedup fix nulled this out intentionally). Real
    # TP raws are the subset whose product_code matches a XLSX file stem.
    file_stems = {f.stem.upper() for f in files}
    file_by_stem = {f.stem.upper(): f for f in files}
    tp_raws_by_stem: dict[str, str] = {}
    for product_code, artifact_id in all_raw:
        if product_code.upper() in file_stems:
            # Pick first match per file stem (should be 1:1).
            tp_raws_by_stem.setdefault(product_code.upper(), artifact_id)

    print(f"Matched {len(tp_raws_by_stem)} TP raw artifacts to XLSX files")
    missing_xlsx = file_stems - set(tp_raws_by_stem.keys())
    if missing_xlsx:
        print(f"WARN {len(missing_xlsx)} XLSX have no matching artifact: "
              f"{sorted(missing_xlsx)[:5]}...")
    missing_artifact = set(file_stems) - {s for s in tp_raws_by_stem.keys()}
    # ^ same set; computed above. Cosmetic.

    total_edges_updated = 0
    total_edges_with_desc = 0
    total_edges_no_desc = 0
    files_failed: list[tuple[str, str]] = []

    for stem, artifact_id in sorted(tp_raws_by_stem.items()):
        path = file_by_stem[stem]
        try:
            blob = path.read_bytes()
            edges = parse_sap_indented_raw_edges(blob, root_code=stem)
        except Exception as exc:  # noqa: BLE001
            files_failed.append((stem, str(exc)))
            continue

        # Build a lookup: source_row_no → description (only edges that
        # have description per the new parser).
        desc_by_row: dict[int, str] = {}
        for e in edges:
            if "description" in (e.get("payload") or {}):
                desc_by_row[e["source_row_no"]] = e["payload"]["description"]

        if not desc_by_row:
            # No description column or all empty — skip without
            # touching the DB (so payload doesn't get a NULL field).
            total_edges_no_desc += len(edges)
            continue

        # In-place UPDATE matching by (artifact_id, source_row_no).
        if args.commit:
            with connect() as conn, conn.cursor() as cur:
                for src_row_no, desc in desc_by_row.items():
                    cur.execute(
                        "update hub.bom_edges "
                        "set payload = coalesce(payload,'{}'::jsonb) "
                        "  || jsonb_build_object('description', %s::text) "
                        "where artifact_id=%s and source_row_no=%s",
                        (desc, artifact_id, src_row_no),
                    )
                    total_edges_updated += cur.rowcount
        else:
            total_edges_updated += len(desc_by_row)
        total_edges_with_desc += len(desc_by_row)

    mode = "COMMITTED" if args.commit else "DRY-RUN"
    print(f"\n{mode} stats:")
    print(f"  Files processed: {len(tp_raws_by_stem)}")
    print(f"  Edges with description in source: {total_edges_with_desc}")
    print(f"  Edges updated: {total_edges_updated}")
    if files_failed:
        print(f"  Files failed to parse: {len(files_failed)}")
        for stem, err in files_failed[:5]:
            print(f"    {stem}: {err}")

    if not args.commit:
        print("\nDry-run only. Pass --commit to write changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
