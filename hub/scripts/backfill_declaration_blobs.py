"""Backfill missing customs-declaration blobs into the storage backend.

Context (2026-06-04): johnson-vn landed in prod as metadata-only — every
`hub.customs_declaration_files` row exists with a `backend_key` + sha256,
but the .xls bytes were never written to the FileBackend. The download
ZIP therefore returns only the manifest. This restores the blobs at their
recorded `backend_key`, matching source files by content sha256 so the
bytes are provably the registered ones.

Idempotent + non-destructive: only `put`s keys that are currently
unresolvable; never deletes or overwrites a present blob. Dry-run by
default — pass `--apply` to write.

Run inside the prod app container (needs DB + backend + the source files
reachable on a path):

    python scripts/backfill_declaration_blobs.py \
        --client johnson-vn --source-dir /tmp/johnson_src           # dry-run
    python scripts/backfill_declaration_blobs.py \
        --client johnson-vn --source-dir /tmp/johnson_src --apply
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from app.database import connect
from app.storage import get_backend


def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _index_source(source_dir: Path) -> dict[str, Path]:
    """sha256 -> source path for every .xls/.xlsx under source_dir."""
    by_sha: dict[str, Path] = {}
    exts = {".xls", ".xlsx"}
    for p in source_dir.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        sha = _sha256(p.read_bytes())
        by_sha.setdefault(sha, p)
    return by_sha


def _blob_present(backend, key: str) -> bool:
    try:
        backend.get(key)
        return True
    except FileNotFoundError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", default="johnson-vn")
    ap.add_argument("--source-dir", required=True, type=Path)
    ap.add_argument("--apply", action="store_true",
                    help="write blobs; default is dry-run")
    args = ap.parse_args()

    if not args.source_dir.is_dir():
        print(f"source-dir not found: {args.source_dir}", file=sys.stderr)
        return 2

    print(f"indexing source files under {args.source_dir} ...")
    by_sha = _index_source(args.source_dir)
    print(f"  {len(by_sha)} distinct-content source files")

    backend = get_backend()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """select id, declaration_no, direction, backend_key,
                      original_filename, sha256
                 from hub.customs_declaration_files
                where client_id = %s
                order by id""",
            (args.client,),
        )
        rows = cur.fetchall()

    present = planned = unmatched = 0
    unmatched_samples: list[str] = []
    plan: list[tuple] = []  # (key, source_path, sha)
    for _id, decl, direction, key, name, sha in rows:
        if _blob_present(backend, key):
            present += 1
            continue
        src = by_sha.get(sha)
        if src is None:
            unmatched += 1
            if len(unmatched_samples) < 10:
                unmatched_samples.append(f"{decl}/{direction} {name} sha={sha[:12]}")
            continue
        planned += 1
        plan.append((key, src, sha))

    total = len(rows)
    print(f"\nclient={args.client} total_rows={total}")
    print(f"  already present : {present}")
    print(f"  matched (plan)  : {planned}")
    print(f"  unmatched       : {unmatched}")
    if unmatched_samples:
        print("  unmatched samples:")
        for s in unmatched_samples:
            print(f"    - {s}")

    if not args.apply:
        print("\nDRY-RUN — no writes. Re-run with --apply to backfill.")
        return 0

    print(f"\napplying {planned} put(s) ...")
    done = failed = 0
    for key, src, sha in plan:
        blob = src.read_bytes()
        if _sha256(blob) != sha:  # paranoia: re-verify the exact bytes
            failed += 1
            print(f"  SHA MISMATCH, skipped: {key}")
            continue
        backend.put(blob, key=key)
        if _blob_present(backend, key):
            done += 1
        else:
            failed += 1
            print(f"  put did not land: {key}")
    print(f"\ndone={done} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
