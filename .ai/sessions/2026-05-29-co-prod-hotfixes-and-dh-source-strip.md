# 2026-05-29 — CO prod hotfixes + DH source-view strip

Second session this day (first: state-machine + gap rule).
8 commits, all pushed to `tinsu/main` and deployed to demo.
374 tests passing locally.

## What Was Done

### Housekeeping (3 commits)
- `1b034a8` — committed Phase-3 audits (`2026-05-28-bom-picker-filter-audit.md`,
  `2026-05-28-case-sheet-stock-state-machine.md`) and recent session logs
  (this morning's state-machine handoff + prior orphan demo-verify log).
- `f161f7e` — tracked 4 perf/verify scripts under `scripts/`
  (`screenshot_cost_buildup.mjs`, `time_load_bom.mjs`,
  `verify_load_bom_local.mjs`, `verify_state_machine_local.mjs`);
  dropped 5 superseded one-offs (`full_workflow_audit{,_v2,_v3,_v4}.mjs`
  rolled into the state-machine smoke, `verify_prod_deploy.mjs` was a
  single-use post-deploy probe).
- `38cb100` — dropped `PostgresCoCaseStateStore.acquire_client_lock` /
  `release_client_lock`. Zero callers left after Phase 3.2 final replaced
  the per-client `pg_advisory_lock` with per-case optimistic concurrency
  on `co_cases.revision`.

### Hotfix #1 — EUR.1 bảng kê always picked PSR template (`acb201e`)
**Symptom**: operator picks LVC/CTH/etc. in the criteria override, but the
HQ workbook ships sheet titled `BẢNG KÊ KHAI HÀNG HÓA XUẤT KHẨU ĐẠT TIÊU
CHÍ "PSR"` with the wide PSR layout, no LVC cost-allocation section,
"Hàng hóa đáp ứng tiêu chí PSR" conclusion.

**Root cause** in `app/workbook_io.py` `hq_sheet_codes_for_product`:
```python
form = ...origin_sheet_effective_form_code...
if form == "EUR.1" or "EUR.1" in form:
    return {"EUR1"}   # ⬅ short-circuit BEFORE reading criteria_override
```
`{"EUR1"}` then gets rewritten to `{"PSR"}` because the form-mau template
workbook has no sheet named `EUR1`. Every EVFTA case shipped the PSR
template regardless of the operator's criterion choice.

**Fix**: move the EUR.1 fallback AFTER the criterion-precedence chain.
Explicit overrides (LVC/CTH/RVC/CTSH/PSR) now win for ANY form, including
EUR.1. EUR.1 → EUR1 fallback only fires when none of the precedence keys
matches a known criterion — preserves the Phụ-lục-VII default for cases
the operator hasn't touched.

**Verified live** against `johnson-vn co-case-4e9f5a3b1e9c MAS1230-39`
(`form=EUR.1`, `override=LVC 30%`): workbook sheet title now
`BẢNG TÍNH HÀM LƯỢNG ... ĐẠT TIÊU CHÍ "LVC"` with the LVC compact
layout. 7 unit tests in `tests/test_hq_sheet_codes.py`.

### Hotfix #2 — Dossier ZIP exported with incomplete TKN list (`897c9a5`)
**Symptom**: `case_tkx_tkn_summary` filters TKN rows to sheets in
`origin_sheet_status == "locked"` (`app/main.py:1556`). The dossier
export gate (`origin_sheet_export_blockers`) only blocked sheets in
`draft/stale/calculating`. A `calculated` sheet (not yet locked) passed
the gate but its TKN demand was silently dropped from the summary —
operators shipped dossiers whose TKN list omitted declarations the case
actually referenced.

**Fix**: `/export-dossier-zip` now requires `co_case_is_completed(case)`.
Since `/close` itself enforces all sheets locked, this implicitly
guarantees the TKN summary is complete by construction. Error 409 with
either of two messages depending on cause:
- Some sheets unlocked → "Còn N bảng kê chưa chốt: …"
- All locked but case still open → "Đóng hồ sơ trước khi xuất file
  tổng hợp"

Per-product `/export-bang-ke` (WIP Excel) keeps its existing looser gate.

**UX**: Review tab swaps action precedence based on case state:
- open → PRIMARY = "Đóng hồ sơ", SECONDARY = disabled "Xuất .zip" with
  state-aware hint (no products / N sheets unlocked / close to finalize).
- closed → PRIMARY = "Xuất .zip", SECONDARY = "Mở lại hồ sơ".

4 tests: bundled (closed), direct (open), all-locked-but-open 409,
partial-locks 409. Verified live on local: 11/11 UI assertions pass.

### Hotfix #3 — Propose-BOM định mức blank on Data Hub (`a52f3c6`)
**Symptom**: operator clicks Propose BOM after sheet lock + overrides;
DH reviewer UI shows the proposal but the định mức (qty) column is blank;
clients in `bom_proposal_mode=auto` get the proposal auto-rejected with
`qty_delta_exceeds_tolerance` for every kept material.

**Root cause**: `build_bom_proposal_rows` shipped rows with key
`norm_per_unit`. Data Hub's BOM row contract uses `qty_per_unit`:
- `normalized_hash` reads `r.get("qty_per_unit") or 0` → hash collisions.
- `_auto_evaluate` compares proposed qty=0 against parent → 100% delta →
  fails tolerance for every material.
- `create_artifact` would also error via `chk_qty_per_unit_positive` if
  approval ever materialized.
- Manual-mode (johnson-vn) → pending but reviewer sees blank qty cell.

**Confirmed via live DB**:
`hub.bom_change_requests prop_jFyrYHqEFQrUplj4` (johnson-vn MAS1230-39,
status=rejected) had `rows_payload [{"norm_per_unit": "2", ...}, ...]`
with no `qty_per_unit`.

**Fix**: translate at the boundary. CO-internal overrides keep the
operator-facing `norm_per_unit` (định mức) key; `build_bom_proposal_rows`
maps to `qty_per_unit` when shaping the DH request. Both edit/substitute
path and add-row path fixed. Test asserts `row["qty_per_unit"] == "2"`
AND `"norm_per_unit" not in row`.

### Source-view strip (`2508ae7`, `922d6bb`)
**Why**: catalog (materials + products), BOM, BCCT and `/config` are
Data Hub-owned source data. CO was re-rendering full paginated tables
for each on every visit — `source_workspace_for_client` paginates the
DH material catalog + product catalog + entire BCCT (Johnson: 65k+ rows)
over HTTP per render. Operators don't need a second UI for these on the
CO side; DH's UI is canonical and richer (upload, preview, lineage).

**Change**: when `source_backend == "data-hub"`, the 7 affected routes
render a summary card + "Mở trên Data Hub →" button to the matching DH
page. Lean context `_data_hub_overview_context()` pulls only counts +
client_config from `portfolio_service.source_summary` — same pattern
as the existing `_co_stock_lean_client_context`. Local-mode (non-DH)
retains the full UI so dev/test workflows still work; branch lives in
context functions + templates.

Affected routes:
- `/clients/{id}/catalog`
- `/clients/{id}/catalog/materials`, `/clients/{id}/catalog/products`
- `/clients/{id}/bom`
- `/clients/{id}/bcct`, `/clients/{id}/bcct/imports`,
  `/clients/{id}/bcct/exports`
- `/clients/{id}/config` (follow-up commit `922d6bb` — same lean
  helper, `dh_path=""` since /config doesn't surface a DH link)

**Perf** (prod TTFB measured via curl):
- Source-view pages: 1.7-2s server time.
- `/config` warm: ~1.3s (was multi-second on Johnson with full BCCT pull).
- Origin-step cold: still 2.7s (separate bottleneck; see Open Items).

### Data ingest — Johnson tồn CO snapshot
- Source: `/mnt/p/Downloads/tru lui CO Johnson.28.05.26.xlsm` (29/05).
- `scripts/convert_co_stock.py` sheet NK2: 62,531 rows →
  25,717 unique adjustments (36,814 `Đã_xuất=0` skipped; 0 errors).
- Uploaded local (`http://127.0.0.1:8001/clients/johnson-vn/co-stock/import`):
  2,662 inserted + 23,055 updated (overlay over prior local data), 0 errors.
- Synced prod (`https://barry-co.tinsu.ai/...`):
  25,717 inserted (sheet was empty on prod), 0 errors.
- Same `batch_id batch_0ba5ff092ef3bc99` both sides — file hash is the
  upsert idempotency key.
- Prod UI banner after sync: `johnson-vn · 650 TP · 12482 NVL ·
  60173 dòng Tồn CO · 65846 dòng BCCT`.

### Auth audit (no code change — deferred by user)
Browser SSO is real prod-grade. CO→DH backend channel is still dev mode:
- DH: `DATA_HUB_API_AUTH_DISABLED=1` env + `hub.app_settings.api_auth_strict=false`.
- CO: `DATA_HUB_API_TOKEN=` empty.
- Anyone reaching `ttdatahub.tinsu.ai/v1/hub/*` calls API without bearer.

User explicitly chose to defer — only one customer using right now, low risk.
Cutover steps captured in STATUS.

### Perf investigation — `/co-case/{id}/origin` cold ~2.7s (no fix yet)
Server-only TTFB on prod with growatt-vn (2-product case):

| Path | TTFB |
|---|---|
| `/co-case` (list) | 0.7s |
| `/co-case/{id}` (detail → shipment) | 0.8-0.9s |
| `/.../shipment` | 0.7s |
| **`/.../origin` cold** | **2.7s** |
| `/.../origin` warm | 1.0s |
| `/.../documents`, `/review` | 0.7s |
| `/.../config` (post-fix) | 0.35s |

Cold /origin spends ~1.5-2s in `bom_service.workspace` fetching
`get_bom_artifacts` per product (1 DH round-trip per TP). Already has a
60s TTL cache (`_DATA_HUB_BOM_WORKSPACE_CACHE`) — first cold call is
the unmitigated case. Quick win = eager-warm bom_workspace in
`preload_co_case_origin_context` so a click to /origin after detail
open hits warm cache. Deferred; user closed the conversation before
implementation.

## Decisions Made

- **Field-name translation at boundary, not internal rename** for
  propose-bom. Operators think "định mức" (norm_per_unit); only the DH
  wire format needs `qty_per_unit`. Translating at
  `build_bom_proposal_rows` keeps the internal vocabulary intact.
- **Hard gate (case completed) over soft gate (all locked)** for dossier
  ZIP. `/close` already enforces all-locked, so requiring `completed`
  implies all-locked AND adds the explicit "frozen for shipping" intent.
- **Strip CO source views entirely in DH mode**, not just lazy-load on
  click. CO is a consumer; duplicating DH's UI was adding latency for
  no benefit. Local-mode branch kept so dev/test workflows aren't broken.
- **Defer prod backend auth fix** per user. Low risk while there's only
  one tenant.
- **Don't drop `prepare_case_origin_products`** even though it has no
  live caller in `app/` — 4 unit tests cover invariants not otherwise
  exercised (`build_signature` short-circuit, sequential allocation
  shortage trace, `origin_snapshot.product_order` propagation, DH
  `material_identity` → `bom_product_code` wiring). Removing would
  either lose coverage or require non-trivial test refactor.

## What Didn't Work

- **Live propose-BOM verify after the field-name fix**: the puppeteer
  script tried to chain unlock → edit-row → calculate → lock → propose
  but kept getting 409 cascade (origin_calculation_lock conflict on the
  test case after the earlier close/reopen cycle). Not related to the
  fix — unit test already pins the contract.
- **First attempt at lean context for catalog/bom/bcct broke 4 tests**
  because FakePortfolioService / FakeSourceIndexStore shims don't expose
  `source_summary`. Wrapped the lean call in `try/except AttributeError`
  so it falls through to the legacy `client_context` path when shims
  don't support it.
- **Test `test_bom_page_uses_bom_service_boundary` had to be updated**:
  its original assertion checked that NVL-1 (a material row) rendered on
  the BOM page in DH mode. After the strip, CO doesn't render BOM rows
  at all in DH mode. Test now asserts callout + "Mở DH" link + NVL-1
  absence.
- **Original puppeteer script asserted button labels via
  `innerText.split('\n')[0]`** — that picked up the emoji icon as the
  first line. Fix: `querySelector('strong')?.innerText.trim()` to grab
  the actual button label.

## Open Items

- **`/co-case/{id}/origin` cold path** — bom_workspace eager warm in
  preload (≈1.5-2s saved on first click). Cache infra already exists,
  just need to call `bom_service.workspace(client, product_codes,
  case_id)` inside `preload_co_case_origin_context` after source_context
  warm.
- **Prod backend auth cutover** (deferred). Steps captured in STATUS;
  one customer right now so low priority.
- **Stale carry-overs from prior session** still open (claim_id
  stability HIGH, customs FX backfill, origin calc lock TTL, missing
  CO forms seed, `can_view_client` short→long, HS↔form coherence).
- **Empty `data_hub_target_url` on /config template**: lean context
  passes `dh_path=""` so the target URL ends with `/clients/{id}/`.
  Template doesn't reference it today but a future addition could
  render an empty href. Either drop the field when `dh_path` is empty,
  or guard in template.

## Reusable Lessons (worth surfacing cross-project)

1. **Field-name divergence at service boundaries is a silent killer.**
   CO used `norm_per_unit` internally for operator-facing "định mức";
   DH used `qty_per_unit` for the standardized BOM-row contract. They
   never disagreed at the type-check level (both strings), and the
   proposal endpoint accepted both — DH just silently treated missing
   `qty_per_unit` as 0. Result: every proposal looked submitted from
   the CO side but got auto-rejected on DH (or shown blank in the
   reviewer UI). Lesson: when wrapping a third-party schema, ALWAYS
   translate at the adapter layer and assert at least one round-trip
   contract field in a test that pins both directions.

2. **Stripping a duplicate UI is sometimes worth more than optimizing
   it.** The catalog/BOM/BCCT pages were re-rendering full paginated
   tables from a Data Hub source CO doesn't own. Every render was a
   5-10s wait on Johnson because `source_workspace` paginated 65k
   rows over HTTP. Spending 2 hours optimizing the table view would
   have been worse than the 30 minutes spent replacing it with a
   summary card + link to the canonical UI. When CO is a consumer of
   another service's source data, prefer linking out over mirroring.

3. **"X already works on local but X is slow on prod" usually means
   N HTTP round-trips × latency.** Local DH at 127.0.0.1 makes the
   round-trip cost invisible; prod over WAN multiplies it by N
   products × 200-500ms per call. Always benchmark the cold path
   against the production network.

4. **`if X or "X" in form` is not a guard, it's a short-circuit.**
   The EUR.1 → PSR template bug came from this exact pattern at the
   top of `hq_sheet_codes_for_product` — it returned BEFORE looking
   at operator overrides. The fix was just reordering: precedence
   chain first, fallback-by-form last. When you see a `return` near
   the top of a precedence function, ask whether it can be pushed
   to the bottom.
