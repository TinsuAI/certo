# Session Summary: Substitute modal, cross-case stock ledger, perf cleanup

Date: 2026-05-13

## What Was Done

### Substitute modal end-to-end (PR3 → fix → polish)
- Added `app/data_hub_client.py::list_material_substitutes` against Data Hub `/api/v1/.../substitutes` (cookie-only); when Data Hub team shipped Bearer-aware `/v1/hub/clients/{c}/materials/{m}/substitutes` later in the day (their commit ae3373b), CO was migrated to that path and the policy whitelist (`tests/test_data_hub_policy.py::APPROVED_DATA_HUB_ENDPOINTS`) was updated. Back-note `2026-05-13-co-substitutes-bearer-consumer-shipped.md` mirrored into Data Hub repo.
- Wrote API request artifacts:
  - `.ai/api-requests/2026-05-11-bearer-aware-substitutes.md` — FULFILLED.
  - `.ai/api-requests/2026-05-13-bcct-by-codes-lookup.md` — pending Data Hub side, would let CO fetch stock for ~20 candidate codes instead of paginating full BCCT.
- Built `compute_substitute_heuristic_candidates`: HS-prefix similarity (0.5 base for 4-digit, 0.7 for 6-digit, +0.2 if any usable CO stock) — fires when Data Hub substitutes endpoint returns 0 items (common when BOM uses a code Data Hub catalog doesn't have).
- Modal redesign: compact `<ul>` cards instead of wide `<table>`, expandable per-item lots table, shared "ĐM áp dụng" input defaulting to the current row's `bom_qty_per`, optimization-mode chip, loading spinner, heuristic-mode banner, lazy stock-merge.
- Split `/substitute-candidates` from `/substitute-stock`: candidates render in ~300ms (one Data Hub call); stock data merges async via lazy `?codes=A,B,C` request.

### Cross-case stock ledger (Postgres)
- Wrote migration `db/migrations/007_co_stock_ledger.sql`: `co_stock_claims` table with claim_id PK, status CHECK ('locked'|'released'), 3 indexes for hot paths (per-lot lookup, per-case audit, per-sheet replace).
- Built `app/co_stock_ledger.py` Postgres-only API: `record_sheet_lock`, `record_sheet_release`, `used_qty_by_lot`, `claims_for_lot`, `claims_for_case`, `apply_used_qty`. Silently no-ops when `BARRY_DATABASE_URL` unset (so test suite still passes without DB).
- Wired `/sheet/{code}/lock` to call `record_sheet_lock_claims(...)` BEFORE `update_case_record` — critical because the form-rebuild path strips `materials[*].allocation_lines`. Helper `_sheet_with_allocations` falls back to persisted disk record when the in-memory case lacks allocations.
- Wired `/sheet/{code}/reopen` to call `co_stock_ledger.record_sheet_release(...)`.
- `co_case_source_context_cached` always re-applies `used_qty_by_lot` to stock_rows so claim mutations propagate even when the source_context is cached.
- New regression test `test_origin_sheet_lock_records_cross_case_stock_ledger_claims` skips when no DB, asserts cross-case claim aggregation when DB present.
- User restarted server with `BARRY_DATABASE_URL='postgresql:///barry_co?host=/var/run/postgresql'`; verified table exists, ledger test passes (3s) with DB.

### Real-time per-cell recompute (Excel-like)
- Each material `<tr>` carries `data-row-original-norm`, `data-row-non-origin-base`, `data-row-origin-status`. Each cell carries `data-base-{consumed,unit-value,material-value,non-origin}` baselines.
- New JS `recomputeSheetTotals(panel)` runs on every ĐM `input` event: recomputes Lượng dùng (= base × ratio), Trị giá NVL, Trị giá KXX, sums VNM, computes LVC = (FOB-VNM)/FOB×100, sets `origin-metric-pass/fail` class against the threshold.
- 15s auto-save timer + dirty-banner with "Lưu ngay" button → POST `/edit-row` for all dirty rows. Removed the per-blur autosave (single source of truth = the timer + manual save).
- Per-row visual marker `origin-row-live-edited` highlights edited rows.

### HQ excel export (PR7 finalize)
- Copied legacy `tru lui CO Johnson.xlsm` to `data/local/hq-templates/tru-lui-co-template.xlsm` (29 MB, gitignored).
- Rewrote `create_hq_bang_ke_workbook`: load template, `wb.copy_worksheet(LVC_template)` per TP, fill header (A3 title, P7 product_code, K6 criterion, K9/L9 qty/unit, K11 FOB, etc.), wipe body rows 16-1585, write material rows + footer totals.
- Dropped untouched template sheets (EUR2, CTH-D, WOII, FORM B, PTN, PLX, FORM X) so the dossier export contains only generated TP tabs (`<seq><product_code>` per legacy macro).
- Per user spec: 1 sheet per TP. `hq_sheet_codes_for_product` returns a singleton set, priority EUR1 > LVC > RVC > CTSH > CTH.

### Dossier .zip export (PR7)
- `POST /clients/{c}/co-case/{cid}/export-dossier-zip` bundles uploaded chứng từ (under `chung-tu/<slot>/`), TKX/TKN summary as JSON, HQ workbook, README.txt with case metadata.

### TKX/TKN tab (PR6)
- Replaced "BCCT exports" tab with TKX (export declarations from invoice_matches) + TKN (import declarations from locked sheets' allocation_lines), each marked "Đã có" / "Cần bổ sung sang Data Hub".
- Helper `case_tkx_tkn_summary(case, invoice_matches, stock_rows)` exposed in case context.

### Async loading UX universal
- Patched `window.fetch` global → drives top progress bar via `beginAsync`/`endAsync` counter (try/finally guarantees release).
- Submit handler in capture phase marks the clicked button with `data-async-busy="1"` (per-button spinner). Cleared on `pageshow` (full nav or bfcache restore).
- Workflow tab links get a per-tab spinner on click + 8s safety-net auto-clear.
- Substitute modal shows "Đang lấy khuyến nghị cho ..." spinner immediately when fetch starts.

### "Chưa tính" default
- `attach_origin_sheet_states` default_status changed from `"calculated" if has_snapshot else "draft"` to `"draft"` always. Sheets only flip to "calculated" after explicit `/calculate` click.
- Three pre-existing tests (`test_co_case_export_workbook_contains_bom_snapshot_rows_from_origin_form`, `test_co_case_export_workbook_contains_origin_snapshot_metadata_from_web`, `test_co_case_origin_round_trips_multi_lot_allocation_to_export_workbook`) updated to call `/sheet/{code}/calculate` before `/export`.

### Case-create feedback
- Create POST sets cookie `co_case_just_created={case_id}` scoped to the new case URL (60s expiry); case page shows green `callout-success` "Đã tạo hồ sơ ..." with auto-dismiss + manual close button. Cookie cleared on dismiss.

### No-BOM TPs surfaced
- `hq_sheet_codes_for_product`-style: sheet tab gets red border + `⚠ no BOM` chip when `materials` list is empty; inside-sheet warning callout with link to `{data_hub_base_url}/clients/{c}/products/{code}`; picker `<select>` shows "❗ Chưa có BOM trên Data Hub".

### Performance fixes (multiple root causes)
- **uvicorn `--reload`**: was scanning full cwd including `data/` symlink (~GB) + 29MB xlsm template; healthz dropped from 52s → 2ms after `--reload-dir app`. `package.json` updated.
- **`source_summary` co_stock_row_count fallback**: was paginating ALL Johnson BCCT (65k rows) just to count `co_stock`; replaced with `int(summary.get("co_stock_row_count") or 0)` — accept 0 when Data Hub source-summary doesn't include it.
- **`co_case_source_context` empty-case shortcut**: returns minimal context (source_summary only) when shipment empty + no products; was paginating full materials + bcct on `/co-case/{id}` index even for fresh empty cases.
- **`/clients/{id}` workspace overview**: new `client_overview_context()` uses source-summary only (counts) instead of full source_workspace + bom_workspace pagination.
- **`invoice_lookup_payload` typeahead**: split into lightweight `invoice_matches_only(client, shipment)` — Data Hub mode uses indexed `invoice_matches` adapter (~300ms), file-store mode falls through to canonical `co_case_source_context` so warnings still surface.
- **`declaration_invoice_matches`**: Data Hub mode now uses indexed `invoice_matches` + `list_bcct(declaration_no=...)` instead of full pagination.
- **TTL cache `co_case_source_context_cached`**: 90s in-memory, LRU 32, fingerprint = client+case+shipment+product_count. `/origin` GET warms it so first substitute open after page render is instant.

### Tab restructure (PR1 confirmed)
- Workflow steps reordered to: Lô hàng / Chứng từ / Form&PSR (W.I.P) / Bảng kê C/O / TKX-TKN / Review-Xuất.
- Form & PSR tab gets a `callout-warning` "W.I.P" banner.
- Chứng từ tab now splits required (BL, Invoice, Packing) vs optional (Hợp đồng, Cam kết NCC, Quy trình SX, Khác); explicit note that TKX is NOT uploaded here (queried from Data Hub later).

## Decisions Made

- **Stock ledger goes to Postgres, no JSON fallback.** User explicitly said the app runs Postgres in prod; ledger silently no-ops when `BARRY_DATABASE_URL` unset so unit tests still pass without setup.
- **CO owns the ledger, Data Hub owns BCCT.** Per Data Hub `routes/api.py:332` docstring (`co_stock.lot_policy, allocation_code.* live in CO`), Data Hub deliberately does not own consumption tracking. CO ledger reads available_qty from BCCT, tracks used_qty/remaining_qty itself. The pending Data Hub `/bcct/by-codes` endpoint only solves the read-side performance problem, not the persistence-of-state problem.
- **Sheet default = "Chưa tính"**, never auto-mark calculated based on snapshot. Staff explicitly clicks "Tính bảng kê" — matches user's mental model of an audit-grade workflow.
- **One HQ excel sheet per TP per dossier** (not per criterion). `hq_sheet_codes_for_product` returns a singleton set with priority EUR1 > LVC > RVC > CTSH > CTH.
- **Async UX never blocks the page.** Removed earlier `body.case-tab-loading [data-co-case-shell] { opacity: 0.6; pointer-events: none }` overlay because user said "khác gì synchronous". Only the clicked control shows busy state; page stays interactive.
- **Lazy stock fetch** in substitute modal (separate `/substitute-stock` endpoint) — accepted that recommendations render before stock metadata, on the basis that score-based sort is what user evaluates first.
- **Don't change the create-case redirect URL.** Tests string-concat `{location}/origin`; instead set a short-lived cookie scoped to the new case URL to surface the toast.
- **Postgres connection via Unix socket peer auth** for local dev (`postgresql:///barry_co?host=/var/run/postgresql`) — no password to manage.
- **Heuristic HS-prefix mode** runs in CO when Data Hub returns 0 substitutes (not just on auth failure) — common when BOM uses an internal code that doesn't exist in catalog.

## What Didn't Work

- First attempt at the substitute modal full-paginated Data Hub catalog inside `co_case_origin_sheet_substitute_candidates` even after Bearer-aware substitutes shipped (because `co_case_source_context_cached` was being called for the stock_pool). Lazy-fetch split required.
- `Bearer dev` and `Bearer admin` both 401 against `/api/v1/.../substitutes` — Data Hub UI route checked session cookie only. Heuristic fallback was added to unblock the user; Data Hub team then shipped the Bearer-aware `/v1/hub/...` mirror within a day.
- Tried adding heuristic candidates by reading `material_rows` from the HEAVY full source_context fetch — that defeated the lazy-stock optimization. Refactored to use the catalog only when heuristic actually fires, and only after the Data Hub call returned empty.
- Setting `?created=1` on the create-case redirect broke `test_co_case_can_select_aggregate_bom_version_snapshot` because it string-concats `{created.headers['location']}/origin`. Switched to a short-lived cookie.
- Initial ledger test asserted `str(used.get(...)) == "5"` — Postgres `NUMERIC(20,6)` returns `Decimal("5.000000")`, so test compared as Decimal instead.
- `body.case-tab-loading [data-co-case-shell] { opacity: 0.6; pointer-events: none }` made the page feel synchronous. User pushed back: "khác gì synchronous". Removed.
- `kill 1421961 1421964 ...` blocked by sandbox classifier when targeting uvicorn processes started by another shell. Asked user to restart server manually.
- `psql` superuser enumeration also blocked by sandbox classifier — used Unix socket peer auth as user `vp` instead.
- The form-rebuild path on `/sheet/{code}/lock` strips `materials[*].allocation_lines` (because the AJAX submit only sends metadata fields, not the full allocation set). Worked around by capturing claims BEFORE `update_case_record` overwrites the disk record, AND by falling back to the persisted disk record in `_sheet_with_allocations`. Long-term: reading persisted state for the lock action would be cleaner than trusting the form.

## Open Items

- **Browser-test the cross-case ledger** end-to-end (task #11). Lock sheet in case A → confirm case B's substitute modal shows reduced `remaining_qty`; reopen → confirm restoration; concurrent lock from two tabs; overclaim flag.
- **Wait for Data Hub `/v1/hub/clients/{c}/bcct/by-codes`** (.ai/api-requests/2026-05-13-bcct-by-codes-lookup.md) to remove the first-call ~30s tax on substitute modal for big clients.
- **Form-rebuild allocation_lines wipe** on `/lock`: long-term fix is to read persisted state for the lock action rather than the form.
- **NVL origin classification config** (backlog #9): still all-non-origin-by-default; coordinate with Data Hub for `material_identity.origin_classification` source.
- **Currency NT ↔ VND swap actually wires through to display values** (per-sheet config persists, but JS doesn't yet swap cell values — needs FX rate + client calc). Today only `data-origin-currency-mode` attribute is set on the panel.
- **Build Up method** still WIP (PR2 spec mentioned it as "Build Down default, Build Up WIP"); origin form still uses Build Down only.
- **Unrelated dirty/untracked artifacts** from prior sessions left in worktree: `docs/co-form-index-confirmation.*`, `.ai/screenshots/...`, `.ai/sister-app-notes/2026-05-07-bom-presets-3b.md`, `.ai/sister-app-prompts/`. User should decide whether to include in the imminent commit.
- **Substitute modal stock UX**: now lazy, but if stock fetch errors out the rows show "0 tồn" forever. Add an explicit retry + "stock unavailable" indicator.
