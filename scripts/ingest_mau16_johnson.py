"""Ingest the preprocessed Mẫu 16 (TT 39/2018 customs BOM declaration)
flat .xlsx as `manual_flat` BOM artifacts for Johnson VN.

One artifact per product (TP). Carries:
- source_bom_kind='manual_flat'
- flatten_status='flattened' (Mẫu 16 is already flat by spec)
- flatten_strategy='manual_flat_as_provided'
- intent='asserted_technical' (filed-with-customs counts as asserted)
- context.regulatory='m16_2025', context.filed_with='customs',
  context.period_from / period_to / source_file
- human_label='Mẫu 16/2025'

Idempotent: re-runs upsert via create_artifact's existing constraint key
(client, product, actor, intent, parent_norm, normalized_hash,
flatten_strategy, bom_variant_id) — same input → same artifact_id.

Usage:
    uv run python scripts/ingest_mau16_johnson.py /tmp/m16_flat.xlsx \\
        [--client johnson-vn] [--period 2025] \\
        [--source-file 'BCDM_TT39 Dinh muc 2025 johnson.xls']
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from app.parsers.bom_adapters.manual_flat import ManualFlatAdapter
from app.stores.bom import create_artifact
from app.stores.uom_standards import resolve_canonical


DEFAULT_CLIENT = "johnson-vn"
DEFAULT_PERIOD = "2025"
DEFAULT_SOURCE_FILE = "BCDM_TT39 Dinh muc 2025 johnson.xls"
ACTOR = "customs_filing"  # mig 066 chk_actor: regulatory filing nộp hải quan
INTENT = "customs_declared"  # mig 066 chk_intent: BOM khai báo với hải quan, không phải asserted_technical


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("xlsx", help="Preprocessed flat xlsx (from preprocess_mau16_to_xlsx.py)")
    ap.add_argument("--client", default=DEFAULT_CLIENT)
    ap.add_argument("--period", default=DEFAULT_PERIOD,
                    help="Reporting year, e.g. '2025'")
    ap.add_argument("--source-file", default=DEFAULT_SOURCE_FILE,
                    help="Original .xls filename for provenance")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    xlsx_path = Path(args.xlsx)
    if not xlsx_path.exists():
        print(f"ERR: {xlsx_path} not found", file=sys.stderr)
        return 1

    blob = xlsx_path.read_bytes()
    adapter = ManualFlatAdapter()
    products = adapter.parse(blob)
    print(f"Parsed: {len(products)} products from {xlsx_path.name}")

    human_label = f"Mẫu 16/{args.period}"
    variant_id = f"m16_{args.period}"  # per-year variant: 'm16_2025', 'm16_2026'...
    context = {
        "regulatory": f"m16_{args.period}",
        "filed_with": "customs",
        "period_from": f"{args.period}-01-01",
        "period_to": f"{args.period}-12-31",
        "source_file": args.source_file,
    }

    # UoM pre-flight — surface unresolvable tokens up-front so we can decide
    # ack-or-block. Phase-2-pending tokens (e.g. `Chai/ Lọ/ Tuýp`) listed in
    # context.uom_drift_acked.
    uom_unresolved = Counter()
    total_rows = 0
    for prod, rows in products.items():
        for r in rows:
            total_rows += 1
            uom = r.get("uom") or ""
            if uom and resolve_canonical(uom) is None:
                uom_unresolved[uom] += 1
    if uom_unresolved:
        print(f"\nUoM tokens unresolved by hub.uom_aliases:")
        for tok, n in uom_unresolved.most_common():
            print(f"  {tok!r}: {n} rows")
        context["uom_drift_acked"] = sorted(uom_unresolved.keys())
        context["uom_drift_acked_reason"] = "phase2_pending"

    if args.dry_run:
        print(f"\nDry run — would create {len(products)} artifacts, {total_rows} rows total")
        return 0

    created = 0
    skipped = 0
    errors: list[tuple[str, str]] = []
    for product_code, rows in products.items():
        try:
            artifact_id = create_artifact(
                client_id=args.client,
                product_code=product_code,
                rows=rows,
                actor=ACTOR,
                intent=INTENT,
                parent_artifact_id=None,
                context=context,
                source_upload_id=None,
                source_bom_kind="manual_flat",
                flatten_status="flattened",
                flatten_strategy="manual_flat_as_provided",
                source_channel="agency_upload",
                bom_code=None,
                bom_variant_id=variant_id,
                lineage={"ingest": "scripts/ingest_mau16_johnson.py",
                         "source_file": args.source_file,
                         "period": args.period},
                flatten_method="none",
                flatten_method_version="0",
                display_label=None,
                human_label=human_label,
            )
            if artifact_id is None:
                skipped += 1
            else:
                created += 1
        except Exception as e:
            errors.append((product_code, str(e)))

    print(f"\nIngest summary:")
    print(f"  created/upserted: {created}")
    print(f"  skipped:          {skipped}")
    print(f"  errors:           {len(errors)}")
    for prod, err in errors[:5]:
        print(f"    {prod}: {err}")
    if len(errors) > 5:
        print(f"    (+{len(errors)-5} more)")
    print(f"\nTotal pair rows ingested: {total_rows}")
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
