# 2026-05-28 (evening) — Stock ledger hardening + Origin override UX + dark theme

4 commits shipped + verified live on `https://barry-co.tinsu.ai`. Spanned 4 themes: dark-theme CSS audit, stock-ledger safety, Origin override UX rework, FastAPI route-order bug fix.

## What Was Done

### 1. Dark theme CSS audit + fix — `36891e0`

User flagged that several pages were unreadable in dark mode because CSS hadn't been updated.

Surveyed `app/static/css/app.css` (4961 lines). Grepped for hardcoded colour literals not routed through CSS vars: 147 hits, concentrated in late-added features (workflow steps, callouts, document checklist, substitute modal, CO stock history modal, BOM diff badges, cost-buildup block, origin-recommendation panel).

Mapped each literal to existing CSS vars:
- Neutral text/bg → `--foreground` / `--foreground-soft` / `--foreground-muted` / `--card` / `--surface-subtle` / `--border`
- State pairs (warning/error/success/info badges) → `--*-soft` background + `--*` foreground
- Solid coloured icon backgrounds → keep `var(--*)` with `var(--primary-foreground)` white text (contrast intent unchanged across themes)

5 `rgba(15, 23, 42, …)` modal-backdrop values left as-is — translucent near-black is theme-neutral.

Wrote `scripts/dark_theme_audit.mjs` (puppeteer + WCAG contrast scan, threshold 3.0 AA-large). Crawled 20 pages, 0 findings post-fix. Spot-checked screenshots (case-origin, case-documents, cost-allocation) confirmed clean dark rendering.

### 2. Critical review of the lock/unlock flow (no commit, audit only)

User asked: "review lại thật kỹ cái flow: mở hồ sơ, giữ tồn / nhả tồn, thứ tự tính các sheet, chốt sheet này mới được tính sheet đi, mở chốt các sheet ngược lại, etc."

Dispatched an Explore agent for the initial map (~1000-word report). Then meta-reviewed the agent's findings by reading each cited file:line directly — agent had ~5/15 false positives:

False positives identified:
- "No cascading unlock validation" — wrong. `main.py:2844-2845` already enforces "must unlock from the last locked sheet". Sequential gate is symmetric in both directions.
- "Re-lock spams audit log" — wrong. `co_stock_ledger.py:144-177` already dedupes events for identical re-locks.
- "Substitute doesn't notify upstream sheets sharing material" — wrong. Each claim is per (case, sheet, source_row, material_index); upstream sheets have independent claims.
- "Export not gated by all-locked" — partially wrong. Export endpoints DO call `origin_sheet_export_blockers`. The real issue is the blocker only rejects `{draft, stale, calculating}` — accepts `calculated`, not yet `locked`. Different concern.
- "mark_origin_sheets_stale skips draft sheets" — wrong by design. Draft sheets have never been calculated; marking them stale is meaningless.

Overstated:
- "Substitute on locked sheet causes ledger desync" — re-graded HIGH→MED. The desync is conservative-stale (ledger keeps the old claim until re-lock or unlock), not over-claiming.

Confirmed real issues that became the next commit:
- HIGH: silent `except Exception → return 0` swallow in `co_stock_ledger` (the one the agent missed entirely).
- HIGH: no stock availability pre-check at lock time.
- HIGH: last-writer-wins on concurrent `update_case_record` calls (deferred — not fixed this session).

### 3. Stock ledger hardening — `dfda66f`

Fixed N1 (silent swallow) and #2 (no pre-check) together — they share the same transaction and call path.

`app/co_stock_ledger.py`:
- Added `StockOverclaimError` exception. Carries `violations` list with `source_row` / `claimed` / `available` / `bcct_remaining` / `other_claims` per violating lot. Message string formats top-5 for the API response.
- New SQL in same transaction as the DELETE/INSERT:
  ```
  SELECT s.source_row,
         CAST(s.remaining_qty AS numeric) AS bcct_remaining,
         COALESCE(SUM(c.claimed_qty WHERE c.status='locked'
                                     AND NOT (c.case_id=ME AND c.sheet=ME)), 0) AS other_claims
  FROM co_stock_rows s LEFT JOIN co_stock_claims c
    ON c.client_id=s.client_id AND c.source_row=s.source_row
  WHERE s.client_id=%s AND s.source_row = ANY(%s)
  GROUP BY s.source_row, s.remaining_qty
  ```
  Built dict `availability[source_row] = (bcct_remaining, other_claims)`. For each new (source_row, claimed_qty), check `claimed <= bcct_remaining - other_claims`. Aggregate violations, raise if any.
