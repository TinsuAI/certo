# 2026-05-27 — Cost Allocation Ratios (per-client × per-Mã-SP cost-buildup auto-fill)

## What Was Done

### Feature brief (`/discover`)
- `.ai/features/2026-05-27-cost-allocation-ratios.md` (~125 lines) — scope, decisions, risks, open Qs.
- Pre-discover step: pulled the GROWATT sample (`P:\Downloads\BANG PHAN BO TY LE CHI PHI.xlsx`) into `.ai/samples/`, identified the column layout (B=Mã SP, C-G=cost details, H=profit-residual, I=transport, J=note), and mapped them to existing `product.cost_buildup` keys.
- User chose: schema expand 4 → 6 details, storage CO Postgres (not Data Hub), Mode A primary + B fallback.

### Migration + store
- `db/migrations/012_cost_allocation_ratio.sql`: composite PK `(client_id, product_code)`, `product_code=''` is the Mode B sentinel. 6 coefficient columns (`numeric(14,10)`) + note + updated_at.
- `app/cost_allocation_store.py`:
  - `CostAllocationRow` dataclass (Decimal coefficients, no profit field).
  - `list_ratios`, `get_ratio` (with Mode B fallback), `get_mode_b_default`, `upsert_ratio`, `delete_ratio`, `replace_all` (per-Mã-SP only; preserves Mode B), `diff_replace`.
  - DB-and-JSON dual-write: DB when `BARRY_DATABASE_URL` is set, JSON fallback at `config/cost-allocation/<client>.json`. Reads prefer DB.
- 14 unit + integration tests cover both backends.

### Schema expansion (cost_buildup)
- `_sanitize_cost_buildup` in `app/co_case_store.py`: now accepts union of 11 keys (6 detail + profit + 3 legacy rollups). Persists what came in — no lossy reshape. Switched the numeric coercion from `decimal_value()` (returns 0 on bad input) to direct `Decimal(text)` so invalid input → `""` (preserves "user hasn't filled in" semantics).
- `_coerce_cost_buildup` in `app/bang_ke_xml_generator.py`: if any 6-detail key present, roll up to 4 rollups (`labor = wages+welfare`, `overhead = rent+depreciation+other_mfg`, `other = transport_storage`); else fall back to legacy 4-key shape directly. XML config (`config/bang-ke-config.xml`) untouched — still consumes 4 rollups.
- Form-merge whitelist in `app/main.py:260` extended to 10 keys.
- Form-field parser in `app/demo_data.py:636` reads all 7 new keys + legacy 3 for back-compat.
- 9 dedicated schema tests in `tests/test_cost_buildup_schema.py`.

### Excel importer
- `app/cost_allocation_importer.py`: parses by column index (header rows are bilingual and merged across rows 2-3, can't match by text). Data starts row 4, terminates on first row without `Mã SP`.
- `apply_to_fob(row, fob)` helper produces the 6 detail values for the cost-buildup auto-fill, quantized to 2 decimals.
- 8 tests cover the real GROWATT file (24 rows expected), comma-separator parsing, malformed/blank handling, and the apply helper.

### Admin UI
- New route family `/clients/{id}/cost-allocation` in `app/main.py`:
  - `GET ` — page render (Mode B panel + Mode A table + upload + template download).
  - `POST /mode-b` and `/mode-b/delete` — Mode B default.
  - `POST /row/delete` — Mode A row delete.
  - `POST /upload` — Excel replace-all with diff banner.
  - `GET /template.xlsx` — empty template download.
  - `GET /resolve?product_code=&fob=` — JSON resolver consumed by the origin-panel "Áp hệ số" button.
- `app/templates/cost_allocation.html` — Mode B form (6 inputs) → Mode A upload + table.
- Nav tab added: `app/templates/_client_nav.html` between BCCT and Config.
- 8 route tests with TestClient + tmp config dir.

### Origin panel UI
- `app/templates/co_case.html` lines 1056-1135: cost-buildup grid expanded from 4 → 6 detail inputs + editable profit. "Áp hệ số" button in `<summary>`, visible always; click handler calls `/resolve`, fills 6 details with confirm-overwrite if any input non-empty, leaves profit blank.
- Autosave JS extended to capture 7-key shape.
- Hint JS still sums all detail inputs vs FOB; text simplified ("Tổng chi phí ngoài NPL = …").
- New JS function `initCostBuildupApply()` wired into `refreshCaseShellInteractions()`.
- CSS in `app/static/css/app.css`: `.cost-buildup-grid-6` 4-col → 2-col responsive, apply button styling, status text states (ok/warning).

### E2E verification (`scripts/e2e_cost_allocation.py`)
- Headless Playwright drives: SSO login → admin page → upload GROWATT → `/resolve` JSON check → open case origin → click Áp hệ số → screenshot.
- Screenshots in `.ai/screenshots/cost-allocation/` (1-admin-empty, 2-admin-after-upload, 3-origin-before-apply, 4-origin-after-apply). Last two captured after the `evaluate_rvc_ctsh` fix.
- Resolve endpoint for `PV00.0048400` @ FOB=1000 returned: wages 8.99, welfare 0.82, rent 25.81, depreciation 17.34, other_mfg 9.49, transport_storage 3.41 — matches the GROWATT coefficients exactly.
- Click on `TP-ZIP` (FOB=100) — not in GROWATT list — fell back to Mode B (set during earlier admin smoke), filled `wages=0.50` (`0.005 × 100`). Confirms Mode A→B fallback path.

### Pre-existing bug fix
- `app/origin.py:109`: `row["hs_code"]` → `row.get("hs_code", "")`. One-char fix for a bug that's existed since the demo commit. Surfaced only after Data Hub became material source-of-truth (some materials don't have HS). Unblocked case CO-ZIP's origin page; likely fixes several of the ~30 pre-existing test failures.

