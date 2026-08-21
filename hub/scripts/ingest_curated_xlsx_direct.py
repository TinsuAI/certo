"""Direct-ingest curated XLSX files (catalog, BQD, BCCT, manual_flat BOM).

Bypasses the unified-mapping-flow UI (which requires staff confirm steps)
by calling parsers + store-level inserters directly. Same call pattern as
app/seed.py:_seed_growatt but reads real XLSX from /tmp/dh_real_data.

Use after Phase A cutover and Phase B raw-batch ingest. Does NOT cover
technical_raw (use ingest_technical_raw_batch.py for that).

Usage:
    DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data uv run python \\
        scripts/ingest_curated_xlsx_direct.py
"""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from hub.app.database import connect
from hub.app.parsers.bcct import parse_bcct_workbook
from hub.app.parsers.bom import parse_bom_workbook
from hub.app.parsers.code_mappings import parse_code_mappings_workbook
from hub.app.parsers.materials import parse_materials_workbook
from hub.app.routes.bcct import _insert_bcct
from hub.app.routes.bqd import _insert_mappings
from hub.app.routes.catalog import _insert_materials
from hub.app.stores.bom import create_artifact


REAL_DATA = Path(os.environ.get("DATA_HUB_REAL_DATA_DIR", "/tmp/dh_real_data"))


def _stub_upload(client_id: str, module: str, filename: str) -> str:
    """Insert a stub file_uploads row so child rows can FK to it."""
    upload_id = f"direct-{module}-{client_id}-{secrets.token_hex(4)}"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.file_uploads (upload_id, client_id, module,
                  original_filename, stored_path, content_sha256, size_bytes,
                  parse_status, row_count)
                values (%s, %s, %s, %s, 'direct-ingest', 'direct', 0, 'done', 0)
                on conflict (upload_id) do nothing
                """,
                (upload_id, client_id, module, filename),
            )
    return upload_id


def ingest_materials(client_id: str, path: Path) -> int:
    if not path.exists():
        print(f"  SKIP missing: {path}")
        return 0
    rows, _ = parse_materials_workbook(path.read_bytes())
    n = _insert_materials(client_id=client_id, rows=rows)
    print(f"  catalog ← {path.name}: {n} rows")
    return n


def ingest_bqd(client_id: str, path: Path) -> int:
    if not path.exists():
        print(f"  SKIP missing: {path}")
        return 0
    rows, _ = parse_code_mappings_workbook(path.read_bytes())
    n = _insert_mappings(client_id=client_id, rows=rows)
    print(f"  bqd ← {path.name}: {n} rows")
    return n


def ingest_bcct(client_id: str, path: Path, code_resolution_mode: str) -> int:
    if not path.exists():
        print(f"  SKIP missing: {path}")
        return 0
    parsed = parse_bcct_workbook(path.read_bytes())
    if not parsed:
        print(f"  bcct ← {path.name}: parser produced 0 rows, skipped")
        return 0
    upload_id = _stub_upload(client_id, "bcct", path.name)
    n = _insert_bcct(client_id=client_id, rows=parsed,
                    upload_id=upload_id,
                    client={"client_id": client_id,
                            "code_resolution_mode": code_resolution_mode})
    print(f"  bcct ← {path.name}: {n} rows (upload_id={upload_id})")
    return n


def ingest_manual_flat_bom(client_id: str, path: Path) -> int:
    if not path.exists():
        print(f"  SKIP missing: {path}")
        return 0
    parsed = parse_bom_workbook(path.read_bytes(), profile="manual_flat")
    upload_id = _stub_upload(client_id, "bom", path.name)
    versions_created = 0
    for product_code, rows in parsed.items():
        if not rows:
            continue
        try:
            create_artifact(
                client_id=client_id, product_code=product_code, rows=rows,
                actor="agency_staff", intent="asserted_technical",
                parent_artifact_id=None,
                context={"channel": "agency_upload", "profile": "manual_flat",
                         "source_filename": path.name},
                source_upload_id=upload_id,
                source_channel="agency_upload",
            )
            versions_created += 1
        except Exception as exc:
            print(f"    ERROR creating BOM for {product_code}: "
                  f"{type(exc).__name__}: {exc}")
    print(f"  bom (manual_flat) ← {path.name}: {versions_created} versions")
    return versions_created


def main() -> int:
    print(f"DATA_HUB_REAL_DATA_DIR = {REAL_DATA}")
    print()

    print("=== growatt-vn ===")
    g = REAL_DATA / "growatt"
    ingest_materials("growatt-vn", g / "catalog_nvl.xlsx")
    ingest_materials("growatt-vn", g / "catalog_sp.xlsx")
    ingest_bqd("growatt-vn", g / "bqd_nvl.xlsx")
    ingest_bqd("growatt-vn", g / "bqd_tp.xlsx")
    ingest_bcct("growatt-vn", g / "bcct_nk_2026_t3-t4.xls",
                "batch_aggregate_resolution")
    ingest_bcct("growatt-vn", g / "bcct_xk_2026_t3-t4.xls",
                "batch_aggregate_resolution")
    ingest_manual_flat_bom("growatt-vn", g / "bom_tp.xlsx")
    ingest_manual_flat_bom("growatt-vn", g / "bom_btp.xlsx")

    print()
    print("=== dke-vietnam-d0e3 ===")
    d = REAL_DATA / "dke"
    ingest_bqd("dke-vietnam-d0e3", d / "bqd.xls")

    print()
    print("Direct-ingest done. Run verify_btp_rollup.py + bootstrap_btp_roster "
          "next. Catalog rows derive on ingest (#52) — no bootstrap step.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
