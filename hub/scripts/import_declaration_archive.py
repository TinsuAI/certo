"""Bulk-import per-declaration TKN/TKX form files into Data Hub.

Walks a directory of `<prefix>_<decl_no>.xls` files, parses + cross-
validates each via `app.parsers.declaration_files`, stores blob via
FileBackend, inserts metadata row in `hub.customs_declaration_files`.

Usage:
    uv run python scripts/import_declaration_archive.py \\
        --client johnson-vn --direction import \\
        --dir data/source_inventory/johnson-vn/2026-05-07-updated/Johnson/TKN

Idempotent on (client, decl_no, direction, sha256). Re-running skips
existing files.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from app.parsers.declaration_files import (
    DeclarationFileError,
    is_supported_filename,
    parse_declaration_file,
)
from app.storage import save_upload, sha256_bytes
from app.stores.customs_declaration_files import insert_declaration_file


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--client", required=True, help="client_id (e.g. johnson-vn)")
    p.add_argument(
        "--direction", required=True, choices=["import", "export"],
        help="'import' for TKN, 'export' for TKX",
    )
    p.add_argument("--dir", required=True, help="directory containing files")
    p.add_argument(
        "--limit", type=int, default=None,
        help="cap files processed (smoke runs)",
    )
    p.add_argument(
        "--no-validate-content", action="store_true",
        help="skip XLS content cross-validation (fast mode)",
    )
    args = p.parse_args()

    src = Path(args.dir)
    if not src.is_dir():
        print(f"ERROR: not a directory: {src}", file=sys.stderr)
        return 2

    files = sorted([
        f for f in src.iterdir()
        if f.is_file() and is_supported_filename(f.name)
    ])
    skipped_unsupported = sum(
        1 for f in src.iterdir()
        if f.is_file() and not is_supported_filename(f.name)
    )
    if args.limit is not None:
        files = files[: args.limit]

    stats = {
        "total": len(files),
        "inserted": 0,
        "deduped": 0,
        "parse_errors": 0,
        "store_errors": 0,
        "skipped_unsupported": skipped_unsupported,
    }
    parse_errors: list[tuple[str, str]] = []
    store_errors: list[tuple[str, str]] = []

    print(f"Importing {len(files)} files from {src}")
    print(f"  client={args.client}, direction={args.direction}, "
          f"validate_content={not args.no_validate_content}")
    print()

    t0 = time.monotonic()
    for i, f in enumerate(files, 1):
        try:
            content = f.read_bytes()
            info = parse_declaration_file(
                f.name, content,
                validate_content=not args.no_validate_content,
            )
        except DeclarationFileError as exc:
            stats["parse_errors"] += 1
            parse_errors.append((f.name, str(exc)))
            continue

        sha = sha256_bytes(content)
        try:
            stored = save_upload(
                content,
                filename=f.name, module="customs_declarations",
                client_id=args.client,
            )
            fid, created = insert_declaration_file(
                client_id=args.client,
                declaration_no=info.declaration_no,
                direction=args.direction,
                file_kind=info.file_kind,
                backend_key=stored.path,
                original_filename=f.name,
                sha256=sha,
                size_bytes=stored.size_bytes,
                uploaded_by="import_script",
            )
            if created:
                stats["inserted"] += 1
            else:
                stats["deduped"] += 1
        except Exception as exc:
            stats["store_errors"] += 1
            store_errors.append((f.name, f"{type(exc).__name__}: {exc}"))

        if i % 200 == 0:
            elapsed = time.monotonic() - t0
            rate = i / elapsed if elapsed > 0 else 0
            print(f"  [{i}/{len(files)}] {rate:.1f}/s "
                  f"inserted={stats['inserted']} dup={stats['deduped']} "
                  f"err={stats['parse_errors'] + stats['store_errors']}")

    elapsed = time.monotonic() - t0
    print()
    print(f"Done in {elapsed:.1f}s ({len(files) / elapsed:.1f}/s):")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    if parse_errors:
        print(f"\nFirst 10 parse errors:")
        for name, err in parse_errors[:10]:
            print(f"  {name}: {err}")
    if store_errors:
        print(f"\nFirst 10 store errors:")
        for name, err in store_errors[:10]:
            print(f"  {name}: {err}")

    return 0 if stats["parse_errors"] + stats["store_errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
