"""Generate Excel files for manual testing of the 4 stages shipped 2026-05-04.

Run:
    uv run python data/manual_test/_generate.py

Output files in this directory; README.md walks through how to drive each.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).parent


# ───────────────────────────────────────────────────────────────────────
# 01 — Stage A+B: full CO-essential BCCT (12 typed columns + year derived)
# ───────────────────────────────────────────────────────────────────────

CO_HEADERS = (
    "Số tờ khai", "Dòng", "Mã loại hình", "Ngày đăng ký",
    "Mã NPL/SP", "Tên hàng", "Tổng số lượng", "ĐVT", "Trị giá", "Nguyên tệ",
    "Xuất xứ", "Số hóa đơn",
    # 12 CO-essential
    "Tên doanh nghiệp", "Mã doanh nghiệp",
    "Tên đối tác",
    "Điều kiện giá hóa đơn",
    "Trọng lượng", "Mã ĐVT trọng lượng",
    "Số lượng kiện", "Mã ĐVT kiện",
    "Ngày hóa đơn", "Ngày khởi hành vận chuyển",
    "Mã địa điểm đích", "Tên địa điểm đích cho vận chuyển bảo thuế",
    "Mã hiệu PTVC",
    "Tỷ giá thanh toán",
)


def stage_ab_full_co():
    wb = Workbook()
    ws = wb.active
    ws.title = "BCCT"
    ws.append(CO_HEADERS)
    # 3 export rows for distinct decl_nos
    rows = [
        ("MAN_AB_001", 1, "E42", "2026-03-15", "PV-INV-3000",
         "PV-INV-3000#&Solar inverter Growatt MIN 5000TL-X",
         50.0, "PCS", 12500.0, "USD", "VN", "INV-2026-001",
         "CÔNG TY TNHH GROWATT NEW ENERGY VIETNAM", "0123456789",
         "ACME ENERGY GMBH",
         "FOB",
         245.5, "KGM",
         8, "CT",
         "2026-03-10", "2026-03-16",
         "DEHAM", "Cảng Hamburg",
         "1",
         25400.0),
        ("MAN_AB_002", 1, "E42", "2026-03-20", "PV-INV-5000",
         "PV-INV-5000#&Solar inverter Growatt MIN 7500TL-X",
         30.0, "PCS", 18000.0, "USD", "VN", "INV-2026-002",
         "CÔNG TY TNHH GROWATT NEW ENERGY VIETNAM", "0123456789",
         "SUNRISE TRADING CO LTD",
         "CIF",
         180.0, "KGM",
         5, "CT",
         "2026-03-18", "2026-03-21",
         "JPTYO", "Cảng Tokyo",
         "1",
         25400.0),
        ("MAN_AB_003", 1, "E11", "2026-03-25", "PE-001",
         "PE-001#&Polyethylene resin",
         500.0, "KGM", 1200.0, "USD", "CN", "PINV-2026-003",
         "CÔNG TY TNHH GROWATT NEW ENERGY VIETNAM", "0123456789",
         "SHANGHAI POLYMERS CO LTD",
         "CFR",
         500.0, "KGM",
         20, "CT",
         "2026-03-22", "2026-03-24",
         "VNHPH", "Cảng Hải Phòng",
         "1",
         25400.0),
    ]
    for r in rows:
        ws.append(r)
    wb.save(OUT / "01_stage_AB_full_co_bcct.xlsx")


# ───────────────────────────────────────────────────────────────────────
# 02 — Stage D: Chinese headers (rigid parser must FAIL → LLM fallback)
# ───────────────────────────────────────────────────────────────────────

def stage_d_chinese_headers():
    wb = Workbook()
    ws = wb.active
    ws.title = "报关详细"
    # Chinese headers — BCCT aliases don't include these → rigid parser
    # rejects → LLM fallback path triggers (when LLM is configured).
    ws.append((
        "报关单号",       # decl_no
        "项次",            # line_no
        "申报类型",        # decl_type
        "登记日期",        # registration_date
        "海关编码",        # customs_code
        "货物名称",        # goods_name
        "数量",            # quantity
        "单位",            # unit
        "总价值",          # total_value
        "货币",            # currency
    ))
    ws.append(("MAN_D_001", 1, "E42", "2026-04-01", "ZH-INV-3000",
               "光伏逆变器 5kW Growatt", 50.0, "件", 12500.0, "USD"))
    ws.append(("MAN_D_002", 1, "E42", "2026-04-05", "ZH-INV-5000",
               "光伏逆变器 7.5kW Growatt", 30.0, "件", 18000.0, "USD"))
    wb.save(OUT / "02_stage_D_chinese_headers.xlsx")


# ───────────────────────────────────────────────────────────────────────
# 03a — Stage C1 baseline: 3 rows, normal upload
# 03b — Stage C1 changed: same 2 TKs (1 DIFF, 1 NOOP) + 1 NEW; row 3
#       missing → ORPHAN candidate
# ───────────────────────────────────────────────────────────────────────

C1_HEADERS = (
    "Số tờ khai", "Dòng", "Mã loại hình", "Ngày đăng ký",
    "Mã NPL/SP", "Tên hàng", "Tổng số lượng", "ĐVT", "Trị giá", "Nguyên tệ",
)


def stage_c1_baseline():
    wb = Workbook()
    ws = wb.active
    ws.title = "BCCT"
    ws.append(C1_HEADERS)
    ws.append(("MAN_C1_A", 1, "E11", "2026-02-01", "MAT-A",
               "MAT-A#&Material A", 100.0, "KGM", 250.0, "USD"))
    ws.append(("MAN_C1_B", 1, "E11", "2026-02-02", "MAT-B",
               "MAT-B#&Material B", 200.0, "KGM", 500.0, "USD"))
    ws.append(("MAN_C1_C", 1, "E11", "2026-02-03", "MAT-C",
               "MAT-C#&Material C", 300.0, "KGM", 750.0, "USD"))
    wb.save(OUT / "03a_stage_C1_baseline.xlsx")


def stage_c1_changed():
    wb = Workbook()
    ws = wb.active
    ws.title = "BCCT"
    ws.append(C1_HEADERS)
    # MAN_C1_A — quantity changed 100 → 88   (DIFF)
    ws.append(("MAN_C1_A", 1, "E11", "2026-02-01", "MAT-A",
               "MAT-A#&Material A", 88.0, "KGM", 250.0, "USD"))
    # MAN_C1_B — identical to baseline       (NOOP)
    ws.append(("MAN_C1_B", 1, "E11", "2026-02-02", "MAT-B",
               "MAT-B#&Material B", 200.0, "KGM", 500.0, "USD"))
    # MAN_C1_C is missing                    (ORPHAN candidate)
    # MAN_C1_D is brand new                  (NEW)
    ws.append(("MAN_C1_D", 1, "E11", "2026-02-04", "MAT-D",
               "MAT-D#&Material D", 400.0, "KGM", 1000.0, "USD"))
    wb.save(OUT / "03b_stage_C1_changed.xlsx")


# ───────────────────────────────────────────────────────────────────────
# 04 — Cleanup script: SQL to wipe manual-test rows so you can re-run
# ───────────────────────────────────────────────────────────────────────

def write_cleanup_sql():
    (OUT / "_cleanup.sql").write_text(
        "-- Run before re-running the manual-test scenarios:\n"
        "--   psql -d data_hub -f data/manual_test/_cleanup.sql\n\n"
        "delete from hub.bcct_row_history\n"
        " where transaction_key like 'MAN\\_%' escape '\\';\n\n"
        "delete from hub.bcct_rows\n"
        " where transaction_key like 'MAN\\_%' escape '\\';\n\n"
        "delete from hub.upload_pending\n"
        " where parsed_rows::text like '%MAN\\_%' escape '\\';\n\n"
        "delete from hub.parser_mappings\n"
        " where mapping::text like '%报关%';\n\n"
        "delete from hub.file_uploads\n"
        " where original_filename like '0%_stage_%.xlsx';\n",
        encoding="utf-8",
    )


def main():
    stage_ab_full_co()
    stage_d_chinese_headers()
    stage_c1_baseline()
    stage_c1_changed()
    write_cleanup_sql()
    print(f"generated 5 files in {OUT}")
    for f in sorted(OUT.iterdir()):
        if f.is_file():
            print(f"  {f.name}  ({f.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