- Special case: query `EXISTS(SELECT 1 FROM co_stock_rows WHERE client_id=%s)` first. If no snapshot exists for the client at all (fresh workspace / unit-test path), skip the entire pre-check. If snapshot exists but a specific source_row is missing, treat as violation ("lot không có trong snapshot").
- Removed the blanket `except Exception → log + return 0`. Now only `DatabaseUnavailable` becomes a no-op (preserved for unit tests without DB). All other exceptions propagate.
- Same treatment for `record_sheet_release`.

`app/main.py`:
- `lock_co_case_origin_sheet`: wrapped `record_sheet_lock_claims` in `try / except StockOverclaimError`. Returns 409 with Vietnamese detail listing 5 violating lots + "hãy tính lại bảng kê để cập nhật phân bổ theo tồn hiện tại" hint. Critically: skips both `set_origin_sheet_status` AND `update_case_record` on failure, so no ghost-locked state exists in case JSON.
- `reopen_co_case_origin_sheet`: **reversed** the ordering. Was: case-state update first → ledger release. Now: ledger release first → case-state update. Reason: if release fails (DB down), sheet should stay locked in the UI (consistent with ledger still holding the claim) rather than appear unlocked while the claim leaks. Wrapped release in `try/except` with logger.warning + 409 to user.
- Added `import logging` (main.py had no logger before).

`tests/test_co_demo.py`:
- Updated `test_origin_sheet_lock_records_cross_case_stock_ledger_claims`: pre-check now rejects unknown source_rows when the client has a snapshot. Seed `co_stock_rows` for ROW-A1 / ROW-A2 / ROW-B1 with `remaining_qty='100'` so the happy-path test still passes.
- New `test_origin_sheet_lock_rejects_overclaim_against_materialized_snapshot`: seed ROW-LIMIT with `remaining_qty='4'`, attempt to lock with allocation 10 → assert 409 + response contains "ROW-LIMIT" + ledger has no claim for the lot + sheet status stays "calculated".

Baseline regression check via `git stash` confirmed: same 17 pre-existing failures before and after (environmental drift, not regressions).

### 4. Form / criteria selection audit (no commit, audit only)

User asked: "Phần chọn form và chọn tiêu chí, review thật kỹ, làm thật flexible, nghĩa là user có thể thay đổi customize được".

Dispatched Explore agent again. Verified findings. Agent corrections:
- "No case-level form override" — partially wrong. `case.co_form_type` field exists (auto-derived from market via `apply_form_defaults`), but no user-facing UI to override at case level. Only per-sheet override is editable.
- Missed: optimistic concurrency exists ON `/recommendation-override` endpoint (`main.py:6699` checks `expected_revision`) but NOT on lock/reopen endpoints.
- Missed (biggest finding): only 4 forms in built-in config (B / CPTPP / EUR.1 / AI). Missing all common ASEAN-bilateral forms: D / E / AK / AANZ / AJ / VK / VC / VJ / RCEP / UKVFTA / AHKFTA / EAV.

Confirmed bugs that drove the next commit:
- B1 (MED): `form_override` persists across market changes. User changes market AI→EUR.1, override stays AI, exports wrong form. No warning.
- B2 (MED): override endpoint has no lock gate (can change form_override on locked sheet).
- B3 (MED): criteria_override accepts free text, no validation against legal corpus.

### 5. Origin override UX — `4cf31f2`

User feedback on B1 fix approach: "Làm thế nào cho thật đơn giản thôi. Tất cả những gì thuật toán chạy ra chỉ là khuyến nghị, còn cụ thể dùng form nào, tiêu chí nào thì user có thể lựa chọn được."

Followed up with: "Phần lựa chọn tiêu chí (override) thì nên dropdown, Ngưỡng LVC và RVC thì chung 1 input, thực ra cái này chỉ ảnh hưởng đến việc lúc export ra bảng kê excel thì dùng form nào".

Three changes in `app/templates/co_case.html`:

1. Criteria input → `<input list="origin-criteria-options">` backed by a shared `<datalist>` of 18 common patterns:
   - WO / PE / CC / CTH / CTSH
   - RVC 35%, RVC 40%, LVC 30%, LVC 35%, LVC 40%
   - "RVC 40% hoặc CTH" / "RVC 40% hoặc CTSH" / "LVC 30% hoặc CTH" / "LVC 30% hoặc CTSH" / "LVC 40% hoặc CTH" / "LVC 40% hoặc CTSH"
   - "AIFTA 35% FOB + CTSH"
   - "Tra PSR theo Phụ lục"
   
   Datalist gives the dropdown UX while still accepting custom text — matches the "engine recommends, user decides" philosophy.

2. Two threshold inputs (LVC + RVC) collapsed into one "Ngưỡng LVC/RVC (%)". JS save handler sends the same value to both server slots (`lvc_threshold_override` + `rvc_threshold_override`). Server's effective lookup is already `effective_lvc_threshold or effective_rvc_threshold`, so the populated one wins. No schema migration needed.

