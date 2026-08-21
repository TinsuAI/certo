"""Per-customs-code UoM drift report.

Finds material codes in BCCT for a given (client, year range) whose
`unit` value is not stable — i.e. at least 2 distinct `unit` values
appear across rows. Writes an XLSX with two sheets:

- Tóm tắt: one row per drifting code with concatenated unit list,
  total observations, total declarations, span, catalog info.
- Chi tiết: one row per (code, unit) breakdown showing observation
  count, declaration count, date span, presence in each year.

Run:
    uv run python scripts/uom_drift_report.py \\
        --client johnson-vn \\
        --year-from 2025 --year-to 2026 \\
        --out /tmp/johnson_uom_drift_2025_2026.xlsx
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.database import connect


SUMMARY_HEADERS = [
    "STT", "Mã (customs_code)", "Tên (catalog)", "Loại", "Mã HS",
    "Số ĐVT phân biệt", "Tổng dòng BCCT", "Tổng tờ khai",
    "Danh sách ĐVT (theo tần suất)",
    "Lần đầu", "Lần cuối", "ĐVT chính 2025", "ĐVT chính 2026",
    "Bất nhất 2025", "Bất nhất 2026",
    "Bất nhất giữa 2 năm", "Đổi ĐVT chính",
]

DETAIL_HEADERS = [
    "STT", "Mã (customs_code)", "ĐVT (unit)", "Số dòng BCCT", "Số tờ khai",
    "Lần đầu", "Lần cuối", "Có trong 2025?", "Có trong 2026?",
    "Tỷ trọng trong mã (%)",
]


NVL_IMPORT_DECLARATION_TYPES = (
    "E11", "E15", "E21", "E23", "E31", "E33",
)


def fetch_drift(client_id: str, year_from: int, year_to: int, *,
                nvl_imports_only: bool = False) -> dict:
    """Returns {customs_code: {unit_stats, catalog_info}}.

    `nvl_imports_only`: when True, restrict to NVL import declarations
    (direction='import' and declaration_type IN the NVL set per
    mig 046 / mig 019)."""
    date_from = date(year_from, 1, 1)
    date_to = date(year_to + 1, 1, 1)

    extra_filter = ""
    if nvl_imports_only:
        extra_filter = (
            " and direction = 'import'"
            " and declaration_type = any(%(nvl_types)s)"
        )

    sql = f"""
        with raw as (
            select customs_code, unit, registration_date, declaration_no,
                   extract(year from registration_date)::int as yr
              from hub.bcct_rows
             where client_id = %(cid)s
               and registration_date >= %(from)s
               and registration_date <  %(to)s
               and customs_code is not null
               and unit is not null and unit <> ''
               {extra_filter}
        ),
        drift_codes as (
            select customs_code
              from raw
             group by customs_code
            having count(distinct unit) >= 2
        ),
        per_code_unit as (
            select r.customs_code, r.unit,
                   count(*)                  as n_rows,
                   count(distinct r.declaration_no) as n_decls,
                   min(r.registration_date)  as first_date,
                   max(r.registration_date)  as last_date,
                   bool_or(r.yr = 2025)      as in_2025,
                   bool_or(r.yr = 2026)      as in_2026
              from raw r
              join drift_codes d using (customs_code)
             group by r.customs_code, r.unit
        ),
        mode_units as (
            select customs_code, yr,
                   first_value(unit) over (
                       partition by customs_code, yr
                       order by count(*) desc, unit
                   ) as mode_unit
              from raw r
              join drift_codes d using (customs_code)
             group by customs_code, yr, unit
        )
        select
          pcu.customs_code, pcu.unit, pcu.n_rows, pcu.n_decls,
          pcu.first_date, pcu.last_date, pcu.in_2025, pcu.in_2026,
          (select distinct mode_unit from mode_units
            where mode_units.customs_code = pcu.customs_code
              and mode_units.yr = 2025 limit 1) as mode_2025,
          (select distinct mode_unit from mode_units
            where mode_units.customs_code = pcu.customs_code
              and mode_units.yr = 2026 limit 1) as mode_2026
        from per_code_unit pcu
        order by pcu.customs_code, pcu.n_rows desc, pcu.unit
    """
    params: dict = {"cid": client_id, "from": date_from, "to": date_to}
    if nvl_imports_only:
        params["nvl_types"] = list(NVL_IMPORT_DECLARATION_TYPES)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    by_code: dict[str, dict] = {}
    for (code, unit, n_rows, n_decls, first_date, last_date,
         in_2025, in_2026, mode_2025, mode_2026) in rows:
        bucket = by_code.setdefault(code, {
            "units": [], "mode_2025": mode_2025, "mode_2026": mode_2026,
        })
        bucket["units"].append({
            "unit": unit, "n_rows": n_rows, "n_decls": n_decls,
            "first_date": first_date, "last_date": last_date,
            "in_2025": in_2025, "in_2026": in_2026,
        })

    # Catalog lookup for name / category / HS.
    codes = list(by_code.keys())
    if codes:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """select material_code, name, category, hs_code
                   from hub.materials
                  where client_id = %s and material_code = any(%s)""",
                (client_id, codes),
            )
            for code, name, category, hs in cur.fetchall():
                by_code[code]["catalog"] = {
                    "name": name, "category": category, "hs_code": hs,
                }
    return by_code


def write_workbook(by_code: dict, *, client_id: str,
                   year_from: int, year_to: int, out_path: Path) -> None:
    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "Tóm tắt"
    ws_det = wb.create_sheet("Chi tiết")

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F4E78")
    drift_fill = PatternFill("solid", fgColor="FFF2CC")

    for ws, headers in ((ws_sum, SUMMARY_HEADERS), (ws_det, DETAIL_HEADERS)):
        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center",
                                       wrap_text=True)
        ws.freeze_panes = "A2"

    # Sort codes by total observations desc for top-down readability.
    code_totals = sorted(
        by_code.items(),
        key=lambda kv: sum(u["n_rows"] for u in kv[1]["units"]),
        reverse=True,
    )

    sum_row = 2
    det_row = 2
    for stt, (code, info) in enumerate(code_totals, start=1):
        units = info["units"]
        catalog = info.get("catalog", {})
        total_rows = sum(u["n_rows"] for u in units)
        total_decls = sum(u["n_decls"] for u in units)
        first_date = min(u["first_date"] for u in units)
        last_date = max(u["last_date"] for u in units)
        unit_list = ", ".join(
            f'{u["unit"]} ({u["n_rows"]})' for u in units
        )
        mode_2025 = info.get("mode_2025") or ""
        mode_2026 = info.get("mode_2026") or ""
        units_2025 = {u["unit"] for u in units if u["in_2025"]}
        units_2026 = {u["unit"] for u in units if u["in_2026"]}
        intra_2025 = len(units_2025) >= 2
        intra_2026 = len(units_2026) >= 2
        # "Bất nhất giữa 2 năm" — broader semantic: tập ĐVT đã từng dùng
        # khác nhau giữa 2 năm. Catches both mode-drift AND the case
        # where both years share the same mode but one year carries
        # an additional unit the other doesn't.
        cross_year_set_drift = (
            bool(units_2025) and bool(units_2026)
            and units_2025 != units_2026
        )
        # "Đổi ĐVT chính" — narrower / stronger signal: mode of 2025 ≠
        # mode of 2026, i.e. the agency switched its primary
        # declaration unit between years.
        mode_drift = (
            bool(mode_2025) and bool(mode_2026)
            and mode_2025 != mode_2026
        )

        ws_sum.cell(row=sum_row, column=1, value=stt)
        ws_sum.cell(row=sum_row, column=2, value=code)
        ws_sum.cell(row=sum_row, column=3, value=catalog.get("name") or "")
        ws_sum.cell(row=sum_row, column=4, value=catalog.get("category") or "")
        ws_sum.cell(row=sum_row, column=5, value=catalog.get("hs_code") or "")
        ws_sum.cell(row=sum_row, column=6, value=len(units))
        ws_sum.cell(row=sum_row, column=7, value=total_rows)
        ws_sum.cell(row=sum_row, column=8, value=total_decls)
        ws_sum.cell(row=sum_row, column=9, value=unit_list)
        ws_sum.cell(row=sum_row, column=10, value=first_date)
        ws_sum.cell(row=sum_row, column=11, value=last_date)
        ws_sum.cell(row=sum_row, column=12, value=mode_2025)
        ws_sum.cell(row=sum_row, column=13, value=mode_2026)
        ws_sum.cell(row=sum_row, column=14, value="X" if intra_2025 else "")
        ws_sum.cell(row=sum_row, column=15, value="X" if intra_2026 else "")
        ws_sum.cell(row=sum_row, column=16,
                    value="X" if cross_year_set_drift else "")
        ws_sum.cell(row=sum_row, column=17,
                    value="X" if mode_drift else "")
        if mode_drift:
            for col in range(1, len(SUMMARY_HEADERS) + 1):
                ws_sum.cell(row=sum_row, column=col).fill = drift_fill
        sum_row += 1

        for u in units:
            ratio = (u["n_rows"] / total_rows * 100.0) if total_rows else 0
            ws_det.cell(row=det_row, column=1, value=stt)
            ws_det.cell(row=det_row, column=2, value=code)
            ws_det.cell(row=det_row, column=3, value=u["unit"])
            ws_det.cell(row=det_row, column=4, value=u["n_rows"])
            ws_det.cell(row=det_row, column=5, value=u["n_decls"])
            ws_det.cell(row=det_row, column=6, value=u["first_date"])
            ws_det.cell(row=det_row, column=7, value=u["last_date"])
            ws_det.cell(row=det_row, column=8, value="X" if u["in_2025"] else "")
            ws_det.cell(row=det_row, column=9, value="X" if u["in_2026"] else "")
            ws_det.cell(row=det_row, column=10, value=round(ratio, 1))
            det_row += 1

    # Column widths — rough manual sizing.
    widths_sum = [5, 22, 50, 8, 12, 8, 10, 10, 50, 12, 12, 14, 14,
                   12, 12, 16, 14]
    widths_det = [5, 22, 12, 10, 10, 12, 12, 10, 10, 10]
    for idx, w in enumerate(widths_sum, start=1):
        ws_sum.column_dimensions[get_column_letter(idx)].width = w
    for idx, w in enumerate(widths_det, start=1):
        ws_det.column_dimensions[get_column_letter(idx)].width = w

    # Date formatting on the date columns.
    for row in ws_sum.iter_rows(min_row=2, min_col=10, max_col=11):
        for cell in row:
            cell.number_format = "yyyy-mm-dd"
    for row in ws_det.iter_rows(min_row=2, min_col=6, max_col=7):
        for cell in row:
            cell.number_format = "yyyy-mm-dd"

    # Header / context row above the summary header isn't standard
    # in this codebase's reports; embed metadata in the sheet title
    # area instead by adding a comment-style row at the bottom.
    info_row = sum_row + 1
    ws_sum.cell(row=info_row, column=1,
                value=f"Client: {client_id} · Năm: {year_from}–{year_to} · "
                      f"Số mã có drift ĐVT: {len(by_code)}").font = Font(italic=True)

    wb.save(out_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", default="johnson-vn")
    parser.add_argument("--year-from", type=int, default=2025)
    parser.add_argument("--year-to", type=int, default=2026)
    parser.add_argument("--nvl-imports-only", action="store_true",
                        help="Restrict to direction=import + NVL declaration "
                             "types (E11/E15/E21/E23/E31/E33).")
    parser.add_argument("--out", type=Path,
                        default=Path("/tmp/uom_drift.xlsx"))
    args = parser.parse_args()

    scope = "NVL imports only" if args.nvl_imports_only else "all rows"
    print(f"Querying BCCT for {args.client} {args.year_from}–{args.year_to} ({scope})…")
    by_code = fetch_drift(
        args.client, args.year_from, args.year_to,
        nvl_imports_only=args.nvl_imports_only,
    )
    print(f"  {len(by_code)} codes with ≥2 distinct units")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_workbook(
        by_code, client_id=args.client,
        year_from=args.year_from, year_to=args.year_to,
        out_path=args.out,
    )
    print(f"Saved → {args.out.resolve()}")


if __name__ == "__main__":
    main()
