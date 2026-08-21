"""Bulk-ingest technical_raw BOM XLSX files into hub.bom_artifacts + hub.bom_edges.

Wraps `parse_raw_edges_with_fallback` + `create_raw_artifact` over a directory
of supplier XLSX files. Bypasses the proposal flow so the auto-rule cannot
silently reject re-ingest (per critic round 3 finding 2).

Each file is one BOM. The filename stem becomes the root_code (caller can
override with --root-from-content if the file's first product code differs).

Usage:
    # Ingest Growatt supplemental batch with distinct variant
    uv run python scripts/ingest_technical_raw_batch.py \\
        --client growatt-vn \\
        --src ~/workspace/client/barry-CO-data/extracted/CO/bom-supplier-zips/by-company/GROWATT/from-bom-15-01/supplemental/ \\
        --variant-id agency_2026-01-supplemental \\
        --source-batch growatt-from-bom-15-01-supplemental

    # Dry-run: parse + report, no DB writes
    ... --dry-run

    # Resume: skip files until reaching <product_code>, then continue
    ... --resume-from PV01.0117200

    # On parser failure: 'continue' (default) logs and goes on; 'abort' raises
    ... --per-file-error abort

Output:
    /tmp/data_hub_pre_v3/ingest_logs/<source_batch>.json — structured log
    stdout — per-file progress + final summary

Idempotency: create_raw_artifact uses normalized_edges_hash to dedup. Re-running
the same batch on a populated DB is a no-op (returns the existing artifact_id).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from hub.app.database import connect
from hub.app.parsers.bom_edges import parse_raw_edges_with_fallback
from hub.app.parsers.bom_adapters import BomParseError
from hub.app.stores.bom import create_raw_artifact, normalized_edges_hash


def discover_xlsx(src: Path) -> list[Path]:
    if not src.exists():
        raise FileNotFoundError(f"Source directory not found: {src}")
    files = sorted(src.glob("*.XLSX")) + sorted(src.glob("*.xlsx"))
    if not files:
        raise FileNotFoundError(f"No XLSX files found in {src}")
    return files


def parse_one(path: Path, root_code: str) -> tuple[list[dict], str]:
    blob = path.read_bytes()
    result = parse_raw_edges_with_fallback(blob, root_code=root_code)
    if isinstance(result, tuple):
        return result
    return result, "unknown"


def ingest_one(
    *,
    client_id: str,
    product_code: str,
    edges: list[dict],
    adapter: str,
    source_batch: str,
    variant_id: str,
    src_filename: str,
    actor: str,
    dry_run: bool,
) -> dict:
    """Insert one bom_version + edges. Returns metadata about the result."""
    fresh_hash = normalized_edges_hash(edges)
    if dry_run:
        return {
            "artifact_id": None,
            "fresh_hash": fresh_hash,
            "edge_count": len(edges),
            "dry_run": True,
        }
    artifact_id = create_raw_artifact(
        client_id=client_id,
        product_code=product_code,
        edges=edges,
        actor=actor,
        intent="asserted_technical",
        parent_artifact_id=None,
        context={
            "channel": "migration",
            "profile": "technical_raw",
            "source_batch": source_batch,
            "parser_adapter": adapter,
            "source_filename": src_filename,
            "ingest_script": "ingest_technical_raw_batch.py",
        },
        source_upload_id=None,
        source_channel="migration",
        bom_variant_id=variant_id,
    )
    return {
        "artifact_id": artifact_id,
        "fresh_hash": fresh_hash,
        "edge_count": len(edges),
        "dry_run": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--client", required=True, help="client_id (e.g. growatt-vn)")
    ap.add_argument("--src", required=True, type=Path,
                    help="Source directory containing XLSX files")
    ap.add_argument("--variant-id", required=True,
                    help="bom_variant_id for this batch (e.g. agency_2026-01-supplemental)")
    ap.add_argument("--source-batch", required=True,
                    help="batch name saved into context.source_batch (audit label)")
    ap.add_argument("--actor", default="erp_pipeline",
                    help="actor for the bom_artifacts row (default: erp_pipeline)")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse + report only, no DB writes")
    ap.add_argument("--resume-from", default=None,
                    help="skip files alphabetically until reaching this product_code")
    ap.add_argument("--per-file-error", choices=("continue", "abort"),
                    default="continue",
                    help="behavior when one file fails (default: continue)")
    ap.add_argument("--out", default=None,
                    help="JSON log path (default: /tmp/data_hub_pre_v3/ingest_logs/<batch>.json)")
    args = ap.parse_args()

    src = args.src.expanduser().resolve()
    files = discover_xlsx(src)

    if args.resume_from:
        files = [f for f in files if f.stem >= args.resume_from]
        if not files:
            print(f"resume-from {args.resume_from!r} skipped all files; nothing to do.")
            return 0

    out_path = Path(
        args.out or f"/tmp/data_hub_pre_v3/ingest_logs/{args.source_batch}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"client_id          = {args.client}")
    print(f"src                = {src}")
    print(f"files discovered   = {len(files)}")
    print(f"variant_id         = {args.variant_id}")
    print(f"source_batch       = {args.source_batch}")
    print(f"actor              = {args.actor}")
    print(f"dry_run            = {args.dry_run}")
    print(f"per_file_error     = {args.per_file_error}")
    print(f"log                = {out_path}")
    print()

    started_at = datetime.now(timezone.utc).isoformat()
    records: list[dict] = []
    counters = {
        "ingested": 0,
        "dedup": 0,
        "parse_failed": 0,
        "ingest_failed": 0,
        "dry_run": 0,
    }

    for idx, path in enumerate(files, 1):
        product_code = path.stem
        rec: dict = {
            "idx": idx,
            "filename": path.name,
            "product_code": product_code,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        t0 = time.time()
        try:
            edges, adapter = parse_one(path, product_code)
            rec["adapter"] = adapter
            rec["edge_count"] = len(edges)
        except BomParseError as exc:
            rec["status"] = "parse_failed"
            rec["error"] = f"BomParseError: {exc}"
            rec["elapsed_ms"] = int((time.time() - t0) * 1000)
            counters["parse_failed"] += 1
            print(f"  [{idx:>3}/{len(files)}] {path.name:30s} PARSE_FAILED: {exc}")
            records.append(rec)
            if args.per_file_error == "abort":
                print("Aborting due to --per-file-error=abort")
                break
            continue
        except Exception as exc:
            rec["status"] = "parse_failed"
            rec["error"] = f"{type(exc).__name__}: {exc}"
            rec["traceback"] = traceback.format_exc()
            rec["elapsed_ms"] = int((time.time() - t0) * 1000)
            counters["parse_failed"] += 1
            print(f"  [{idx:>3}/{len(files)}] {path.name:30s} PARSE_FAILED: {exc}")
            records.append(rec)
            if args.per_file_error == "abort":
                print("Aborting due to --per-file-error=abort")
                break
            continue

        try:
            result = ingest_one(
                client_id=args.client,
                product_code=product_code,
                edges=edges,
                adapter=adapter,
                source_batch=args.source_batch,
                variant_id=args.variant_id,
                src_filename=path.name,
                actor=args.actor,
                dry_run=args.dry_run,
            )
        except Exception as exc:
            rec["status"] = "ingest_failed"
            rec["error"] = f"{type(exc).__name__}: {exc}"
            rec["traceback"] = traceback.format_exc()
            rec["elapsed_ms"] = int((time.time() - t0) * 1000)
            counters["ingest_failed"] += 1
            print(f"  [{idx:>3}/{len(files)}] {path.name:30s} INGEST_FAILED: {exc}")
            records.append(rec)
            if args.per_file_error == "abort":
                print("Aborting due to --per-file-error=abort")
                break
            continue

        rec["fresh_hash"] = result["fresh_hash"]
        rec["edge_count"] = result["edge_count"]
        rec["artifact_id"] = result.get("artifact_id")
        rec["elapsed_ms"] = int((time.time() - t0) * 1000)
        if result["dry_run"]:
            rec["status"] = "dry_run"
            counters["dry_run"] += 1
            label = "DRY_RUN"
        elif result["artifact_id"]:
            rec["status"] = "ingested"
            counters["ingested"] += 1
            label = f"ingested {result['artifact_id']}"
        else:
            rec["status"] = "dedup"
            counters["dedup"] += 1
            label = "DEDUP (existing artifact_id)"
        print(f"  [{idx:>3}/{len(files)}] {path.name:30s} "
              f"edges={rec['edge_count']:>5}  {rec['elapsed_ms']:>5}ms  {label}")
        records.append(rec)

    finished_at = datetime.now(timezone.utc).isoformat()
    log = {
        "client_id": args.client,
        "source_batch": args.source_batch,
        "variant_id": args.variant_id,
        "src": str(src),
        "actor": args.actor,
        "dry_run": args.dry_run,
        "started_at": started_at,
        "finished_at": finished_at,
        "counters": counters,
        "records": records,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(log, fh, ensure_ascii=False, indent=2)

    print()
    print(f"Files processed: {len(records)}")
    for k, v in counters.items():
        print(f"  {k}: {v}")
    print(f"\nLog: {out_path}")

    return 1 if (counters["parse_failed"] > 0 or counters["ingest_failed"] > 0) else 0


if __name__ == "__main__":
    sys.exit(main())
