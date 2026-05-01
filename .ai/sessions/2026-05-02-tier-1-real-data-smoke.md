# Session: 2026-05-02 — Tier 1 real-data smoke (BOM + BQD)

Closing the MVP coverage gap from STATUS "Next Steps #1 + #2": real BOM
and real BQD had never been driven through the HTTP layer end-to-end
before this session. Approach was: explore sister-repo data, organize
by company, capture current behavior in an env-gated parser-layer test,
then drive the same files through the live UI with Playwright.

## What was done

### 1. Real-data discovery (sister repos)

Explored bcqt-growatt, BCQT-DKE, bcqt-dothanh, Johnson, BCQT-System,
barry-CO-data, barry-CO-bom-data, barry-CO-main. Compiled a candidate
table organized by company. Discovered an existing curated test corpus
at `~/workspace/client/barry-CO-bom-data/local/manual-test-files/`
(19 files designed for full UI walkthrough).

### 2. Staging (`/tmp/dh_real_data/`)

Symlinked 6 new files following the existing BCCT layout convention:

| Company | Path | Source | Notes |
|---|---|---|---|
| growatt | `bom_tp.xlsx` | bcqt-growatt/data/archive | 963 KB Chinese SAP shape |
| growatt | `bom_btp.xlsx` | bcqt-growatt/data/archive | 462 KB same shape, BTP |
| growatt | `bqd_tp.xlsx` | bcqt-growatt/data/archive | 14 KB Vietnamese N-to-N (TP) |
| growatt | `bqd_nvl.xlsx` | bcqt-growatt/data/archive | 170 KB Vietnamese N-to-N (NVL) |
| dke | `bqd.xls` | BCQT-DKE/input/28.03 | 143 KB multi-sheet legacy `.xls` |
| johnson | `bom_sap.xlsx` | barry-CO-bom-data/local/manual-test-files | 4 KB synthetic SAP-leaf |

**Skipped:** DKE `DINH MUC.xlsx` (Mẫu 16 settlement form, not a hub BOM);
Dothanh BOM (no real file found).

### 3. Parser-layer smoke test extension

`tests/test_real_data_external.py` extended with BOM + BQD parametrized
blocks. Reflects current observed reality with xfail markers for known
gaps. Result with env set: **9 passed + 5 xfailed**. Without env, all
real-data tests skip cleanly. Full suite still green: **104 passed**.

### 4. UI-driven HTTP smoke (`scripts/smoke_real_uploads.py`)

New Playwright script that logs in, drives each upload through the
actual web form, captures before/after screenshots per
company × entity to `data/screenshots/real_uploads/`. Map: Growatt BQD
TP + NVL → growatt-vn; Johnson BOM SAP → johnson-vn; Growatt BOM TP
exercise the parse-error path. Final result: **4 of 4 active jobs
matched expectation**, 1 intentionally skipped (Bug C unsafe).

### 5. DB verification

| Check | Expected | Got |
|---|---|---|
| growatt-vn `code_mappings` | 8 seed + 73 TP + 2819 NVL = 2900 | **2900** ✓ |
| johnson-vn `bom_versions` | 1 seed + 1 upload = 2 | **2** ✓ |
| johnson-vn latest `bom_version_rows` | 2 (synthetic SAP fixture) | **2** ✓ |
| growatt-vn `file_uploads` bom errored | 1 (BOM TP rejected) | **1** ✓ |
| growatt-vn `file_uploads` bqd done | 2 | **2** ✓ |

### 6. Bugs logged to `.ai/BACKLOG.md`

Three parser bugs + one UX bug captured, scoped per-file with fix ideas:

- **Bug A** (P0): `header_row()` in `app/parsers/_excel.py:68` picks data
  row over header row when STT inflates the data-row non-empty count.
  Blocks every real Growatt BOM today.
- **Bug B** (P1): DKE BQD alias gap. 1-line addition — `Mã ERP` /
  `Mã NPL/TP`.
- **Bug C** (P0, *silent corruption*): `index_headers()` pass-2
  substring match treats `'' in target` as True, claiming empty trailing
  header cells as column matches. Real Growatt BTP "ingests" 50 garbage
  products with `product_code='FARATRONIC'` (a brand string). NO user-
  visible error. Found while triaging Bug A.
