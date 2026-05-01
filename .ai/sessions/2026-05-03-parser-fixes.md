# Session: 2026-05-03 — Real-data fixture corpus + 5 parser bugs fixed

Continued from `2026-05-02-rip-resolver.md`. User asked to drive real client
data through Data Hub and build a permanent test suite. The corpus surfaced
5 parser bugs immediately; user pushed back on the schedule offer ("tại sao
không fix luôn") so all bugs got fixed in the same session.

## What was done

### Phase 1 — Survey + corpus (commit `80b3a89`)

- Inventoried real data across `barry-CO-data/extracted/Growatt-20260421/`,
  `barry-CO-bom-data/local/manual-test-files/`, `BCQT-DKE/input/`,
  `bcqt-dothanh/data/extracted/`. Found:
  - 18 small curated `.xlsx` (`barry-CO-bom-data/local/manual-test-files/`)
    designed for the CO app's manual upload flow — copied into
    `tests/fixtures/manual_test/` as the seed corpus.
  - Real Growatt BCCT NK + XK 2026 (`.xls`, 2.2MB + 134KB), DKE BCCT 2025
    (`.xls`), Dothanh E31 + E62 (`.xls`), Danh Mục NPL/SP (`.xls`),
    Growatt 51MB settlement workbook (`.xlsm`).
- Wrote `tests/fixtures/edge_cases/_generate.py` to produce 7 synthetic
  hub-specific edge cases (Chinese BOM headers, SP-no-HQ, SAP English,
  empty workbook, headers-in-row-5, BOM-as-BCCT trap, DKE synthetic).
- Built `tests/test_fixture_corpus.py` parametrized over 26 cases with
  xfail-aware expected outcomes (numeric row count, exception type, or
  `xfail` placeholder until bugs are fixed).
- Built `tests/test_real_data_external.py` gated on
  `DATA_HUB_REAL_DATA_DIR` for real-file smoke tests.
- Documented in `.ai/features/2026-05-03-parser-bugs.md` + fixtures
  `README.md`.

Initial result: 19 passed + 7 xfail mapping to 5 distinct bugs.

### Phase 2 — Fix all 5 bugs (this commit)

**P0 #1: Legacy `.xls` format unsupported.**
- `app/parsers/_excel.py` — magic-byte dispatch: `PK` → openpyxl,
  `\xD0\xCF\x11\xE0` → xlrd. Thin `_XlsBook` + `_XlsSheet` adapter exposes
  the openpyxl `.worksheets` / `.iter_rows` API; xlrd cell types coerced to
  match openpyxl (datetime for dates, None for blanks, bool for booleans).
- Added `xlwt` dev dep for `.xls` fixture generation.
- Added `tests/fixtures/edge_cases/legacy_xls_bcct.xls` and
  `legacy_xls_materials.xls` to lock the OLE-format path.

**P0 #2: BCCT parser falsely matched BOM workbook.**
- `app/parsers/bcct.py:51` — gate now requires `declaration_no` AND
  `registration_date`. BOM files have neither; settlement workbooks
  (Growatt LVC/RVC summary sheets) cite a declaration_no but lack the date.
- Synthetic trap fixture flipped from xfail to `raises BcctParseError`.

**Reframe during fix:** the real Growatt 51MB workbook isn't a pure BOM —
it has 5 BCCT-shaped sheets (NK/NK2/XK/X-N/Save) with real declaration
data totaling ~197K rows. The "false positive" was actually correct
acceptance. Synthetic test (pure-BOM with no decl/date columns) still
catches the genuine trap.

**P1: Chinese BOM headers + SAP English headers + SP-only catalog +
  Vietnamese short-form aliases.**
- `app/parsers/bom.py:COMMON_ALIASES` — added Chinese (`成品物料`,
  `组件物料`, `标准用量`, `单位`) + SAP English (`component number`,
  `comp. qty`, `component unit`).
- `app/parsers/materials.py:59` — accepts `product_code` as canonical id
  when `customs_code` column is absent. DS SP/TP files commonly have only
  `product_code` because HQ codes are assigned later.
- `app/parsers/bcct.py:ALIASES` — added `Số TK` / `Ngày ĐK` (Dothanh
  abbreviations), `declaration date` (CO-app fixture format).

**Bonus: declaration-type set extended.**
- `IMPORT_TYPES`: added E21, E23, E31, E41, A11, A12, A41, A42, G11-13.
- `EXPORT_TYPES`: added E54, E82, B11-13, G21-23.
- Source: TT39 Phụ lục I + real Dothanh data (E31 + A12 surfaced).

**Bonus fix found during testing: Johnson SAP parent-row leak.**
- `_parse_johnson` was treating level-1 rows as both parent header AND
  appending them as material rows under themselves. The `level == 0` check
  never fires because Johnson's SAP variant starts at level 1.
- Fix: detect `parent_level` dynamically as the first level seen; skip
  rows at that level entirely.

## Results

```
tests/test_fixture_corpus.py:        28 passed (was 19+7 xfail)
tests/test_real_data_external.py:     6 passed (with DATA_HUB_REAL_DATA_DIR set)
full suite (no env var):             68 passed, 7 skipped, 0 xfail (was 40 baseline)
```

Real `.xls` smoke verification:
- Growatt BCCT NK 2026 T3-T4: 3045 rows, all `import`
- Growatt BCCT XK 2026 T3-T4: 137 rows, all `export`
- DKE BCCT 2025 Official: parses (>= 100 rows)
- Dothanh BCCT E31: 132 rows, all `import` (E31 type now recognized)
- Dothanh BCCT E62: 317 rows (97% direction-tagged)
- Growatt 51MB settlement `.xlsm`: 197K BCCT rows from 5 sheets

## Decisions made

- **xlrd (not libreoffice) for `.xls` support.** Already a dep, deterministic,
  no subprocess overhead. xlrd 2.x dropped `.xlsx` but keeps `.xls`.
- **Magic bytes (not file extension) for format dispatch.** Caller passes
  bytes; can't trust the extension since uploads route through `UploadFile`.
- **AND-gate (declaration_no AND registration_date) over more elaborate
  schemes.** Real BCCT always has both; BOM/RVC summary sheets miss at least
  one. Two-line change > heuristic scoring.
- **product_code as canonical fallback in materials.py** rather than
  changing the schema (which still treats `customs_code` as PK). When agency
  has no HQ assignment yet, product_code IS the canonical identifier; we
  just route it into the same DB column.
- **Conservative declaration-type list extension.** Only added codes from
  TT39 Phụ lục I that have evidence in real client data. Didn't speculate.
- **Removed misleading xfail real-data test** (`test_growatt_real_bom_should_not_match_as_bcct`).
  After reframe, the workbook isn't a BOM — it's a settlement workbook
  with BCCT data. Replaced with `test_growatt_settlement_workbook_has_bcct_sheets`
  pinning the expected ~197K row count.

## What didn't work / Surprises

- First gate-tightening attempt (declaration_no only) wasn't enough — the
  Growatt LVC/RVC sheets have declaration_no without date. AND-with-date
  was the right line to draw.
- My CO-app-style synthetic Dothanh fixtures used `declaration_date`
  column header which didn't match the `registration_date` aliases. After
  tightening, those fixtures regressed. Fix: added `declaration date` /
  `declaration_date` to the alias list.
- `header_row()` works fine on Dothanh's 10-row metadata header (max_scan=15
  is enough); no scanner change needed.
