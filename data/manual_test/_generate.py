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
# Phase 1+2+3 fixtures (2026-05-02): universal preview + LLM fallback for
# BOM/BQD/Catalog. Test the rigid happy path + LLM-fallback path + reject
# button + idempotent re-upload across all 4 modules.
# ───────────────────────────────────────────────────────────────────────

# 04 — BQD rigid happy path. Vietnamese standard headers; ~5 mappings;
# tests preview UI + counter rendering + 1-to-N detection.

def bqd_basic_rigid():
    wb = Workbook()
    ws = wb.active
    ws.title = "BQD"
    ws.append(("Mã nội bộ", "Mã hải quan", "Loại", "Ghi chú"))
    ws.append(("MAN_BQD_001", "MAN-HQ-A1", "nvl", "Test mapping 1"))
    ws.append(("MAN_BQD_001", "MAN-HQ-A2", "nvl", "1-to-N case"))
    ws.append(("MAN_BQD_002", "MAN-HQ-B1", "tp", ""))
    ws.append(("MAN_BQD_003", "MAN-HQ-C1", "nvl", "another"))
    ws.append(("MAN_BQD_004", "MAN-HQ-D1", "ccdc", "tool"))
    wb.save(OUT / "04_bqd_basic_rigid.xlsx")


# 05 — BQD LLM fallback. English headers don't match any rigid alias
# exactly (post Phase 1: pass-2 substring is GONE, so 'Internal' won't
# match 'internal code' alias).

def bqd_llm_english():
    wb = Workbook()
    ws = wb.active
    ws.title = "Mapping"
    ws.append(("Internal", "Customs", "Type", "Note"))
    ws.append(("MAN_BQD_LLM_001", "MAN-HQ-LLM-A", "nvl", "english headers"))
    ws.append(("MAN_BQD_LLM_002", "MAN-HQ-LLM-B", "tp", "force LLM path"))
    ws.append(("MAN_BQD_LLM_003", "MAN-HQ-LLM-C", "nvl", ""))
    wb.save(OUT / "05_bqd_llm_english.xlsx")


# 06 — Catalog rigid happy path. Standard Vietnamese DS NVL shape.

def catalog_basic_rigid():
    wb = Workbook()
    ws = wb.active
    ws.title = "DS NVL"
    ws.append(("Mã hải quan", "Mã nội bộ", "Tên", "Loại", "ĐVT", "HS", "Trạng thái"))
    ws.append(("MAN-MAT-A", "MAN_CAT_A", "Test material A", "nvl", "KGM", "39031900", "active"))
    ws.append(("MAN-MAT-B", "MAN_CAT_B", "Test material B", "nvl", "KGM", "39031900", "active"))
    ws.append(("MAN-MAT-C", "MAN_CAT_C", "Test material C", "nvl", "PCS", "85044090", "active"))
    wb.save(OUT / "06_catalog_basic_rigid.xlsx")


# 07 — Catalog LLM fallback. English headers force LLM.

def catalog_llm_english():
    wb = Workbook()
    ws = wb.active
    ws.title = "Materials"
    ws.append(("HQ Code", "Internal Code", "Description", "Cat", "Unit"))
    ws.append(("MAN-MAT-LLM-A", "MAN_CAT_LLM_A", "Material A LLM", "nvl", "KGM"))
    ws.append(("MAN-MAT-LLM-B", "MAN_CAT_LLM_B", "Material B LLM", "tp", "PCS"))
    wb.save(OUT / "07_catalog_llm_english.xlsx")


# 08 — BOM manual_flat rigid. Vietnamese product/material/qty/uom.

def bom_basic_rigid():
    wb = Workbook()
    ws = wb.active
    ws.title = "BOM"
    ws.append(("Mã SP", "Mã NVL", "Định mức", "ĐVT"))
    # Product MAN_PROD_A has 3 components
    ws.append(("MAN_PROD_A", "MAN_NVL_001", 2.5, "KGM"))
    ws.append(("MAN_PROD_A", "MAN_NVL_002", 1.0, "PCS"))
    ws.append(("MAN_PROD_A", "MAN_NVL_003", 0.5, "KGM"))
    # Product MAN_PROD_B has 2 components
    ws.append(("MAN_PROD_B", "MAN_NVL_001", 1.5, "KGM"))
    ws.append(("MAN_PROD_B", "MAN_NVL_004", 4.0, "PCS"))
    wb.save(OUT / "08_bom_manual_flat_rigid.xlsx")


# 09 — BOM LLM fallback. Synthetic non-aliased English headers force LLM.
# manual_flat profile is the only profile that supports mapping_override
# today (the other two infer structure from sheet layout).

