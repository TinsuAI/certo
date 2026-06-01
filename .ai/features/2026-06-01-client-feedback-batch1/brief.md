# Fix Plan — Client Feedback Batch 1 (HIỆN TRẠNG BARRY CO)

Source: client PDF "HIỆN TRẠNG BARRY CO - Trang tính1" (2 pages, 6 items).
Date: 2026-06-01. All 6 items triaged against code; all valid.

## Triage summary

| # | Feedback | Status | Owner |
|---|----------|--------|-------|
| 1 | Chưa có mục xóa hồ sơ | Valid — permission gap | CO (config) |
| 2 | Bước "mở" load hơi lâu | Already fixed prior session | — (confirm w/ client) |
| 3 | Thỉnh thoảng lỗi, không đề xuất được NVL thay thế | Valid — empty/error fallback | CO |
| 4 | Mã NVL thay thế chưa phù hợp | DH request pending client examples; CO heuristic dropped (see note) | DH (request) |
| 5 | Muốn nhiều bộ lọc cùng lúc (mã + tên) | DONE (fuzzy modal search) | CO |
| 6 | Muốn chọn nhiều dòng để thao tác hàng loạt (xóa…) | DONE — bảng kê (origin sheet) bulk row delete | CO |

Decisions taken (user, 2026-06-01):
- #1: add `manager` to delete roles.
- #4: file a Data Hub API request for substitute-ranking quality, plus improve CO-side fallback.
- Scope: full plan for all 6.

---

## STATUS (2026-06-01)
- **#1 — DONE** (code). `DEFAULT_CO_CASE_DELETE_ROLES` now includes `manager`
  (`data_hub_settings.py:13`). Test: `test_can_delete_co_cases_allows_manager_by_default`.
