#!/usr/bin/env python
"""Snapshot LVC% on N real locked cases — before-fix vs after-fix-with-VND-mode.

Approach:
  1. Pull the latest persisted case state from co.co_case_states.
  2. Compute LVC% using current `material_value` (native units, post-existing
     allocation pipeline) — this is the "before" state staff sees today.
  3. Simulate currency_mode="vnd" by reading the `material_value_vnd` aggregate
     populated by phase 2. Where lines lack VND (FX missing), reuse native.
  4. Print side-by-side LVC%, delta, and per-product currency mix so we can
     spot which cases would visibly drift on a real currency_mode toggle.

Run on local dev DB; does NOT mutate anything.
"""
from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Ensure app is importable when run from project root.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Pick up .env so database_url() resolves.
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

from app.database import connect, database_url


def fetch_locked_cases(limit: int) -> list[tuple[str, dict]]:
    url = database_url()
    if not url:
        raise SystemExit("BARRY_DATABASE_URL not set")
    rows: list[tuple[str, dict]] = []
    with connect(url) as conn, conn.cursor() as cur:
        cur.execute("set search_path=co")
        cur.execute(
            """
            select client_id, c
            from co_case_states, jsonb_array_elements(payload->'cases') c
            where exists (
              select 1 from jsonb_each(c->'origin_sheet_states') s
              where s.value->>'status' = 'locked'
            )
            limit %s
            """,
            (limit,),
        )
        for client_id, case_json in cur.fetchall():
            rows.append((client_id, case_json))
    return rows


def _dec(value) -> Decimal:
    text = str(value or "").strip()
    if not text:
        return Decimal(0)
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return Decimal(0)


def lvc_percent(fob: Decimal, vnm: Decimal) -> str:
    if fob <= 0:
        return "n/a"
    pct = (fob - vnm) / fob * Decimal(100)
    return f"{pct:.2f}%"


def summarize_case(case: dict) -> dict:
    products = case.get("products", []) or []
    rows = []
    for product in products:
        fob_native = _dec(product.get("fob"))
        fob_vnd = _dec(product.get("fob_vnd") or product.get("fob"))
        vnm_native = Decimal(0)
        vnm_vnd = Decimal(0)
        currency_mix: set[str] = set()
        fx_sources: set[str] = set()
        for material in product.get("materials", []) or []:
            if str(material.get("origin_status") or "non_origin") != "non_origin":
                continue
            vnm_native += _dec(material.get("material_value"))
            vnd = material.get("material_value_vnd")
            vnm_vnd += _dec(vnd) if vnd not in (None, "") else _dec(material.get("material_value"))
            cur = str(material.get("currency") or "").strip().upper()
            if cur:
                currency_mix.add(cur)
            src = str(material.get("exchange_rate_source") or "").strip()
            if src:
                fx_sources.add(src)
        rows.append({
            "product_code": product.get("code", "?"),
            "currency_mix": sorted(currency_mix),
            "fx_sources": sorted(fx_sources),
            "fob_native": fob_native,
            "fob_vnd": fob_vnd,
            "vnm_native": vnm_native,
            "vnm_vnd": vnm_vnd,
            "lvc_native": lvc_percent(fob_native, vnm_native),
            "lvc_vnd": lvc_percent(fob_vnd, vnm_vnd),
        })
    return {
        "case_id": case.get("case_id", "?"),
        "case_code": case.get("case_code", "?"),
        "products": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    cases = fetch_locked_cases(args.limit)
    if not cases:
        print("No locked cases found.")
        return 0

    drift_count = 0
    for client_id, case in cases:
        summary = summarize_case(case)
        print(f"\n=== {client_id} · {summary['case_code']} ({summary['case_id']}) ===")
        for product in summary["products"]:
            print(f"  TP {product['product_code']}")
            print(f"    currencies in materials: {product['currency_mix'] or ['(none)']}")
            print(f"    FX sources:              {product['fx_sources'] or ['(none)']}")
            print(f"    FOB native: {product['fob_native']:>20,.2f}   FOB vnd: {product['fob_vnd']:>20,.2f}")
            print(f"    VNM native: {product['vnm_native']:>20,.2f}   VNM vnd: {product['vnm_vnd']:>20,.2f}")
            print(f"    LVC native: {product['lvc_native']:>10s}     LVC vnd: {product['lvc_vnd']:>10s}")
            if product["lvc_native"] != product["lvc_vnd"]:
                drift_count += 1
                print(f"    >>> DRIFT")

    print(f"\nTotal cases: {len(cases)}  ·  products with LVC drift: {drift_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
