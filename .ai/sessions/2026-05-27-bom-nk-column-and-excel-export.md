# 2026-05-27 (PM) — BOM phẳng: NK column + Excel export + demo deploy + audit

Second session of 2026-05-27 (the morning ran the stale-UX rebuild — see
`2026-05-27-bom-stale-rebuild.md`). Two small UX features on the flat BOM
artifact detail page, plus a deploy to the demo box and a verification audit
of Johnson + Growatt flatten data on demo.

## What Was Done

### 1. NK / BOM-only "Nguồn" column

`app/routes/bom.py::artifact_detail` now calls
`make_bcct_import_lookup(client_id)` once per request and attaches
`has_nk = lookup(material_code)` to each row before rendering.

`app/templates/clients/bom_artifact_detail.html` got a new rightmost
column "Nguồn" with a small badge:
- "NK" — when `has_nk` is true (material has ≥1 import BCCT row)
- "BOM-only" (warn-style badge) — otherwise

The column only renders on the rows-based path (when `edges` is empty); the
raw_graph edges table is unchanged.

### 2. Excel export

New route `GET /clients/{client_id}/bom/artifact/{artifact_id}/export.xlsx`
in `app/routes/bom.py`. Pattern copied from
`/clients/{cid}/uom-factors/template.xlsx`:
- `openpyxl.Workbook()` in-memory, written to a `BytesIO`.
- Sheet name `BOM_<product_code>` truncated to 31 chars (openpyxl limit).
- Filename `BOM_<product_code>_v<artifact_no>.xlsx`.
- Header row first, then one body row per `bom_artifact_rows.row` —
  `qty_per_unit` cast to `float` so the cell is numeric (not string).
- Returns 400 if the artifact has no flat rows (raw_graph).

Template renders the "⬇ Xuất Excel" button next to the existing
"← artifacts" link, gated on `{% if rows %}` so raw_graph hides it.

Initial column order had "Nguồn" as col 3; user asked to move it last,
done in commit `5fefa4a`. Both UI and XLSX export updated together.

### 3. Demo deploy

- `git push origin main` — fast-forwarded `a331c74..5fefa4a`.
- ssh.exe to `tinsu@100.84.189.87`, `cd ~/data-hub`,
  `git pull --ff-only && docker compose up -d --build`.
- Build took ~30s, container recreated, app healthy at HTTP 200 within ~10s.
- App-on-startup migrator ran 067–071, including the two backfill rounds.
- Verified via curl (see workaround note below) + openpyxl inspection of
  the downloaded `export.xlsx` against johnson-vn artifact
  `ba_drOLJTU33ZyLWzvz` — 14 rows, header order matches, NK/BOM-only
  values consistent with DB.

### 4. Audit on demo

User asked twice for verification: first "BOM phẳng từ BOM kỹ thuật của
Johnson đã ổn chưa?" then "Còn Growatt thì sao?" + "Growatt có mâu thuẫn
đơn vị tính gì không?". All queries run via
`docker compose exec -T db psql -U hub -d data_hub`.

**Johnson:**
- 100% coverage: 3137 raw → 3452 ff artifacts (315 products have multiple
  ff versions from history; expected).
- 3400/3452 ff clean (98.5%).
- 52 needs_input — all from UoM drift dimensions `factor_missing` (10
  artifacts, all from material `1000469803` mixed EA/KG, the known open
  item) and `unconfirmed_default_1to1` (42 artifacts from 13 codes, top
  `1000202688` hitting 42).
- 0 duplicate (artifact_id, material_code) rows — dedup fix `7552c64`
  from 2026-05-12 holding.
- Row-count distribution: 63% products 1-5 rows, 2% >100 rows (consistent
  with apparel/footwear BOMs).
- Spot-check 1000534541: raw 2 edges → ff 2 rows (matches the memory
  `project_bom_subtree_dedup.md` post-fix count).
- Spot-check 1000553612: raw 14 edges → ff 13 rows (loses the TP root row,
  which is correct).

**Growatt:**
- 99.5% coverage: 197/198 raw → ff. The one gap is `B710.0071401` — raw
  uploaded 2026-05-05 with 83 edges, intent `asserted_technical`, but
  flatten never ran for it. Not tombstoned, real missing ff.