- **#6 — DONE** (code), target = **bảng kê (origin sheet) row delete**, NOT the dossier
  list. Use case (client): after Load BOM, the sheet has NVL rows with no CO stock / not in
  BCCT — they want to delete many at once. Added per-row checkbox (STT cell) + per-sheet
  select-all (thead) + a **"Chọn dòng không có tồn/BCCT"** quick-select + a bulk-action bar
  (`co_case.html`), all gated to unlocked sheets. Quick-select targets rows with
  `data-row-no-stock="1"` (= `allocation_count == 0`, i.e. no CO-stock lot matched from
  BCCT). Delete **reuses the existing staged-delete path**: extracted `stageRowDeletion()`
  (shared by the substitute modal's "Xoá dòng này" and bulk), marks rows struck-through +
  records `pendingOps.deletes`, then the single **"Lưu bảng kê"** persists — no new server
  endpoint, lock/claims semantics unchanged. CSS resets the global `input{width:100%}` on
  the checkboxes + `.origin-bulk-bar[hidden]` so the bar hides. Test:
  `test_origin_sheet_renders_bulk_row_select_controls`. **Browser-verified** on real
  growatt-vn case `SD00.0010600` (128 rows, 125 with tồn / 3 without): quick-select picks
  exactly the 3 no-BCCT rows, bulk-delete strikes them + raises the dirty banner, 0 console
  errors (staged only, not saved → real data untouched). Screenshots in
  `.ai/screenshots/bangke-bulk-delete/`.
  - **Note:** earlier mis-built on the dossier list — reverted entirely per client.
- **#3 — DONE** (code), reframed after review. Root cause was deeper than "retry DH":
  `/substitute-stock` re-derived CO stock from BCCT live via `list_bcct_by_codes` (the
  flaky dependency). Substitute feasibility (đủ tồn? / ΔLVC) only needs CO stock lots —
  computed client-side in `computeFeasibility`/`renderFeasibilityCell`
  (`co_case.html:3155-3245`). Fix: read candidate stock from the **materialized CO-stock
  snapshot** (`co_stock_materializer.read_co_stock_rows_cached`), case-allocated, no DH
  BCCT round-trip; snapshot is authoritative (missing code = no tồn). Response carries
  `stock_refreshed_at` → modal shows freshness marker. File-store/CI (empty snapshot)
  still falls back to source-context. Test:
  `test_substitute_stock_reads_materialized_snapshot_not_bcct` (asserts BCCT is never
  called). Full suite 405 passed + 8 skipped.
  - **Verify needed on demo:** snapshot path only activates in Postgres mode; local
    file-store keeps the fallback (freshness label hidden, `last_refresh_at` = "").

## #1 — Xóa hồ sơ visible to managers

**Root cause:** Feature exists (`co_case.html:405-410`, route `main.py:6155`,
`delete_case_record` in `co_case_store.py:210-251` with release-claims guard +
completed/lock block). Button gated by `co_auth.can_delete_co_cases`
(`co_auth.py:215-218`) → roles from `CO_CASE_DELETE_ROLES`, default `("dev","admin")`
(`data_hub_settings.py:13`). Manager testers can't see it.

**Fix (config-only):**
- Prod `.env`: `CO_CASE_DELETE_ROLES=dev,admin,manager`.
- No code change needed; existing guards (release-claims confirm, block-when-completed,
  origin-lock block) still apply and protect against accidental destructive delete.

**Optional hardening (decide later):** keep default at `dev,admin` in code; rely on env
override so policy stays per-deployment.

**Verify:** log in as `claude-check@local` (manager, growatt-vn+johnson-vn) → dossier list
shows "Xoá" → delete a throwaway dossier; confirm claims-release path + block reasons.

**Effort:** XS (env + redeploy + manual check).

---

## #2 — "Mở" load slow — ALREADY DONE

Addressed in prior sessions (see STATUS.md):
- Case-detail load: `skip_heavy_context` ~21s → ~1.5–3.6s (`d28e237`).
- BOM workspace: parallel fetch + DH batch endpoint (64ms vs ~10.4s).
- DH↔CO internal network (~8x latency cut).
- Origin tab: snapshot + narrow BCCT (cold ~1.47s).

**Action:** no new code. Confirm with client whether current build still feels slow on a
specific step; if yes, capture which step + client + timing before any further work
(measure, don't blind-optimize).

---

## #3 — Substitute: intermittent error / no suggestions

**Root cause** (`main.py:6949-7091`):
- `list_material_substitutes` wrapped in bare `except` → on any DH failure sets
  `source="error"` (`6993-6995`).
- Heuristic fallback only runs when DH returns empty (`7017`); if seed material absent
  from catalog → `compute_substitute_heuristic_candidates` returns `[]` → user sees
  **zero candidates** + raw error string. DH transient errors = "thỉnh thoảng".

**Fix (CO-side):**
1. **Retry transient DH calls:** add a short bounded retry (1 retry, ~300ms backoff) for
   `list_material_substitutes` on timeout/5xx in `data_hub_client.py` /
   `portfolio_service`, so a single network blip doesn't surface as zero results.
2. **Never silent-empty:** when both DH and heuristic yield nothing, always fall back to
   the `search`-tab path seeded from the material's own name/HS so the modal still shows
   *something* + a clear, friendly message (not a raw exception string).
3. **User-facing message cleanup:** map error kinds to short VI messages
   ("Data Hub tạm thời không phản hồi, đang dùng gợi ý nội bộ") instead of `str(exc)`.
4. **Distinguish states** in the JSON: `candidates_source` ∈
   {data_hub, co_heuristic, co_search_fallback, error} so the UI can label provenance.

**Files:** `app/main.py:6985-7091`, `app/data_hub_client.py` (retry),
`app/portfolio.py` (wrapper). Tests: extend `tests/` substitute coverage —
DH-timeout → retry → heuristic; DH-error + empty-heuristic → search fallback non-empty;
message mapping.

**Effort:** M.

---

## #4 — Substitute suggestions "chưa phù hợp"

Two layers:

**(a) Data Hub (primary) — file API request.**
CO is a consumer; ranking quality (`combined_score`) is DH-precomputed. Create
`.ai/api-requests/2026-06-01-substitute-ranking-quality.md` from
`.ai/templates/data-hub-api-request.md`, covering:
- Use case + observed bad suggestions (collect 3-5 concrete material codes from client).
- Gap: HS-prefix dominates; missing signals (name/spec similarity, category, unit,
  supplier, actual substitution history).
- Proposed response: richer `raw_scores` breakdown + min-quality threshold + reason codes.
- Provider tests DH must add. **Stop and get DH contract approval before consuming.**

**(b) CO fallback heuristic (interim) — DROPPED (decision 2026-06-01).**
Improving `compute_substitute_heuristic_candidates` was prototyped (multi-signal +
reason chips) but **reverted**: the heuristic only fires when DH returns *no* precomputed
substitute for a code, and in practice DH covers all real materials — the codes DH misses
are junk components (no HS, no usable name), so the path almost never yields a useful
suggestion. Effort there is wasted; the real lever is **(a) DH-side ranking quality**.
Original intent (kept for reference if ever revisited):
- Add token/name similarity + category match + unit match as weighted signals.
- Keep HS-prefix but down-weight when it's the only signal.
- Surface why each candidate was suggested (reason chips) so users can judge fit.

**Files:** `.ai/api-requests/…` (new), `app/main.py:7218+`, tests for scoring.
**Effort:** DH request S (CO); CO heuristic M. **Blocked on collecting real bad-examples
from client.**

---

## #5 — Multiple simultaneous filters (mã + tên)

**Root cause:** `_advanced_table.html:5-7` exposes one cross-field search box (`q`,
substring over searchable fields) + single-select dropdown filters
(`table_view.py:140-161`) that are exact-match AND-combined (`:40-48`). No way to
free-text filter `mã` AND `tên` independently at once.

**Fix:** extend the shared table component to support **text filters** alongside select
filters:
- `table_view.normalize_filter`: add `kind: "text"` (substring on a specific field) vs
  current `kind: "select"`; matching logic at `:40-48` branches on kind.
- `_advanced_table.html:8-17`: render `<input type=search>` for text filters,
  `<select>` for select filters.
- Per-screen: declare desired field filters (e.g. `code`, `name`) where useful —
  candidates: `catalog_table.html`, `bom.html` (the tables in the screenshots).
- All text filters AND-combined, in addition to the global `q`.

**Files:** `app/table_view.py`, `app/templates/_advanced_table.html`, the route(s) that
build filter defs (e.g. `main.py:5353-5370` catalog). Tests: `table_view` multi-text
filter intersection.

**Effort:** M. Shared component → benefits all 5 tables (bcct, catalog, co_stock,
customs_exchange_rates, bom).

---

## #6 — Multi-row select + bulk action

**Root cause:** no checkbox column / select-all / bulk action anywhere
(`_advanced_table.html`). All ops per-row.

**Fix (phased):**
1. **Component:** optional checkbox column + select-all + a sticky bulk-action bar in
   `_advanced_table.html`, enabled per-table via a flag (`selectable=True`,
   `bulk_actions=[…]`). Selection state + bar in a small JS module (likely
   `app/static/`).
2. **First bulk action = delete**, scoped to the table where it's safe and requested.
   Confirm with client which table they meant (screenshots suggest BOM/origin-sheet rows
   or the dossier list). Reuse existing per-row delete endpoints via a batch wrapper, OR
   add a bulk endpoint that loops the existing guarded single-delete (so claims/lock
   guards still fire per item, partial-failure reporting).
3. **Guardrails:** confirmation modal listing count + names; respect existing
   block-reasons per row; report which succeeded/failed.

**Files:** `_advanced_table.html`, `app/static/` JS, target template + route, new bulk
endpoint, tests (bulk delete with mixed allowed/blocked rows).

**Effort:** M–L. Needs client confirmation on target table before build.

---

## Sequencing

1. **#1** (XS, config) — ship immediately.
2. **#2** — none; confirm w/ client.
3. **#3** (M) — substitute robustness; high user-visible value.
4. **#5** (M) — multi-filter; shared component win.
5. **#4** (M + DH request) — needs real bad-examples from client; file DH request in
   parallel.
6. **#6** (M–L) — bulk select; needs target-table confirmation.

## Open inputs needed from client
- #4: 3-5 concrete "wrong" substitute examples (material codes + expected).
- #6: which table(s) need bulk select/delete.
- #2: still slow anywhere? which step?
