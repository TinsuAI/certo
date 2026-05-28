# 2026-05-28 — Multi-currency, refresh delta, close-case, dossier ZIP

15 commits in one continuous session. Three Data Hub API requests were filed
and consumed end-to-end within the session. Demo deploys after every commit.

## What Was Done

### 1. Node 20 deprecation (`0838659`)
- `actions/checkout` v4 → v5, `actions/setup-python` v5 → v6, `astral-sh/setup-uv` v5 → **v8.1.0** (pinned exact; v8 dropped major tags as a supply-chain hardening).
- Verified all three jobs run on Node 24 runners (Python tests / Docker build / Deploy demo).

### 2. Bảng kê HQ export 4-item checklist (`5aa13aa` + backfill `06f8c2f`)
User flagged 4 regulatory mismatches on the xlsx output:

1. **Tên thương nhân** — `client.name` was a short label ("Growatt"). Added `legal_name` field to client storage + form in `/clients/{id}/config`. Overlay applied in `resolve_client` (Data Hub doesn't expose `legal_name`). Renderer reads `case.customer_legal_name`.
2. **Mã số thuế** — `case.customer_tax_code` was read by the renderer but never set anywhere. Wired through `case_from_record` + the case-create paths.
3. **Tờ khai xuất khẩu date** — `product.source_declaration_date` was a read-only field nobody wrote to. Now populated from `match.declaration_date` at BCCT-match time, plus a backfill helper that pulls `earliest_bcct_date` via Data Hub's `list_declarations` and patches both `product.source_declaration_date` AND `case.source_invoice_matches[].declaration_date` so next render is free. ISO → DD/MM/YYYY normalization.
4. **Đơn vị tiền tệ** — `config/bang-ke-config.xml` had `format="{fob} USD"` literally, and the form-mau template hardcoded "USD" at L10/L11/H13. Added `currency_cells` block to all 5 JSON form configs (lvc/cth/ctsh/rvc/psr) + dynamic `{currency}` in XML + workbook_io fallback path.

Smoke `scripts/verify_export_checklist.mjs` exercises a real puppeteer login + form save + dossier export end-to-end; all 4 PASS.

### 3. Multi-currency phases 1-5 (`fed2836`, `c171e51`, `1cc69a3`)
Per `.ai/features/2026-05-28-currency-multi-currency.md`. Five-phase rollout:

- **Phase 1** — `co_stock_rows.payload` gets `exchange_rate_to_vnd` + `exchange_rate_source`. 4-tier resolution: `vnd_native` (currency=VND, rate=1) → `bcct_declared` (BCCT row's own `ty_gia_thanh_toan`) → `customs_lookup` (`customs_fx_store.lookup_exchange_rate` weekly granularity) → `missing`. `co_stock_rows_from_bcct` gains optional `customs_fx_rows` kwarg; callers pre-load via `_safe_customs_fx_rows()`.
- **Phase 2** — `stock_allocation_line` returns dual `unit_value_native` + `unit_value_vnd` + `material_value_*` + carries `exchange_rate_to_vnd` + `exchange_rate_source`. `origin_material_from_bom_row` aggregates `material_value_vnd` across lines (even mixed-currency cases sum cleanly because every line is VND-base via its own FX rate).
- **Phase 3** — Both renderers (`bang_ke_renderer.py` for the JSON-config path + `bang_ke_xml_generator.py` for the XML-driven path) get a `_pick_currency_value(material, key, use_vnd, product)` helper. Currency label cells (L10/L11/H13) reflect target currency.
- **Phase 4** — `co_case.html` emits dual `data-base-*-native` + `data-base-*-vnd` per material cell + `data-row-currency`. JS `applyCurrencyMode` swaps in place. Plus an FX source chip on the "Nguồn" column flagging `bcct_declared / customs_lookup / missing / mixed`.
- **Phase 5** — `product.fob_currency` (defaults to `product.currency` from BCCT). `_attach_fob_vnd()` runs in `attach_origin_sheet_states` and populates `product.fob_vnd` via customs FX lookup at declaration date.

#### Bidirectional fix (`e2f63c5`)
User caught: "ca nguyen tệ deu la VND". My initial Phase 4 only converted `native → VND` for vnd mode. The reverse `VND → nguyên tệ` for native mode when `product.fob_currency != VND` was missing.

`_pick_currency_value` now implements the full direction matrix:
```
row.currency == target               → row[key]                     (no-op)
target == "VND"                      → row[key + "_vnd"]            (canonical)
target non-VND, row in VND           → row[key + "_vnd"] / fob_fx   (cross-convert)
```

JS swap mirrors the same logic with `data-product-fob-currency` + `data-product-fob-fx-rate` on the panel. 8 unit tests in `tests/test_renderer_currency_mode.py` lock the matrix.

#### LVC drift snapshot
`scripts/lvc_drift_snapshot.py` against 5 real growatt locked cases: **0/6 products drifted** between native and vnd modes. Existing materialized rows lack phase-1 FX fields → renderer falls back to native → engine math unchanged. The "HIGH risk — engine semantics drift" line in the original brief is **over-stated for already-locked cases**.

### 4. Tồn CO refresh: option B + delta (`ca368cd`, `e0797c9`)
User asked why refresh wipes all `co_stock_rows`. Answer: it didn't need to. Refactor:

- **Drop the `DELETE FROM co_stock_rows WHERE client_id` wipe.** Replace with UPSERT + targeted DELETE.
- `_classify_changes` buckets keys into added / updated / identical. Volatile audit fields (`eligibility_config_hash`, `eligibility_config_version`) excluded from the diff because `get_client_config` regenerates `updated_at` on every call — pre-existing client_config_store quirk that would flag every row as updated.
- Claim-safety pre-check: rows whose `source_row` has an active `co_stock_claims.status='locked'` entry are **kept** even when missing from the new derive set — they'd otherwise orphan the case's claim.
- Emit `snapshot_row_added/_updated/_removed` events per change (migration 013 adds them to the `co_stock_events` CHECK constraint).

#### Delta refresh (`e0797c9`)
Filed `.ai/api-requests/2026-05-28-bcct-incremental-since-filter.md` requesting Data Hub add `since` + `tombstones` to `/v1/hub/bcct`. User restarted Data Hub; CO consumed it the same hour:

- Adapter `list_bcct_with_envelope(client_id, since, include_tombstones)` returns `{items, tombstones, server_time}`.
- Materializer gains `mode="delta"` — derive callback returns ONLY the changed rows; removed-keys = explicit `tombstone_source_rows`.
- Endpoint refactor: probe `last_bcct_server_time`; if present, attempt delta; if response carries `server_time`, persist and continue. Otherwise fall back to full-pull. First refresh always full (no prior server_time).
- Migration 014 adds `last_bcct_server_time` to `co_stock_refresh_state`.

Live result on growatt (38,287 rows): refresh #1 (initial) ~12s, #2/#3 (delta no-op) **~1.7s** — ~7× speed win.

### 5. Workflow polish (`0ca012a`, `c0c11a7`)
- **Dropped the `guidance` step** (Form & PSR placeholder). 5 workflow steps now: Lô hàng, Chứng từ, Bảng kê C/O, TKX/TKN, Review & Xuất. `/guidance` returns 404. 3 tests updated to assert 404 or moved hints to the shipment page.
- **Lock-state edit gate**: when `product.origin_sheet_status='locked'`, substitute trigger + add-row trigger get `disabled` and the JS handlers `early-return` on a `data-origin-sheet-locked="1"` panel attribute. Defends against dev-tools `disabled` bypass; server endpoints already validate.
- **Workflow stepper status**: "Lô hàng" returns `review` (partial) when only one of invoice / market is set, instead of `todo`. "TKX/TKN" downgrades from `ready` to `review` when `tkx_tkn_summary` reports missing files (was always `ready` once any invoice_match existed). Stepper CSS: 5 columns instead of 6 + min-height 2.6rem instead of 4.5rem (compact).

### 6. Step 6 (Review & Xuất) two-pass redesign (`5d44726`, `c7f24d5`, `fc8669d`)
First pass added single dossier ZIP + close-case toggle. **Two follow-up bugs** the user reported:

- "**Đóng hồ sơ không có hiệu lực**" — root cause: `case_from_record` never propagated `record.status` into the runtime case dict. DB had `status=completed` but the template's `case.status in [...]` was always false. Fix: copy status. Plus add `CaseClosedError` (subclass of `ValueError`) raised by `update_case_record` when existing status is in `COMPLETED_CASE_STATUSES` unless incoming status is `open`/`reopen`. FastAPI exception handler converts to 409. Plus release `origin_calculation_lock` on close.
- "**Chỉ đóng được khi tất cả sheet đã chốt**" — close endpoint refuses with 409 listing unlocked sheets. Close button disabled with explanation when sheets aren't all locked.
- "**UX polish**" — hero gradient + 3-card checklist replacing the old 6-zone layout. Removed: stats stack, source evidence snapshot, audit notes, criteria preview table. Scoped 920px max-width with mobile responsive at 900px.

### 7. Dossier ZIP — Bearer download consumer (`e47e968`)
Filed `.ai/api-requests/2026-05-28-bcct-declarations-download-bearer.md`. The cookie route `/clients/{cid}/declarations/download.zip` works for the operator's browser, but CO can't fetch it server-side. Asked for a `/v1/hub/clients/{cid}/declarations/download.zip` Bearer mirror.

Pre-staged the consumer with a probe:
- `DataHubClient.download_declarations_zip(client_id, direction, declaration_nos, filename)` adapter.
- `main._try_fetch_declaration_archives` probes the call; any error (404 / network / auth) silently returns `{}` and the dossier renderer falls back to manifest-only mode.
- `create_dossier_zip` takes a `declaration_archives` dict keyed by `TKX/...zip` / `TKN/...zip`; embeds bytes under `03-to-khai/` when populated.
- README + MANIFEST text switch wording between "đã nhúng sẵn" and "sẽ tự nhúng khi Data Hub bật endpoint" based on whether archives are present.

Data Hub shipped at `28ea610` the same session. Live verify (case `growatt-vn / co-case-e44fe2065b62`):
```
Archive contents (4 entries):
  00-README.md
  01-bang-ke/E2E-DH-220630-bang-ke-HQ.xlsx
  03-to-khai/MANIFEST.md
  03-to-khai/TKX/TKX_E2E-DH-220630.zip  ← 29,546 bytes embedded from DH
```

## Decisions Made

- **Option B over option A for refresh**: drop the wipe entirely (UPSERT) instead of just emitting diff events on top of the wipe. User's question "tại sao phải xoá data cũ?" was correct — the wipe was never necessary for correctness, only the simplest path through INSERT/UPDATE/DELETE in two SQL statements.
- **Probe-based DH endpoint detection** for both `since` and `download.zip`: CO auto-upgrades the moment DH ships, no CO redeploy needed. Detection key is `server_time` field presence (for `since`) or response status (for `download.zip`).
- **`(declaration_no, line_no, customs_code)` lot key for growatt allocation_code regex**: verified empirically (137/528 customs_codes map to multiple internal materials cross-line, but 0 within-line). DH confirmed `transaction_key = f"{declaration_no}-{line_no}"` is deterministic across re-imports.
- **Volatile-key exclusion in materializer diff**: rather than fixing the pre-existing `get_client_config` quirk (regens `updated_at` on every call → config_hash drift), exclude `eligibility_config_hash` + `eligibility_config_version` from the payload comparison. Lower blast radius.
- **Close-case as a one-button toggle with idempotent re-click**: bouncing through `update_case_record` would trigger the close-gate against itself. Detect `co_case_is_completed(case)` at the top of the close endpoint and just redirect without writing.
- **Step 6 strips Source evidence snapshot + audit notes**: those are dev/audit info, not operator-facing. User explicitly said "chỉ để lại những thứ thực sự cần thiết". Tests updated to drop those assertions.
- **Currency direction matrix in renderer helper**: `_pick_currency_value(material, key, use_vnd, product=None)` — single function handles 4 cases (row=target / target=VND / target=foreign + row=VND / fallback). Both renderers delegate so approach-A and approach-B stay byte-identical.

## What Didn't Work

- **`fetch` from puppeteer's cookie-domain context** for some smoke runs: when the page was on `/auth/callback` mid-redirect, `fetch('/x')` resolved against the callback origin and CORS-failed. Workaround: explicit `page.goto(BASE_CO + '/clients')` before the fetch.
- **Initial Phase 4 swap (commit `c171e51`)**: only `native → VND` direction. User immediately spotted the missing reverse for USD-export products. Fix was `e2f63c5`.
- **Initial close-case (commit `5d44726`)**: persisted status but the runtime dict didn't pick it up because `case_from_record` was missing the field copy. Banner + reopen button never rendered. Fix in `c7f24d5`.
- **First config form save attempt**: `require_local_source_writes()` raised 409 because `DATA_HUB_ENABLED` is on locally. Moved identity-update block BEFORE the require call (legal_name + tax_code are CO-side render metadata, not source data — should be editable even in DH source-mode).
- **JS `String.fromCharCode(...new Uint8Array(buf))`** in smoke scripts: blew the call stack on a 150KB xlsx. Switched to chunked approach.
- **Smoke verify on USD product `co-case-781cea0d0bf9`**: had 0 materials, so the body cells never exercised the VND→USD conversion. Re-targeted to a real-allocation case to validate.

## Open Items

- **Multi-currency LVC drift on real prod cases** — local data is too sparse (1 USD rate in customs_fx_store, all materials VND).
- **Customs FX historical backfill** — needs an admin to run `refresh_customs_exchange_rates(history_start_date=...)` before USD/EUR cases pre-2026 can render correctly in vnd mode.
- **Concurrent edit race on `co_case_states`** — last-writer-wins on lock/reopen (HIGH from prior session). `expected_revision` exists on `/recommendation-override` only.
- **Claim ID stability** — `claim_id` derived from `material_index` breaks on BOM reorder (HIGH from prior session).
- **Origin calculation lock TTL** — 60 min is too long; staff that abandons a session blocks colleagues for an hour.
- **Untracked smoke scripts**: `scripts/full_workflow_audit{,_v2,_v3,_v4}.mjs`, `scripts/screenshot_cost_buildup.mjs`, `scripts/verify_prod_deploy.mjs`, plus the prior session's `.ai/sessions/2026-05-28-demo-verify-prod-sso-fix.md` — decide whether to commit or delete.
- **Pre-existing 30 local test failures** — they appear to be gone (local suite 320 passed now). Confirm before re-flagging as a TODO.

## Reusable Lessons (worth surfacing cross-project)

1. **API contract → probe consumer → ship** is a tight loop when both repos are local. We landed two end-to-end Data Hub features in one session (`since` + Bearer download), each within ~30 min of DH commit, because CO had the consumer pre-staged before DH shipped. Pattern: write the API request artifact, stub the consumer with graceful fallback, then wait for the sister repo.

2. **`case_from_record` (or any "DB row → runtime dict" hydrator) is a high-trap function** — every field that the template reads MUST be copied here. When a field works in some places but not others, suspect the hydrator first. We hit this twice: once for `status` (close-case bug), once for `customer_tax_code` (export bug).

3. **Bidirectional currency conversion needs a single helper that knows the target**. Don't think in "swap direction" — think in "target currency". The target is `VND` for vnd mode and `product.fob_currency` for native mode. The conversion direction falls out naturally once target is named.

4. **Wipe-and-rebuild caches are a maintenance trap, not a simplification**. The `co_stock_rows` refresh wipe seemed "simple" but cost us audit trail, claim safety, and made delta-pull impossible. UPSERT + targeted DELETE is barely more code (~50 LOC) and unlocks all three.