- 197/197 ff clean (100%).
- 0 duplicate rows.
- Row distribution is much heavier than Johnson: 36% products >100 rows,
  consistent with inverter BOMs (deep technical exploded).
- 1 manual_flat with state=needs_input named literally `TEST_TP_DRIFT` —
  test fixture from 2026-05-10, not real production data.

**Growatt UoM contradictions:**
- Only 1 real material drift: `033.0024500` — catalog `PIECES`, BCCT has
  1 import line `PIECES` + 15 import lines `SETS`, no
  `hub.client_uom_overrides` row. `hub.is_uom_aligned('SETS','PIECES')`
  returns false, so it's a real factor question for the agency. The
  material is not used in any BOM artifact, so the artifact-level drift
  gate doesn't flag it — that's the design (drift surfaces on BOM-side
  evidence), and the gap is the "stretch" item in Next Steps.
- 5 alias-resolved "mismatches" (B700.* + PV01.0104300): catalog `ST`/`PCS`
  vs BCCT `PIECES`. `is_uom_aligned()` returns true for both, no flag,
  correct.
- 6 materials with NULL `uom` in catalog: 3 fixtures (DEMO-NPL-001/002,
  VAI), 2 TPs (PV00.0048500, PV01.0117600 — TPs don't strictly need
  uom for BOM math), and 1 real NVL gap (001.0031100).
- Phantom code `.` shows up with 840 BCCT rows across many units — all
  from declaration type `E13` (export, pre-export domestic supplier
  sales). Not a real material code, ignore.

## Decisions Made

- **NK lookup is per-request, not cached.** `make_bcct_import_lookup`
  preloads a `set` of distinct customs_codes (~thousands rows max). One
  SELECT per artifact-detail render is fine; no need for a memoized
  module-level cache that would have to invalidate on every BCCT upload.
- **"Nguồn" column applied only to rows view, not edges view.** Raw_graph
  edges show parent/child columns; bolting NK there would need lookups
  per edge endpoint, and the data isn't useful (child code's NK status
  doesn't tell you much in a graph traversal context). Rows-only is the
  right scope.
- **Excel column order: identifying → numeric → context → status.** Put
  Nguồn at the rightmost end (user-requested). Matches how spreadsheets
  read: scan ID and qty first, decoration last.
- **Filename includes `v<artifact_no>`.** Multiple artifacts per product
  exist; the version number prevents downloaded files from clobbering
  each other in user's Downloads folder.
- **400, not 404, for raw_graph export.** The artifact exists; the
  feature is not applicable for its shape. 400 = "request not valid
  for this resource state" is semantically right.
- **No new tests written.** Diff is 80 LOC, the routes use existing
  helpers, manual verification via Playwright + openpyxl inspection.
  The 254-test BOM suite still passes. Test-after for cosmetic UI per
  CLAUDE.md.

## What Didn't Work

- **First Playwright verify attempt against demo** used the
  `Secure`-flagged session cookie over HTTP — `urllib.request` quietly
  dropped the cookie on redirect, login flow appeared to succeed (303
  to /clients) but the next request 401'd. Workaround: grep
  `set-cookie` from the login response and re-send via explicit
  `Cookie:` header. Worth fixing the underlying `Secure` flag if we
  ever serve demo over plain HTTP long-term, but out of scope here.
- **psql with passwords flag** (`-h 127.0.0.1 -U hub`) failed locally —
  this dev box has TWO data_hub Postgres instances (per memory
  `reference_dev_db_topology.md`), and the native one uses peer auth as
  user `vp`. `psql -U vp -d data_hub` is the right invocation locally;
  `docker compose exec -T db psql -U hub -d data_hub` is the right one
  on demo.

## Open Items

- `B710.0071401` (Growatt) — needs flatten run.
- `033.0024500` (Growatt) — needs UoM override confirmation from agency.
- 14 Johnson codes still flagged on demo — `reconcile_for_material()`
  will clear them in-band once overrides land.
- 3 real Growatt NVL/TP without uom in catalog.
- (Stretch) Material-level drift surface for codes not in BOM —
  artifact-level gate misses standalone NVL mismatches.
- (Cleanup) `TEST_TP_DRIFT` Growatt manual_flat artifact — confirm it's
  safe to tombstone since it's a fixture, not production. Out of scope
  this session.
