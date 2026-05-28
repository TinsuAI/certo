# Project Status

## Current State
- Branch `main` at `e47e968`, **15 commits ahead** of prior STATUS snapshot. All pushed to `tinsu/main`; CI green; demo deployed and verified at `https://barry-co.tinsu.ai`.
- Local CO dev at `http://127.0.0.1:8001` (`npm run co:serve` `--reload`); Data Hub at `:8754`. Both `/healthz` OK.
- Data Hub now ships at `28ea610` with Bearer-aware declarations download.zip; CO `e47e968` consumes it through `download_declarations_zip` adapter — verified live with 200 + 29.5KB TKX embedded into dossier ZIP at `03-to-khai/TKX/...`.
- Pre-existing 30 local test failures from prior STATUS are gone (cleaned up via newer fixtures); local suite **320 passed + 6 skipped**. CI runs the same suite green.

## Recent Changes (this session — 15 commits, oldest → newest)

| Commit | Topic |
|---|---|
| `0838659` | CI actions bumped off Node 20 (deprecation 2026-06-02) — checkout v5, setup-python v6, setup-uv pinned to v8.1.0 (v8 dropped major tags). |
| `5aa13aa` | Bảng kê HQ export 4-item checklist fix: legal_name (new client field + form), tax_code wiring, declaration_date propagation, dynamic currency label on form-mau template (was hardcoded "USD"). |
| `06f8c2f` | Backfill `product.source_declaration_date` for old cases via Data Hub `list_declarations` (`earliest_bcct_date` → DD/MM/YYYY); patches `case.source_invoice_matches` cache so next render is free. |
| `fed2836` | Multi-currency phase 1: `exchange_rate_to_vnd` + `exchange_rate_source` on `co_stock_rows.payload`, 4-tier priority (vnd_native / bcct_declared / customs_lookup / missing). |
| `c171e51` | Multi-currency phases 2-5: dual `*_native` / `*_vnd` allocation values, renderer mode swap, per-product `fob_currency` + `fob_vnd`, template hidden inputs + JS swap, FX source chip. |
| `1cc69a3` | Tồn CO refresh audit + `scripts/lvc_drift_snapshot.py` (0/6 products drifted on 5 locked growatt cases — engine math safe). |
| `ca368cd` | Tồn CO refresh: drop destructive DELETE+INSERT, use UPSERT + targeted DELETE with claim-safety + `snapshot_row_added/_updated/_removed` audit events (option B). |
| `e0797c9` | Consume Data Hub `since` + `tombstones` for delta refresh — refresh time on 38k-row growatt dropped from 12s (full) to ~1.7s (no-op delta). |
| `e2f63c5` | Bidirectional currency conversion in renderer (VND ↔ nguyên tệ) — fix the bug where USD-export product still showed VND material rows. |
| `0ca012a` | Drop workflow step 3 (Form & PSR placeholder). Lock Bảng kê edits when sheet `origin_sheet_status=locked` (substitute / add-row / delete disabled + JS guard). |
| `c0c11a7` | Workflow stepper: accurate status (Lô hàng partial state, TKX/TKN reflects file-presence not just BCCT matches) + compact single-row layout. |
| `5d44726` | Step 6 redesign: single dossier ZIP + close/reopen-case buttons + completed-case banner. |
| `c7f24d5` | Close-case fix: `case_from_record` now propagates `status`, `update_case_record` raises `CaseClosedError` (→ 409) when closed, sheet-locked precheck before close, release origin_calculation_lock on close. |
| `fc8669d` | Review & Xuất UX polish: hero + 2-action panel + 3-card checklist deeplinks. Bỏ source snapshot/audit/preview blocks. 920px scoped + mobile responsive. |
| `e47e968` | Pre-stage Bearer download consumer for dossier ZIP — probe-based, embeds TKX/TKN blobs when DH supports, falls back to manifest links when not. **Live and embedding** after DH commit `28ea610`. |

### Data Hub API requests shipped end-to-end this session
- `2026-05-28-bcct-incremental-since-filter.md` → DH commit `ebedf86` → CO `e0797c9` consumed.
- `2026-05-28-bcct-declarations-download-bearer.md` → DH commit `28ea610` → CO `e47e968` consumed.

### Local test fixture
- `co-case-b1e2602f0d8d` (CO-ZIP, growatt) — Mode-A Áp hệ số smoke fixture, still works.
- `co-case-36ad2da0201a` (CO-BOM-INV, growatt, VND) — used by `scripts/verify_export_checklist.mjs` 4-item checklist smoke; all PASS.
- `co-case-e44fe2065b62` (E2E-DH-220630, growatt-vn, 31 import decls) — used to verify Bearer download embed; produced a 59.7KB dossier ZIP with `03-to-khai/TKX/TKX_E2E-DH-220630.zip` nhúng (29.5KB blob).

## Next Steps