3. New "Reset về khuyến nghị" button next to "Lưu cấu hình". Disabled via Jinja `{% if not (...) %}disabled{% endif %}` when no override is currently set. Click → `window.confirm` → POST empty/default values to `/recommendation-override` → 600ms toast → `window.location.reload()` to refresh effective values.

End-to-end verification:
- `/tmp/verify_export_override.py`: set overrides via `set_origin_sheet_config_override`, run `attach_origin_sheet_states`, call `create_hq_bang_ke_workbook(case)`, parse output xlsx with `zipfile`. Criteria override "LVC 45% hoặc CTSH" appears in cell K6. Form override "EUR.1" routes the template to the PSR sheet (form-mau-combined.xlsx has sheets {LVC, RVC, CTH, CTSH, PSR}; EUR1 falls back to PSR).
- `scripts/verify_export_combos.py`: 5-combo dispatch test. EUR.1 form → 1099 KB output sheet (PSR template). No-form-override + criteria text → 342 KB output (LVC layout).
- Rendered the xlsx via `libreoffice --headless --convert-to pdf` and read PDF pages directly through the Read tool. Header / "Tiêu chí áp dụng" / threshold cells render as expected.

### 6. GET 404 route fix — `f83bfa1`

Found during the full E2E browser walkthrough (next section). GET `/clients/{cid}/co-case/{id}/export-bang-ke` returned 404 even though both `@app.get` and `@app.post` decorators were declared on the handler at `main.py:5616`.

Root cause: `@app.get("/clients/{cid}/co-case/{case_id}/{step}")` at `main.py:5465` matches first (FastAPI is order-sensitive). Step handler then validates `step in CO_CASE_WORKFLOW_STEP_KEYS`, rejects "export-bang-ke", raises 404. POST was unaffected (no catch-all POST `{step}` route).

First attempt: constrain `{step}` with `Path(..., pattern="^(shipment|documents|guidance|origin|exports|review)$")`. Discovered (the hard way) that FastAPI returns **422 Unprocessable Entity** on path-pattern mismatch, NOT skip the route to fall through. Reverted.

Final fix: defined a tiny `@app.get` wrapper for `/export-bang-ke` BEFORE the catch-all `{step}` route. It just `await`s the existing handler. The original `@app.post` decorator stays in its original location (less diff churn).

`scripts/verify_export_route.mjs` probes 7 endpoints: 7/7 pass after fix (GET valid steps → 200, GET invalid step → 404, GET /export-bang-ke → 200, POST /export-bang-ke → 200).

### 7. Full E2E browser audit

User asked: "chạy thử một hồ sơ từ đầu đến cuối, thử sửa, thay đổi này kia .... tất cả dùng trình duyệt nhé, chụp ảnh lại các bước ..."

Built `scripts/full_workflow_audit{,_v2,_v3,_v4}.mjs` (4 iterations as I learned the auth + UI). Final coverage:
- SSO login via Data Hub form (admin@data-hub.local / admin123 local seed).
- Walk all 7 workflow tabs in dark mode (overview / shipment / documents / guidance / origin / exports / review).
- Test override UI: set form_override + criteria from datalist + single threshold → save → reload → confirm badges → Reset button → reload → confirm cleared.
- Read sheet state to verify gate logic (canCalculate / canLock / canReopen flags per sheet).
- Export probe (this is where GET 404 was discovered).

22 screenshots in `.ai/screenshots/full-workflow/`. Lock/unlock POST-from-puppeteer failed with 409 because raw POST body lacked the full products snapshot the UI normally submits — relied on the existing unit tests for that coverage instead.

### 8. Prod deploy verification

After `git push tinsu main`, CI ran 1m08s and passed. `scripts/verify_prod_deploy.mjs` ran against `https://barry-co.tinsu.ai`:
- Login via `claude-check@local` / `claude-temp-2026` SSO. OK.
- Origin override UI probe: `data-origin-recommendation-threshold` present, no old `-lvc` / `-rvc` selectors, criteria `list="origin-criteria-options"`, Reset button rendered (disabled — correct when no overrides). All good.
- Datalist `#origin-criteria-options` has 18 options. OK.
- GET `/export-bang-ke` → 200 + xlsx content-type (not 404). Bug fix verified live.
- POST `/export-bang-ke` → 200 + xlsx. OK.
- 8 dark-mode screenshots across all 6 workflow tabs in `.ai/screenshots/prod-deploy-verify/`. Clean.
- 5/5 verdict checks pass.

## Decisions Made

