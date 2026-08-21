"""Export one client's data to a tar.gz bundle.

  uv run python scripts/export_client.py --client growatt-vn -o /tmp/growatt.tar.gz

Bundle includes:
  - hub schema rows scoped to client_id (allow-listed tables only)
  - DATA_HUB_FILES_ROOT files under <module>/<client_id>/
  - manifest.json (client_id, schema_version, created_at, source)

Restore on another deployment with `scripts/onboard_client.py
--from-export <bundle.tar.gz>`. The two deployments must be on the
same migration head — import refuses on schema_version mismatch.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from hub.app.data_promotion import export_client


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--client", required=True, help="client_id to export")
    p.add_argument("-o", "--out", required=True, help="path for output bundle (tar.gz)")
    p.add_argument(
        "--source",
        default=None,
        help="label for the source deployment (defaults to $DATA_HUB_DEPLOYMENT_NAME or 'unknown')",
    )
    args = p.parse_args()

    manifest = export_client(
        client_id=args.client,
        out_path=Path(args.out),
        source=args.source,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    print(f"\nbundle written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