- **UX-1** (low): `app/routes/bom.py:85` BomParseError surfaces as raw
  FastAPI JSON `{"detail":...}` in the browser instead of an in-app error
  page. Compare BCCT's parse-mapping flow which renders a proper template.

## Decisions made

- **Smoke tests capture current reality, not future state.** xfail with
  rich `reason=` strings (file path + class of fix) matches the existing
  pattern in `test_real_data_external.py` for legacy `.xls`. When fixes
  land, xfails flip to assertions naturally.
- **DON'T post Growatt BOM BTP through UI.** Bug C would silently insert
  50 garbage rows. Script just screenshots the form and labels it
  `_form_skipped`. Expanded the script's `JOBS` table with an explicit
  `expected="skip_unsafe"` value for this case.
- **Tighter shape assertion for Bug A xfail.** First version asserted
  only `len(products) >= 10`, which Bug C's garbage path satisfied →
  XPASS noise. Tightened to a regex on real Growatt product-code shape
  (`^[A-Z]{1,4}[0-9]+\.[A-Z0-9]+$`), which the brand-string garbage
  ('FARATRONIC') fails. Now xfails cleanly.
- **Skip the HTTP-route pytest variant.** Originally Task #4 was a
  TestClient-driven HTTP test; deleted in favor of Playwright (which
  exercises the same path with the bonus of screenshots + login flow).
  Rationale: existing `tests/test_bcct_confirm_flow.py` doesn't actually
  use TestClient despite its docstring — the project hasn't built that
  pattern yet, and Playwright is closer to user reality.

## What didn't work / Surprises

- **Playwright `page.click('button[type="submit"]')` clicked the topnav
  lang-toggle button** instead of the upload form's submit. Multiple
  submit buttons on the page (lang/theme/logout in topnav). Fixed by
  scoping selector to `form[action*='/upload'] button.btn-primary[type='submit']`.
- **First `expect_response` predicate timed out at 30s.** Even when the
  POST eventually succeeded server-side, Playwright's response listener
  didn't catch it. Replaced with a `page.on('response', ...)` listener
  pattern + `wait_for_url(list_url)` which is more robust.
- **Bug A and Bug C compounded surprisingly.** Initial smoke run reported
  BOM BTP "passes" with 50 products. Took digging through `index_headers`
  internals to realize the parser was matching empty header cells via
  `'' in target` substring fallback — a genuinely silent data-corruption
  bug that the test now documents.
- **Existing dev server was on :8754** when I tried to start one in the
  background. The script worked because it was talking to the existing
  one. Worth knowing — bg uvicorn won't fail loudly if port is taken.

## How to resume

```bash
cd ~/workspace/client/data-hub
# Server should still be on :8754 (started in prior session). If not:
uv run uvicorn app.main:app --port 8754 --host 127.0.0.1 --reload

# Tests (real-data tests gated on env)
uv run pytest -q                                                 # 104 passed
DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data uv run pytest -q        # +9 / 5 xfailed

# Re-run UI smoke (regenerates screenshots; re-uploads BQD files —
# code_mappings has on-conflict-update so it's idempotent on internal+customs key,
# but BOM creates a fresh version each run if hash differs — re-runs are safe).
DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data uv run python scripts/smoke_real_uploads.py

# Visual evidence
ls data/screenshots/real_uploads/
```

## Open items

Tier 1 closed for the files we can locate. Remaining MVP-validation gaps:

- **Real Dothanh BOM/BQD** — not found in any sister repo. Ask user.
- **DKE BOM** — only file is the Mẫu 16 settlement form, not in scope.
- **Bug A / B / C / UX-1 fixes** — captured in BACKLOG. Bug C is the
  most urgent (silent corruption) but Bug A blocks any real Growatt BOM
  upload regardless. Suggested order: A + C in one PR (both touch
  `app/parsers/_excel.py`), then B (1-line alias add), then UX-1.

## Files touched

- `tests/test_real_data_external.py` — added BOM + BQD parametrized blocks
- `scripts/smoke_real_uploads.py` — new Playwright UI smoke
- `.ai/BACKLOG.md` — 4 new bugs logged (A/B/C/UX-1)
- `data/screenshots/real_uploads/*.png` — 9 captured screenshots
- `/tmp/dh_real_data/{growatt,dke,johnson}/` — 6 new symlinks
- `.ai/STATUS.md` — updated with this session