- Johnson SAP parser had a latent bug not in the original audit list —
  surfaced when I went to flip the xfail to a numeric assertion and the
  count was off (3 rows vs expected 2). Fixed in same session.

## How to resume

```bash
cd ~/workspace/client/data-hub
uv run pytest -q                              # 68 passed, 7 skipped
DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data \
  uv run pytest tests/test_real_data_external.py -v   # +6 real-data tests

# Server (still NOT running at handoff):
uv run uvicorn app.main:app --port 8754 --host 127.0.0.1 --reload
```

To set up the real-data symlinks like this session did:
```bash
mkdir -p /tmp/dh_real_data/{growatt,dke,dothanh}
ln -sf "<path to BaoCaoHangChiTietnk grw t3-t4.2026.xls>" /tmp/dh_real_data/growatt/bcct_nk_2026_t3-t4.xls
# ...etc per the layout at top of test_real_data_external.py
```

## Open items

- **HTTP-level real-data validation** — parsers are solid; routes layer
  isn't tested at scale (idempotency, dual-source detection, audit views).
  Drive a few real files through the UI next.
- **Growatt 51MB workbook semantic audit** — 5 BCCT sheets total 197K
  rows; are these duplicates across time slices? Save sheet redundant?
  Needs domain confirmation before allowing the file as a single upload.
- All other open items in STATUS.md "Next Steps" unchanged.