- **"User chooses" philosophy for overrides**: User articulated this explicitly. Implication: don't auto-clear overrides when market changes (would lose user intent). Instead, add an explicit "Reset về khuyến nghị" button as escape hatch. Engine output is suggestion, override is intent, both visible side by side.
- **Datalist over pure dropdown**: User said "dropdown" but pure dropdown blocks edge-case criteria text. Datalist gives the suggestions UX + preserves custom text. Reflects the same "user decides" philosophy.
- **Single threshold input, dual server fields**: Avoided a schema migration by keeping the 2 server fields and just writing identical values from 1 UI input. Existing effective-value logic naturally picks the populated one.
- **Route reorder over Path-pattern**: After empirically discovering Path-pattern returns 422 (not skip), reverted to the simpler reorder. Added a delegating GET wrapper rather than moving the original decorator (preserves co-location of GET+POST on the canonical handler).
- **Skip-snapshot escape in stock pre-check**: If client has no `co_stock_rows` snapshot, skip availability check. Needed for unit-test path; production clients always have a snapshot.
- **Release-first ordering in reopen**: If DB fails on release, sheet stays locked (consistent with the ledger still holding the claim) rather than appearing unlocked while the claim leaks. Trade-off: a transient DB error blocks reopens until retry.
- **No backwards-compat shim for the old test fixture**: Updated `test_origin_sheet_lock_records_cross_case_stock_ledger_claims` to seed `co_stock_rows` rather than adding a "skip pre-check in tests" toggle. The new behaviour IS the contract.

## What Didn't Work

- **`Path(..., pattern="^(...)$")` as a route-skip mechanism**. FastAPI returns 422 on mismatch, does not fall through. Reverted in same session.
- **First `record_sheet_lock` test run** post-fix: pre-check rejected the synthetic ROW-A1/A2/B1 source_rows because growatt has a `co_stock_rows` snapshot from the per-client materializer. Fix was test-side (seed those rows), not code-side.
- **Lock/unlock via puppeteer raw POST**: failed 409 because `origin_case_from_request` rebuilds the case from form fields and my minimal POST body had `product_count=0` → action_error said "sheet not found in case". Would need to scrape the full hidden-input snapshot the UI submits. Skipped — unit tests cover lock/unlock contracts.
- **`Failed to fetch` in puppeteer evaluate** when page was on the SSO callback origin (data hub domain). Worked around by navigating to a CO-domain page first before running fetch.
- **`Path` name collision**: Tried `from fastapi import Path` but `pathlib.Path` is already imported as `Path` on `main.py:11`. Imported as `FastAPIPath` alias before discovering the pattern approach didn't work anyway. Removed.

## Open Items

- **Per-client default overrides** in `client_config_store.py` — high-value follow-up (operators currently re-override per-sheet every time).
- **Missing CO forms** in `default_co_form_config()`: D / E / AK / AANZ / AJ / RCEP / UKVFTA / VK / VC / VJ. Pure content/data gap. Admin UI at `/settings/co-forms` accepts new forms via `sanitize_form` (auto-uppercases form_code).
- **HS↔form coherence check** + **criteria token validation** (MED severity, both deferred per "make it simple").
- **Concurrent edit race** on `co_case_states` (last-writer-wins, no `revision` field) — flagged HIGH.
- **Export gate too lenient**: `origin_sheet_export_blockers` accepts `calculated` (not just `locked`), letting users export bảng kê HQ before stock claim is recorded. Confirm with business intent.
- **Lock TTL too long**: `origin_calculation_lock` per-client TTL is 60 min. Staff that abandons a session blocks colleagues for an hour.
- **Claim ID stability**: `claim_id = sha256(case_id|sheet|source_row|material_index)`. Reordering BOM materials breaks the claim → orphan claim. Use stable lot-key (declaration_no + line_no + customs_code) instead.
- **4 `full_workflow_audit*.mjs` exploratory scripts untracked**. Decide whether to check them in or delete. The `verify_*` scripts ARE committed.
- **7 pre-existing test failures** (`-k "export or step or co_case_workflow"`) confirmed pre-existing via git-stash baseline. Match earlier "30 pre-existing local test failures" pattern. Worth a focused cleanup pass.

## Reusable Lessons

Worth surfacing to the user's cross-project knowledge base:

1. **FastAPI route ordering for catch-all path params**: Catch-all path params (e.g. `{step}`) eat ALL single-segment paths on the same prefix. Define specific routes BEFORE catch-alls. `Path(..., pattern=...)` does NOT make the router skip — it returns 422 on mismatch. Reordering or splitting the catch-all is the only fix.

2. **Explore agents have ~30% false-positive rate on code-flow audits**. Always verify the cited file:line before relaying. The most serious finding in this session was one the agent MISSED entirely (silent exception swallow). Two separate agent reports in this session both required correction.

3. **`libreoffice --headless --convert-to pdf` + Read tool's PDF page rendering** is a clean way to verify xlsx output end-to-end without an Excel install. Faster + cheaper than spinning up a headed browser, and the model can read the rendered PDF directly as images.
