"""End-to-end round-trip smoke test for data_promotion on real data.

  uv run python scripts/smoke_roundtrip_client.py [client_id]

DELETEs the client (cascade), imports the just-exported bundle, verifies
row counts + spot aggregates match. Default client is growatt-vn.

This script catches schema/trigger interactions that unit tests miss
(file_uploads SET-NULL FK, bcct_row_history trigger accumulation, etc).
Run before tagging a release that touches data_promotion. BACK UP THE DB
FIRST — the DELETE+INSERT is destructive.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from hub.app.data_promotion import export_client, import_client_bundle
from hub.app.database import connect


CID = sys.argv[1] if len(sys.argv) > 1 else "growatt-vn"
# Audit tables are excluded — they're per-deployment and the import
# explicitly purges them (see AUDIT_TABLES_TO_PURGE_ON_IMPORT).
TABLES = (
    "clients", "client_config", "file_uploads", "parser_mappings",
    "code_mappings", "materials", "client_uom_overrides",
    "bcct_rows", "bom_artifacts", "bom_change_requests",
    "bom_flatten_decisions",
)


def counts() -> dict[str, int]:
    out = {}
    with connect() as conn, conn.cursor() as cur:
        for t in TABLES:
            cur.execute(
                f"select count(*) from hub.{t} where client_id = %s", (CID,)
            )
            out[t] = cur.fetchone()[0]
        # bom_artifact_rows: indirect via bom_artifacts
        cur.execute(
            """
            select count(*) from hub.bom_artifact_rows r
            join hub.bom_artifacts v using (artifact_id)
            where v.client_id = %s
            """,
            (CID,),
        )
        out["bom_artifact_rows"] = cur.fetchone()[0]
    return out


def spot_check() -> dict:
    out = {}
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select max(registration_date), min(registration_date), "
            "sum(quantity)::numeric(20,6) "
            "from hub.bcct_rows where client_id = %s",
            (CID,),
        )
        out["bcct_aggregates"] = cur.fetchone()
        cur.execute(
            "select max(artifact_id) from hub.bom_artifacts where client_id = %s",
            (CID,),
        )
        out["max_bom_version"] = cur.fetchone()[0]
    return out


def main():
    print(f"== Round-trip {CID} ==")
    before_counts = counts()
    before_spot = spot_check()
    print(f"Before: {before_counts}")
    print(f"Spot:   {before_spot}")

    bundle = "/tmp/roundtrip_bundle.tar.gz"
    print(f"\nExporting → {bundle}")
    manifest = export_client(client_id=CID, out_path=bundle)
    print(f"Manifest: {manifest}")

    print(f"\nImporting (will DELETE + re-INSERT {CID}) ...")
    result = import_client_bundle(bundle_path=bundle)
    print(f"Result:   {result}")

    after_counts = counts()
    after_spot = spot_check()
    print(f"\nAfter: {after_counts}")
    print(f"Spot:  {after_spot}")

    diff = {t: (before_counts[t], after_counts[t])
            for t in before_counts
            if before_counts[t] != after_counts[t]}
    if diff:
        print(f"\n!! COUNT MISMATCH: {diff}")
        return 1
    if before_spot != after_spot:
        print(f"\n!! SPOT MISMATCH: before={before_spot} after={after_spot}")
        return 1
    print("\nALL EQUAL ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
