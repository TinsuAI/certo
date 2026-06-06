"""One-off data correction: trừ-lùi adjustment rows whose unit disagrees with
the lot's BCCT unit by a mass factor (kg vs metric-tons).

Context: the agency trừ-lùi workbook is a stock snapshot we sync into the
system. A few rows were entered in KILO-GRAMMES while BCCT declares the lot in
METRIC-TONS; since `unit_value` is per BCCT unit, the override over-stated
remaining (and its value) by 1000×. Per the architecture decision (the workbook
must not drive system logic), there is NO unit conversion in the fold path —
this script corrects the stored adjustment DATA to the canonical (BCCT) unit
instead, then refolds the affected lots.

Idempotent: once a row is converted its unit becomes the BCCT unit, so the
mismatch predicate no longer selects it. Dry-run by default; pass --apply to
write.

Usage:
    uv run python scripts/fix_trului_unit.py <client_id> [--apply]
"""
from __future__ import annotations

import sys
from decimal import Decimal

from app.database import connect
from app import co_stock_materializer

# Mass units → kilograms. Only same-dimension mass pairs are reconciled; any
# other unit pair is left for a human (not guessed).
_MASS_TO_KG = {
    "KG": Decimal("1"), "KGM": Decimal("1"), "KGS": Decimal("1"),
    "KILOGRAM": Decimal("1"), "KILOGRAMS": Decimal("1"),
    "KILOGRAMME": Decimal("1"), "KILOGRAMMES": Decimal("1"),
    "KILO-GRAM": Decimal("1"), "KILO-GRAMMES": Decimal("1"),
    "TAN": Decimal("1000"), "TẤN": Decimal("1000"), "TON": Decimal("1000"),
    "TONS": Decimal("1000"), "TONNE": Decimal("1000"), "TONNES": Decimal("1000"),
    "TNE": Decimal("1000"), "METRIC-TON": Decimal("1000"),
    "METRIC-TONS": Decimal("1000"), "METRIC TON": Decimal("1000"),
    "METRIC TONS": Decimal("1000"),
}


def _norm(u) -> str:
    return str(u or "").strip().upper()


def _dec(v):
    return Decimal(str(v)) if v is not None else None


def main(client_id: str, apply: bool) -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select a.declaration_no, a.line_no, a.customs_code, a.unit,
                   a.opening_qty_override, a.used_qty, a.unit_price, a.taxable_unit_price,
                   r.payload->>'unit'
            from co_stock_adjustments a
            join co_stock_rows r
              on r.client_id = a.client_id
             and r.payload->>'import_declaration_no' = a.declaration_no
             and r.payload->>'line_no' = a.line_no
             and r.payload->>'customs_item_code' = a.customs_code
            where a.client_id = %s and a.status = 'active'
              and coalesce(a.unit, '') <> coalesce(r.payload->>'unit', '')
            """,
            (client_id,),
        )
        rows = cur.fetchall()

        fixes = []
        for decl, line, code, adj_unit, override, used, uprice, tprice, bcct_unit in rows:
            au, bu = _norm(adj_unit), _norm(bcct_unit)
            if au not in _MASS_TO_KG or bu not in _MASS_TO_KG:
                print(f"  SKIP {code} decl={decl}: unit pair {adj_unit!r}->{bcct_unit!r} not a known mass pair")
                continue
            qty_factor = _MASS_TO_KG[au] / _MASS_TO_KG[bu]   # adj-unit qty → bcct-unit qty
            if qty_factor == 1:
                continue
            price_factor = _MASS_TO_KG[bu] / _MASS_TO_KG[au]  # per-adj-unit price → per-bcct-unit price
            fixes.append({
                "decl": decl, "line": line, "code": code,
                "from_unit": adj_unit, "to_unit": bcct_unit,
                "override": (_dec(override) * qty_factor) if override is not None else None,
                "used": (_dec(used) * qty_factor) if used is not None else None,
                "unit_price": (_dec(uprice) * price_factor) if uprice is not None else None,
                "taxable_unit_price": (_dec(tprice) * price_factor) if tprice is not None else None,
            })
            print(f"  FIX  {code} decl={decl} line={line}: {adj_unit}->{bcct_unit} "
                  f"override {override}->{fixes[-1]['override']} used {used}->{fixes[-1]['used']}")

        if not fixes:
            print("Nothing to fix.")
            return 0
        if not apply:
            print(f"\nDRY-RUN: {len(fixes)} row(s) would change. Re-run with --apply to write.")
            return 0

        for f in fixes:
            cur.execute(
                """update co_stock_adjustments
                   set opening_qty_override = %s, used_qty = %s,
                       unit_price = %s, taxable_unit_price = %s,
                       unit = %s, updated_at = now()
                   where client_id = %s and declaration_no = %s
                     and line_no = %s and customs_code = %s and status = 'active'""",
                (f["override"], f["used"], f["unit_price"], f["taxable_unit_price"],
                 f["to_unit"], client_id, f["decl"], f["line"], f["code"]),
            )
        conn.commit()
        print(f"\nApplied {len(fixes)} row(s).")

    refolded = co_stock_materializer.refold_all_adjustments(client_id)
    co_stock_materializer.invalidate_co_stock_rows_cache(client_id)
    print(f"Refolded {refolded} lot(s). New summary: {co_stock_materializer.co_stock_summary(client_id)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], "--apply" in sys.argv[1:]))
