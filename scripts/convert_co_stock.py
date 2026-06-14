"""Convert the agency `tru-lui-co-template.xlsm` into the standard CO stock
template xlsx that the import endpoint accepts.

Usage:
  uv run python scripts/convert_co_stock.py <input.xlsm> <output.xlsx>
  uv run python scripts/convert_co_stock.py --sheet NK2 input.xlsm out.xlsx
  uv run python scripts/convert_co_stock.py --sheet Save input.xlsm out.xlsx

This is the CLI front-end for `app.co_stock_workbook.parse_workbook`. The
web-based equivalent (upload .xlsm → snapshot in-app) lives in
`app.co_stock_workbook.import_workbook_snapshot` + the /co-stock/import-workbook
endpoint; both share the same parsing.

Behaviour:
- Default source sheet: `NK2` (the agency's reconciled per-lot snapshot).
  Alternative: `Save` (legacy event log) via --sheet Save.
- Rows with the same (declaration_no, line_no, customs_code) triplet are
  consolidated: used_qty summed, static fields take the first non-empty.
- Rows missing declaration_no/line_no/customs_code are logged to a sibling
  `.errors.log` file and dropped.
- NK2 rows with `Đã_xuất = 0` are skipped by default (the legacy Data-Hub
  overlay path already has the opening from BCCT); --include-zero-used keeps
  them. (The in-app snapshot path keeps them by default — the workbook is the
  standalone stock there.)

Output: standard CO stock template xlsx (see app/co_stock_template.py).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as `uv run python scripts/convert_co_stock.py` without
# editable-install of the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.co_stock_template import write_standard_co_stock  # noqa: E402
from app.co_stock_workbook import (  # noqa: E402
    AGENCY_NK2_COLUMN_MAP,
    AGENCY_SAVE_COLUMN_MAP,
    DEFAULT_SHEET,
    SHEET_PROFILES,
    parse_workbook,
)

__all__ = [
    "convert",
    "main",
    "AGENCY_NK2_COLUMN_MAP",
    "AGENCY_SAVE_COLUMN_MAP",
    "SHEET_PROFILES",
    "DEFAULT_SHEET",
]


def convert(
    input_path: Path,
    output_path: Path,
    sheet_name: str = DEFAULT_SHEET,
    *,
    include_zero_used: bool = False,
) -> dict:
    rows, parsed = parse_workbook(input_path, sheet=sheet_name, include_zero_used=include_zero_used)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(write_standard_co_stock(rows))
    summary = {
        "input": str(input_path),
        "output": str(output_path),
        "sheet": parsed["sheet"],
        "rows_in": parsed["rows_in"],
        "rows_unique": parsed["rows_unique"],
        "rows_dropped": parsed["rows_dropped"],
        "rows_skipped_zero_used": parsed["rows_skipped_zero_used"],
        "duplicates_merged": parsed["duplicates_merged"],
    }
    if parsed["dropped"]:
        log_path = output_path.with_suffix(output_path.suffix + ".errors.log")
        log_path.write_text("\n".join(parsed["dropped"]), encoding="utf-8")
        summary["errors_log"] = str(log_path)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Đường dẫn workbook gốc (e.g. tru-lui-co-template.xlsm)")
    parser.add_argument("output", type=Path, help="Đường dẫn xlsx output (standard CO stock template)")
    parser.add_argument("--sheet", default=DEFAULT_SHEET, choices=list(SHEET_PROFILES.keys()), help=f"Sheet nguồn (mặc định: {DEFAULT_SHEET!r})")
    parser.add_argument("--include-zero-used", action="store_true", help="Import cả lot có Đã_xuất=0 (mặc định NK2 bỏ qua)")
    args = parser.parse_args(argv)
    if not args.input.exists():
        raise SystemExit(f"Không tìm thấy file: {args.input}")
    summary = convert(args.input, args.output, args.sheet, include_zero_used=args.include_zero_used)
    print("Converted CO stock workbook:")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
