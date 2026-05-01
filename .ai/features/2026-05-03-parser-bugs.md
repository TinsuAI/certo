# Parser bugs surfaced by real-data fixture corpus (2026-05-03)

**Status: ALL FIXED 2026-05-03** — see `.ai/sessions/2026-05-03-parser-fixes.md`
for the resolution session.

## Context

Built a 26-case fixture corpus (`tests/fixtures/` + `tests/test_fixture_corpus.py`)
sourcing from `barry-CO-bom-data/local/manual-test-files/` (18 curated files)
plus 7 synthetic edge-case files. Smoke-tested every fixture against the
right parser. Also ran real `.xls/.xlsm` files from
`barry-CO-data/extracted/Growatt-20260421/`, `BCQT-DKE/input/`, and
`bcqt-dothanh/data/extracted/`.

Result: 19 fixtures pass cleanly, 7 xfail mapping to 5 distinct bugs, plus
1 P0 found only via real-data testing.

## Bugs

### P0 — Legacy `.xls` format unsupported

**Where:** `app/parsers/_excel.py:load_xlsx` — uses `openpyxl.load_workbook`,
which only handles OOXML (`.xlsx`, `.xlsm`).

**Surface:** every real BCCT and Danh Mục file we have today is `.xls`:
- `barry-CO-data/extracted/Growatt-20260421/Growatt/BaoCaoHangChiTiet[NK,XK]*.xls`
- `BCQT-DKE/input/28.03 XU LY DINH MUC/BaoCaoHangChiTiet 2025 Official.xls`
- `BCQT-DKE/input/.../BẢNG MÃ NVL-SP - Update March 24.xls`
- `bcqt-dothanh/data/extracted/BCQT SXXK 2025/BaoCaoHangChiTiet[E31,E62]*.xls`
- `barry-CO-data/extracted/CO/bom-supplier-zips/.../DANH MUC NPL/SP DK HQ MOI.xls`

Error: `Cannot open workbook: File is not a zip file` /
`File contains no valid workbook part`.

**Fix options:**
1. Add `xlrd` (deprecated for .xlsx in newer xlrd; still supports .xls) and
   route by extension/magic bytes in `_excel.load`.
2. Convert in flight: `libreoffice --headless --convert-to xlsx`.
3. Reject at upload-time with a clear error message asking the user to
   re-save as `.xlsx` from Excel.

Option 1 is cleanest. Two-line change in `_excel.py` to dispatch based on
magic bytes (`PK` = zip = OOXML; `\xD0\xCF\x11\xE0` = OLE = legacy xls).

### P0 — BCCT parser falsely matches BOM workbook

**Where:** `app/parsers/bcct.py:50-52` — accepts a sheet if EITHER
`customs_code` OR `declaration_no` columns are present.

**Surface:** real Growatt 51MB BOM `.xlsm` parses as **197,360** BCCT rows
because BOM's `Mã NVL` column aliases to `customs_code` in the BCCT alias
map. Synthetic repro: `tests/fixtures/edge_cases/bom_workbook_uploaded_as_bcct.xlsx`.

**Risk:** if an agency staffer uploads a BOM file to the BCCT slot in the
UI, hub silently ingests 200K junk rows. Currently no upload-side
validation distinguishes the two.

**Fix:** tighten gating to require BOTH `declaration_no` AND a
direction-cue column (date, declaration_type, OR explicit direction). BOM
files lack all three. Two-line change in `bcct.py:51`.

### P1 — Chinese BOM headers not aliased

**Where:** `app/parsers/bom.py:COMMON_ALIASES`.

**Surface:** real Growatt 2026 BOM template uses Chinese:
- `成品物料` (finished product)
- `组件物料` (component)
- `组件物料描述` (component description)
- `标准用量` (standard quantity)
- `单位` (unit)

Fixtures: `25/26-growatt-technical-*.xlsx`, `edge_growatt_bom_chinese`.

**Fix:** extend `product_code/material_code/qty_per_unit/uom` aliases with
Chinese strings.

### P1 — SAP English headers not aliased (Johnson)

**Where:** `app/parsers/bom.py:_parse_johnson` — `material_code` aliases.

**Surface:** real Johnson SAP export uses:
- `Component number` (material_code)
- `Comp. Qty (CUn)` (qty_per_unit)
- `Component unit` (uom)

Fixtures: `30-johnson-technical-sap-leaf-only.xlsx`,
`edge_johnson_sap_english`.

**Fix:** extend Johnson profile aliases.

### P1 — SP-only catalog (no Mã HQ) rejected

**Where:** `app/parsers/materials.py:60` — requires `customs_code` column.

**Surface:** DS Thành Phẩm catalogs typically don't have HQ codes (SP codes
ARE the canonical identifier from the agency's perspective; HQ assigns codes
later during declaration). Fixture `03-growatt-ds-sp-full-products.xlsx`
has only `product_code/name/hs_code/rule/status`.

**Fix:** when sheet name is TP/SP and `product_code` column exists, treat
it as the canonical code; relax the `customs_code` requirement.

### P1 — Real Growatt BOM `.xlsm` doesn't fit any of 3 profiles

**Surface:** `barry-CO-data/.../tru lui CO final SXXK 2025.xlsm` opens
fine (it's xlsm = OOXML), but all 3 BOM profiles fail: `manual_flat`,
`growatt_multi_workbook`, `johnson_sap_exploded` all raise
`BomParseError`.

**Cause:** likely uses Chinese headers (overlaps with the P1 Chinese-headers
bug); also the workbook structure is one-sheet-per-product but with extra
config sheets that the multi_workbook profile doesn't filter out, or the
header row isn't where `header_row()` looks. Needs deeper inspection.

**Fix:** after Chinese aliases land, re-test. May still need a 4th profile
or extension of `growatt_multi_workbook` to handle the 2026 format.

## What's NOT broken

- All 6 Do Thanh BCCT scenarios (overlap, unit conflict, qty conflict,
  reupload, mixed import-export) parse correctly.
- 5 Growatt direct/flat BOM scenarios (no-change, qty-change, retire,
  partial, duplicate-row) parse correctly.
- DS NVL catalog (full + partial) parses correctly.
- Header scanner tolerates title/metadata rows above the actual header
  (tested via `headers_in_row_5` fixture).
- Empty workbooks raise the right ParseError per parser.

## How the corpus runs

```bash
# Corpus tests (fast, no DB):
uv run pytest tests/test_fixture_corpus.py -v

# Real-data tests (gated; skipped without env var):
DATA_HUB_REAL_DATA_DIR=/path/to/real \
  uv run pytest tests/test_real_data_external.py -v

# Full suite:
uv run pytest -q
# 59 passed, 10 skipped, 7 xfailed
```

## When a bug is fixed

Flip the corresponding `CASES` entry in `tests/test_fixture_corpus.py` from
`{"xfail": "..."}` to a numeric expectation (`{"rows": N}` or
`{"products": N, "rows": M}`). The xfail-aware test will hard-fail if the
parser starts succeeding without the expectation being updated, forcing
the author to lock the new contract explicitly.

## Cross-repo

No sister-repo coordination needed — these are parser bugs scoped to Data
Hub. When the .xls fix lands, BCQT/CO migrations (when they happen) won't
need to know — those consumers read from `hub.bcct_rows` (already-parsed),
not raw uploads.