def bom_llm_english():
    wb = Workbook()
    ws = wb.active
    ws.title = "Recipe"
    ws.append(("Finished Goods", "Component", "Standard Usage", "Unit"))
    ws.append(("MAN_BOM_LLM_P1", "MAN_BOM_LLM_C1", 3.0, "KGM"))
    ws.append(("MAN_BOM_LLM_P1", "MAN_BOM_LLM_C2", 2.0, "PCS"))
    ws.append(("MAN_BOM_LLM_P2", "MAN_BOM_LLM_C1", 1.5, "KGM"))
    wb.save(OUT / "09_bom_llm_english.xlsx")


# 10 — BCCT all-NEW (Phase 2 closes the all-NEW bypass gap).
# Distinct from 03a/03b (those test the existing diff/orphan flow).
# 3 fresh transaction keys → all NEW → preview shows
# "Xem trước BCCT trước khi lưu" (not "Xác nhận thay đổi").

def bcct_all_new_phase2():
    wb = Workbook()
    ws = wb.active
    ws.title = "BCCT"
    ws.append(C1_HEADERS)
    ws.append(("MAN_P2_X", 1, "E11", "2026-05-01", "MAT-X",
               "MAT-X#&Material X for phase2 test", 100.0, "KGM", 250.0, "USD"))
    ws.append(("MAN_P2_Y", 1, "E42", "2026-05-02", "MAT-Y",
               "MAT-Y#&Material Y for phase2 test", 200.0, "KGM", 500.0, "USD"))
    ws.append(("MAN_P2_Z", 1, "E11", "2026-05-03", "MAT-Z",
               "MAT-Z#&Material Z for phase2 test", 300.0, "KGM", 750.0, "USD"))
    wb.save(OUT / "10_bcct_all_new_phase2.xlsx")


# 11 — File that fails BOTH rigid AND LLM (no recognizable column shape
# at all). Tests the user-facing 400 error.

def malformed_random():
    wb = Workbook()
    ws = wb.active
    ws.title = "Random"
    # Random non-data-shaped headers; 0 rows. LLM might still try but
    # typically returns empty or junk → second-stage parse fails.
    ws.append(("Foo", "Bar", "Baz"))
    ws.append(("aaa", "bbb", "ccc"))
    wb.save(OUT / "11_malformed_random.xlsx")


# ───────────────────────────────────────────────────────────────────────
# Cleanup script: SQL to wipe manual-test rows so you can re-run
# ───────────────────────────────────────────────────────────────────────

def write_cleanup_sql():
    (OUT / "_cleanup.sql").write_text(
        "-- Run before re-running the manual-test scenarios:\n"
        "--   psql -d data_hub -f data/manual_test/_cleanup.sql\n\n"
        "-- Phase 2026-05-04 BCCT (files 01-03b)\n"
        "delete from hub.bcct_row_history\n"
        " where transaction_key like 'MAN\\_%' escape '\\';\n\n"
        "delete from hub.bcct_rows\n"
        " where transaction_key like 'MAN\\_%' escape '\\';\n\n"
        "-- Phase 1+2+3 (files 04-11) — BQD / Catalog / BOM\n"
        "delete from hub.code_mappings\n"
        " where internal_code like 'MAN\\_%' escape '\\';\n\n"
        "delete from hub.materials\n"
        " where customs_code like 'MAN-%' or product_code like 'MAN\\_%' escape '\\';\n\n"
        "-- Cascade delete BOM versions for MAN_ products (also clears bom_version_rows)\n"
        "delete from hub.bom_versions\n"
        " where product_code like 'MAN\\_%' escape '\\';\n\n"
        "-- Pending rows from any in-flight preview\n"
        "delete from hub.upload_pending\n"
        " where parsed_rows::text like '%MAN\\_%' escape '\\'\n"
        "    or parsed_rows::text like '%MAN-%';\n\n"
        "-- LLM-cached mappings from manual-test runs\n"
        "delete from hub.parser_mappings\n"
        " where mapping::text like '%MAN\\_%' escape '\\'\n"
        "    or mapping::text like '%报关%'\n"
        "    or sample_headers::text ~ 'Internal|Customs|Recipe|Finished Goods';\n\n"
        "delete from hub.file_uploads\n"
        " where original_filename like '0%_stage_%.xlsx'\n"
        "    or original_filename like '04_bqd%' or original_filename like '05_bqd%'\n"
        "    or original_filename like '06_catalog%' or original_filename like '07_catalog%'\n"
        "    or original_filename like '08_bom%' or original_filename like '09_bom%'\n"
        "    or original_filename like '10_bcct%' or original_filename like '11_malformed%';\n",
        encoding="utf-8",
    )


def main():
    stage_ab_full_co()
    stage_d_chinese_headers()
    stage_c1_baseline()
    stage_c1_changed()
    bqd_basic_rigid()
    bqd_llm_english()
    catalog_basic_rigid()
    catalog_llm_english()
    bom_basic_rigid()
    bom_llm_english()
    bcct_all_new_phase2()
    malformed_random()
    write_cleanup_sql()
    print(f"generated fixtures in {OUT}")
    for f in sorted(OUT.iterdir()):
        if f.is_file():
            print(f"  {f.name}  ({f.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
