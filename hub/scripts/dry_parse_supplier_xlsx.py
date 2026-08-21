"""Dry-parse supplier XLSX files and compare hash with current DB.

For each file under the configured supplier roots, parse via
`parse_raw_edges_with_fallback` and compute the same `normalized_edges_hash`
that `create_raw_artifact` would. Compare against existing
`hub.bom_artifacts.normalized_hash` for the same `product_code` + a
matching `context->>'source_batch'`.

Output:
  /tmp/data_hub_pre_v3/dry_parse_report.json — per-file record
  stdout summary — counts by status

Status values:
  match           — current DB has a version for this (product, batch) and
                    the freshly parsed hash equals it. Safe to dedup or
                    re-ingest with no surprise.
  mismatch        — current DB has a version for this (product, batch) but
                    the hash differs. PARSER DRIFT — investigate before
                    re-ingest, otherwise BOM identity changes silently.
  no_db_match     — no DB version with this (product, batch) — file is a
                    new ingest, no comparison possible. Expected for the
                    14 Growatt root/ + 4 from-bom-20260423/ files that
                    were never trial-ingested.
  parse_failed    — parser raised. Will need manual fix before re-ingest.

Read-only. Connects to local DB via Unix socket.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from hub.app.database import connect
from hub.app.parsers.bom_edges import parse_raw_edges_with_fallback
from hub.app.parsers.bom_adapters import BomParseError
from hub.app.stores.bom import normalized_edges_hash


SUPPLIER_ROOT = Path(os.path.expanduser(
    "~/workspace/client/barry-CO-data/extracted/CO/bom-supplier-zips/by-company"
))


# (file_path → (client_id, source_batch, expected_root_code))
# source_batch matches what the trial ingest used (verified in current DB).
def discover_files() -> list[dict]:
    out: list[dict] = []

    growatt_root = SUPPLIER_ROOT / "GROWATT"
    if growatt_root.exists():
        for sub, batch in [
            ("from-bom-15-01/root", "growatt-from-bom-15-01-root"),
            ("from-bom-15-01/supplemental", "growatt-from-bom-15-01-supplemental"),
            ("from-bom-20260423/technical", "growatt-from-bom-20260423-technical"),
        ]:
            d = growatt_root / sub
            if not d.exists():
                continue
            for p in sorted(d.glob("*.XLSX")) + sorted(d.glob("*.xlsx")):
                root_code = p.stem
                out.append({
                    "client_id": "growatt-vn",
                    "batch": batch,
                    "subdir": sub,
                    "path": str(p),
                    "expected_root": root_code,
                })

    johnson_root = SUPPLIER_ROOT / "JOHNSON"
    if johnson_root.exists():
        for sub, batch in [
            ("from-bom-20260423/technical", "johnson-from-bom-20260423-technical"),
        ]:
            d = johnson_root / sub
            if not d.exists():
                continue
            for p in sorted(d.glob("*.XLSX")) + sorted(d.glob("*.xlsx")):
                root_code = p.stem
                out.append({
                    "client_id": "johnson-vn",
                    "batch": batch,
                    "subdir": sub,
                    "path": str(p),
                    "expected_root": root_code,
                })

    return out


def fetch_db_baseline(conn, client_id: str) -> dict[tuple[str, str], dict]:
    """Map (product_code, source_batch) → {artifact_id, normalized_hash, row_count}."""
    out: dict[tuple[str, str], dict] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            select product_code, context->>'source_batch' as batch,
                   artifact_id, normalized_hash, row_count
            from hub.bom_artifacts
            where client_id = %s
              and source_bom_kind = 'technical_raw'
              and tombstoned_at is null
              and context->>'source_batch' is not null
            """,
            (client_id,),
        )
        for product_code, batch, artifact_id, h, rc in cur.fetchall():
            out[(product_code, batch)] = {
                "artifact_id": artifact_id,
                "normalized_hash": h,
                "row_count": rc,
            }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument(
        "--out", default="/tmp/data_hub_pre_v3/dry_parse_report.json",
        help="JSON report path",
    )
    args = ap.parse_args()

    files = discover_files()
    print(f"Discovered {len(files)} XLSX files", file=sys.stderr)
    by_client: dict[str, list[dict]] = {}
    for f in files:
        by_client.setdefault(f["client_id"], []).append(f)
    for cid, lst in by_client.items():
        by_subdir: dict[str, int] = {}
        for f in lst:
            by_subdir[f["subdir"]] = by_subdir.get(f["subdir"], 0) + 1
        print(f"  {cid}: {len(lst)} files — " + ", ".join(
            f"{s}={n}" for s, n in sorted(by_subdir.items())
        ), file=sys.stderr)

    with connect() as conn:
        baselines = {
            cid: fetch_db_baseline(conn, cid) for cid in by_client.keys()
        }

    records: list[dict] = []
    counters = {"match": 0, "mismatch": 0, "no_db_match": 0, "parse_failed": 0}

    for f in files:
        rec = {
            "client_id": f["client_id"],
            "batch": f["batch"],
            "subdir": f["subdir"],
            "path": f["path"],
            "expected_root": f["expected_root"],
        }
        t0 = time.time()
        try:
            blob = Path(f["path"]).read_bytes()
            edges = parse_raw_edges_with_fallback(blob, root_code=f["expected_root"])
        except BomParseError as exc:
            rec["status"] = "parse_failed"
            rec["error"] = f"BomParseError: {exc}"
            rec["elapsed_ms"] = int((time.time() - t0) * 1000)
            counters["parse_failed"] += 1
            records.append(rec)
            continue
        except Exception as exc:
            rec["status"] = "parse_failed"
            rec["error"] = f"{type(exc).__name__}: {exc}"
            rec["traceback"] = traceback.format_exc()
            rec["elapsed_ms"] = int((time.time() - t0) * 1000)
            counters["parse_failed"] += 1
            records.append(rec)
            continue

        if isinstance(edges, tuple):
            edges_list, adapter_used = edges
        else:
            edges_list, adapter_used = edges, "unknown"

        rec["edge_count"] = len(edges_list)
        rec["adapter"] = adapter_used
        rec["fresh_hash"] = normalized_edges_hash(edges_list)
        rec["roots"] = sorted({e.get("root_code") for e in edges_list if e.get("root_code")})
        rec["elapsed_ms"] = int((time.time() - t0) * 1000)

        baseline_map = baselines.get(f["client_id"], {})
        # Try expected_root first, then any of the parsed roots.
        candidates = [f["expected_root"], *(rec["roots"] or [])]
        baseline = None
        matched_product = None
        for c in candidates:
            if (c, f["batch"]) in baseline_map:
                baseline = baseline_map[(c, f["batch"])]
                matched_product = c
                break

        if baseline is None:
            rec["status"] = "no_db_match"
            counters["no_db_match"] += 1
        else:
            rec["matched_product"] = matched_product
            rec["db_hash"] = baseline["normalized_hash"]
            rec["db_row_count"] = baseline["row_count"]
            rec["db_artifact_id"] = baseline["artifact_id"]
            if baseline["normalized_hash"] == rec["fresh_hash"]:
                rec["status"] = "match"
                counters["match"] += 1
            else:
                rec["status"] = "mismatch"
                counters["mismatch"] += 1
        records.append(rec)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"counters": counters, "records": records}, fh,
                  ensure_ascii=False, indent=2)

    print()
    print(f"Total files: {len(records)}")
    for k, v in counters.items():
        print(f"  {k}: {v}")
    print(f"\nReport: {args.out}")

    if counters["mismatch"] > 0 or counters["parse_failed"] > 0:
        print("\nFiles needing investigation:")
        for r in records:
            if r["status"] in ("mismatch", "parse_failed"):
                err = r.get("error") or f"db={r.get('db_hash','?')[:12]} fresh={r.get('fresh_hash','?')[:12]}"
                print(f"  [{r['status']}] {r['subdir']}/{Path(r['path']).name} — {err}")

    # Exit code: 0 if no parse failure (mismatch is informational not blocking).
    return 1 if counters["parse_failed"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
