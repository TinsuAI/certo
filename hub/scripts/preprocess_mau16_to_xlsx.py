"""Preprocess a Mẫu 16/ĐMTT/GSQL .xls (TT 39/2018 customs declaration) into a
clean .xlsx that the existing `manual_flat` BOM adapter can consume.

Input layout (per TT 39/2018 Phụ lục):
- rows 0..5: header metadata (đơn vị, MST, kỳ báo cáo)
- rows 6..10: column headers (3 rows of merged labels + 1 row of (1)(2)...)
- rows 11..N-3: data rows. Cột 0..3 (Stt, Mã SP, Tên SP, ĐVT SP)
  forward-fill across continuation rows of the same product.
- last 3 rows: empty + 2 signature lines (NGƯỜI LẬP / NGƯỜI ĐẠI DIỆN ...)

Output: 1-sheet .xlsx with columns [`Mã SP`, `Mã NVL`, `ĐVT`, `Định mức`]
(aliased by app/parsers/bom_adapters/_common.COMMON_ALIASES).

Usage:
    uv run python scripts/preprocess_mau16_to_xlsx.py INPUT.xls OUTPUT.xlsx
"""
from __future__ import annotations

import sys
from pathlib import Path

import xlrd
from openpyxl import Workbook


HEADER_ROWS_BELOW_DATA_START = 11  # data starts at row index 11
SIGNATURE_TAIL_HINTS = ("NGƯỜI LẬP", "Ký, ghi rõ họ tên")


def transform_rows(rows: list[list]) -> tuple[list[tuple[str, str, str, float]], set[str]]:
    """Pure transform: takes raw 9-col rows starting at data row (no header
    rows), forward-fills product, skips footer/empty, yields output 4-tuples
    (product_code, material_code, uom, qty). Unit-testable in isolation.

    Caller is responsible for slicing off the header rows before calling.
    """
    out: list[tuple[str, str, str, float]] = []
    current_product: str | None = None
    products_seen: set[str] = set()

    for r_offset, row in enumerate(rows):
        padded = (list(row) + [""] * 9)[:9]
        stt, tp_code, _tp_name, _tp_uom, nvl_code, _nvl_name, nvl_uom, qty, _note = padded

        # Stop at signature footer
        stt_str = str(stt).strip()
        if any(hint in stt_str for hint in SIGNATURE_TAIL_HINTS):
            break

        tp_code_str = str(tp_code).strip()
        if tp_code_str:
            current_product = tp_code_str
            products_seen.add(current_product)

        nvl_code_str = str(nvl_code).strip()
        if not nvl_code_str:
            continue
        if not current_product:
            print(
                f"  WARN offset {r_offset}: NVL {nvl_code_str} without "
                "preceding TP — skipped",
                file=sys.stderr,
            )
            continue

        try:
            qty_num = float(qty) if qty not in ("", None) else 0.0
        except (TypeError, ValueError):
            print(
                f"  WARN offset {r_offset}: qty={qty!r} not numeric — emitting 0",
                file=sys.stderr,
            )
            qty_num = 0.0

        out.append(
            (current_product, nvl_code_str, str(nvl_uom).strip(), qty_num)
        )

    return out, products_seen


def preprocess(in_path: Path, out_path: Path) -> tuple[int, int]:
    """Read the .xls, emit clean .xlsx. Returns (n_products, n_rows)."""
    wb_in = xlrd.open_workbook(filename=str(in_path))
    sh = wb_in.sheet_by_index(0)

    raw_rows = [sh.row_values(r) for r in range(HEADER_ROWS_BELOW_DATA_START, sh.nrows)]
    rows_out, products_seen = transform_rows(raw_rows)

    wb_out = Workbook()
    ws_out = wb_out.active
    ws_out.title = "Mau16"
    ws_out.append(["Mã SP", "Mã NVL", "ĐVT", "Định mức"])
    for row in rows_out:
        ws_out.append(list(row))
    wb_out.save(out_path)
    return len(products_seen), len(rows_out)


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "Usage: preprocess_mau16_to_xlsx.py INPUT.xls OUTPUT.xlsx",
            file=sys.stderr,
        )
        return 2
    in_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    if not in_path.exists():
        print(f"Input not found: {in_path}", file=sys.stderr)
        return 1
    n_products, n_rows = preprocess(in_path, out_path)
    print(
        f"OK: {n_products} products, {n_rows} pair rows → {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