1. **Multi-currency LVC snapshot on real prod cases** (carry-over from `1cc69a3` audit). Local growatt data has trivially-trivial drift because materials are all VND. Snapshot LVC% before/after on 5 real cases with USD/EUR materials after the next BCCT refresh that has actual non-VND lots.
2. **Customs FX historical backfill** — store currently has 1 USD rate (2026-04-27). For older case declarations (pre-2026) the FX lookup misses → renderer falls back to native. Run `refresh_customs_exchange_rates(history_start_date='2024-01-01')` via CLI or admin route.
3. **Concurrent edit race on `co_case_states`** (carry-over HIGH item from prior STATUS) — last-writer-wins on lock/reopen; `expected_revision` exists on `/recommendation-override` only.
4. **Claim ID stability** (carry-over HIGH) — `claim_id = sha256(case_id|sheet|source_row|material_index)`. Reordering BOM materials breaks the claim. Use stable lot-key.
5. **Origin calculation lock TTL too long** (60 min) — staff that abandons a session blocks colleagues for 1h.
6. **Seed missing CO forms** in `default_co_form_config()`: D / E / AK / AANZ / AJ / RCEP / UKVFTA / VK / VC / VJ. Built-in still has only B / CPTPP / EUR.1 / AI.
7. **`can_view_client` short→long client_id URL fallback** (carry-over).
8. **HS↔form coherence + criteria token validation** (MED, carry-over).
9. **Investigate 30 pre-existing local test failures** — those may have resolved already; the suite now runs 320 passed locally. Confirm before re-flagging.
10. **GitHub Actions Node 20 deprecation** — **DONE** in `0838659`; deadline 2026-06-02 is moot.

## Notes for Next AI Session
- **Memory** at `/home/vp/.claude/projects/-home-vp-workspace-client-barry-CO/memory/` has 5 entries: demo URLs, SSH access, test account, deploy hygiene, test-local-by-default preference. Read MEMORY.md first.
- **Test on local by default.** Only touch prod when explicitly told ("trên prod" / "lên demo" / etc.).
- **Demo URLs** (in memory, not in repo): `barry-co.tinsu.ai`, `ttdatahub.tinsu.ai`.
- **Prod test account**: `claude-check@local` / `claude-temp-2026`. URLs MUST use `-vn` long form on prod until `can_view_client` is fixed.
- **Data Hub local restart**: `data-hub` worker process at `/home/vp/workspace/client/data-hub` runs with `--workers 4` and **no `--reload`** — if DH ships a new endpoint, user must restart the worker for CO to see it. CO's own dev server has `--reload`.
- **Workflow has 5 steps now** (was 6): Lô hàng, Chứng từ, Bảng kê C/O, TKX/TKN, Review & Xuất. The old `guidance` step (Form & PSR) was removed; `/guidance` returns 404.
- **Currency mode display logic**: when `product.fob_currency != "VND"`, native mode renders VND material rows divided by `fob_fx_rate`. Tests in `tests/test_renderer_currency_mode.py` lock the direction matrix.
- **Close-case is the single source of truth** for completed cases. `case_from_record` now copies `status` from DB. `update_case_record` raises `CaseClosedError` (→ 409) on any mutation when `existing_status in COMPLETED_CASE_STATUSES` unless incoming status is `open`/`reopen`. Banner + button gating in `co_case.html` mirrors this.
- **Dossier ZIP layout**: `00-README.md`, `01-bang-ke/{case_code}-bang-ke-HQ.xlsx`, `02-chung-tu/NN-{slot}-{filename}`, `03-to-khai/MANIFEST.md`, `03-to-khai/{TKX,TKN}/<filename>.zip` (embedded when DH Bearer endpoint reachable, else manifest-only). Probe lives in `app/main.py:_try_fetch_declaration_archives`.
- **Tồn CO delta refresh**: tracks `last_bcct_server_time` on `co_stock_refresh_state`. First refresh after a clean DB does full pull; subsequent ones use `since=<server_time>&include_tombstones=true`. Tombstone source_row computed via the same sha1(transaction_key)[:16] mapping.
- **Authoritative case state** still lives in `co.co_case_states` (jsonb-per-client). Never UPDATE `co.co_cases` directly — use `update_case_record()` from `app/co_case_store.py`.
- **User writes Vietnamese casually**; respond in **fully accented Vietnamese** (or English). Never unaccented Vietnamese.
- **Pronoun protocol**: user uses "tao" / "mày" → reply with "ông" / "tôi".

### Untracked exploratory files (decide later)
The repo carries several untracked files that have been floating across sessions. They're useful one-shot artifacts but not committed yet. Either commit them under `scripts/` or delete:
- `scripts/full_workflow_audit{,_v2,_v3,_v4}.mjs` — 4 iterations from the 2026-05-28 stock-ledger session.
- `scripts/screenshot_cost_buildup.mjs`, `scripts/verify_prod_deploy.mjs` — from earlier sessions.
- `.ai/sessions/2026-05-28-demo-verify-prod-sso-fix.md` — session log from the prior session that never got committed.