### Perf fix
- `_cost_allocation_context()` was calling shared `client_context()` which triggers `source_workspace_for_client()` (Data Hub BCCT scan ~2.6s on Growatt) + `form_candidates_for_market` (~310 ms) + others. Replaced with a minimal context: `resolve_client(client_id)` + ratio rows + `active` flag. **3588 ms → 67 ms (53× faster).** Nav tagline counts conditionally hidden via `{% if client.counts %}` in `_client_nav.html` so the lightweight context doesn't AttributeError.

### .gitignore updates
- Added `/config/cost-allocation/` (per-client agency data), `/.ai/samples/` (agency Excel files), `/.ai/screenshots/` (local artifacts).

## Decisions Made

- **Storage = CO Postgres, not Data Hub.** Cost-buildup ratios are CO-form-specific accounting policy (TT 05/2018), not shared master data. Data Hub policy test does not apply.
- **Persist 6 details + editable profit; do not persist rollups.** Engine rolls up at read time. Avoids dual-copy divergence and keeps `bang_ke_xml_generator` as the single source of rollup semantics.
- **Profit is residual on import; user-editable in the panel.** GROWATT file's H column (`=GIÁ XUẤT XƯỞNG - CHI PHÍ XUẤT XƯỞNG`) is ignored on import. UI leaves profit blank after Áp hệ số; user can override.
- **Replace-all on Excel upload.** Agency files are authoritative snapshots; partial-upsert would leave zombie rows for codes the agency dropped. Mode B preserved across uploads (it lives in the same table with `product_code=''`).
- **Mode A primary, Mode B fallback in `get_ratio()`.** Single-table model with composite PK. Diff math in `replace_all()` excludes Mode B.
- **Don't gate cost-allocation writes behind `require_local_source_writes()`.** That guard exists for Data-Hub-owned shared source data (BCCT, catalog); cost-allocation ratios are CO-only config.
- **Match Mã SP by `product.bom_product_code or product.code`**, case-sensitive exact. The same key the bảng kê renderer already uses.
- **Skip `client_context()` for the admin page.** Pulled the perf bottleneck. Tradeoff: nav tagline counts hidden on this page — acceptable for an admin-only sub-page.
- **Schema migration policy = forward-only.** Existing 4-key `cost_buildup` rows still readable; new writes emit 6-key shape; engine reader handles both.

## What Didn't Work

- **First sanitizer pass used `decimal_value()`** (existing helper that returns `Decimal(0)` on parse failure). That broke the "invalid input → empty string" semantics. Switched to direct `Decimal(text)` with explicit `InvalidOperation` catch.
- **First sed attempt to drop `require_local_source_writes()` guards** deleted the wrong lines (decorators + `async def` signatures, not the guard calls themselves). Symptom: `SyntaxError` on module import. Fixed by reading the corrupted region and rewriting it via `Edit` rather than line-based sed.
- **First e2e run used `wait_for_url("**/cost-allocation", timeout=10000)`** — timed out because the navigation chain (`/auth/callback?…` → `303` → admin URL) had already completed by the time we waited, so no fresh navigation event fired. Changed to `wait_for_selector('form[action$="/cost-allocation/upload"]')` which works regardless of whether the URL just changed.
- **First admin upload returned `409 Conflict`** because the new POST route inherited `require_local_source_writes()`. Wrong guard for CO-only config writes — removed.
- **DB-backed tests leaked across test runs** because rows persisted between tests using the same client_id. Fixed by forcing the JSON-fallback path in unit tests (`monkeypatch.delenv("BARRY_DATABASE_URL")`) and adding one separate DB integration test with a per-pid client_id and explicit cleanup.
- **Tried to verify counts via cheap COUNT queries** (`select count(*) from material_catalog_published_rows where client_id=…`) to avoid the slow workspace load — tables don't exist locally; that data lives in Data Hub now. Abandoned and just hid the counts on this page.
- **Status text capture in e2e timed too early** — `wait_for_function` returned on first non-empty status ("Đang tra hệ số…") instead of the final "Đã áp hệ số …". Minor; screenshot still captures the final state because the page is settled when the screenshot runs.

## Open Items

- **Pre-existing 30 test failures on `main`** — same class of bug as the `hs_code` fix (strict `[key]` accessors over evolved demo data). Worth a follow-up sweep with the `[key]` → `.get(key, "")` pattern.
- **Real Mode-A live screenshot still missing**: today's UI test used `TP-ZIP` which legitimately fell back to Mode B. A case using a product code from the GROWATT 24 (`PV00.0048400` etc.) would close the visual loop on Mode A.
- **Replace-all semantics on partial agency updates**: if an agency starts sending incremental files instead of full lists, we'll need an upsert-by-row mode. Easy to add via a checkbox on the upload form.
- **Versioning of ratios** is explicitly out of scope. If a C/O case computed against the "old" ratios needs re-computation, today the user must re-apply manually. If this becomes a pain point, add `valid_from / valid_until` columns.
- **CTH/CTSH/PSR cases**: cost-buildup section is shown on all products (`<details>` always present, just collapsed when criterion isn't LVC/RVC). Áp hệ số button is also visible. That's harmless but possibly surprising — could hide button for non-LVC/RVC criteria.
- **6 detail rendering on the bảng kê itself** (vs the current I-VIII rollup view): explicitly deferred to phase 2 per brief; no agency request yet.
