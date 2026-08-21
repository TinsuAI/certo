"""Onboard a client into Data Hub from a bundle or Excel folder.

  # Promote from another deployment (dev → demo):
  uv run python scripts/onboard_client.py --from-export /tmp/growatt.tar.gz

  # Bulk import from a customer's Excel folder (NOT YET IMPLEMENTED):
  uv run python scripts/onboard_client.py --client newco --from-excel ./newco-files

Replace mode (default and only mode for v1): the target's existing
rows for the bundle's client_id are wiped via cascade from
hub.clients before insert. Other clients on the target deployment
are untouched.

Confirmation: `--commit` is required to actually write. Without it,
the bundle is read and validated but no DB changes are made.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from hub.app.data_promotion import (
    SchemaVersionMismatch,
    UnsupportedBundleFormat,
    import_client_bundle,
)


def _peek_manifest(bundle_path: Path) -> dict:
    with tarfile.open(bundle_path, "r:gz") as tar:
        member = tar.getmember("manifest.json")
        f = tar.extractfile(member)
        return json.loads(f.read().decode("utf-8"))


def _from_export(args) -> int:
    bundle = Path(args.from_export)
    if not bundle.exists():
        print(f"ERROR: bundle not found: {bundle}", file=sys.stderr)
        return 2

    manifest = _peek_manifest(bundle)
    print("Bundle manifest:")
    print(json.dumps(manifest, indent=2, sort_keys=True))

    if not args.commit:
        print("\nDry run (no --commit): would replace client_id "
              f"{manifest.get('client_id')!r} on the target deployment.")
        print("Re-run with --commit to apply.")
        return 0

    try:
        result = import_client_bundle(bundle_path=bundle)
    except SchemaVersionMismatch as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 3
    except UnsupportedBundleFormat as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 3
    print("\nImported:")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _from_excel(args) -> int:
    print(
        "ERROR: --from-excel is not yet implemented.\n"
        "       The Excel onboarding path requires reusing the parser layer\n"
        "       (app/parsers/{bcct,materials,bom}.py) and is the next slice\n"
        "       of feature 2026-05-04-data-promotion. For now, onboard via\n"
        "       the web UI on dev, then promote to demo with --from-export.",
        file=sys.stderr,
    )
    return 4


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-export", help="path to a bundle.tar.gz produced by export_client.py")
    src.add_argument("--from-excel", help="path to a directory of customer Excel files (NYI)")
    p.add_argument("--client", help="client_id (required for --from-excel; inferred from manifest for --from-export)")
    p.add_argument("--commit", action="store_true", help="apply changes (default is dry-run)")
    args = p.parse_args()

    if args.from_export:
        return _from_export(args)
    return _from_excel(args)


if __name__ == "__main__":
    raise SystemExit(main())
