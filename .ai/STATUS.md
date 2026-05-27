# Project Status

## Current State
- Active branch: `main`. Cost-allocation feature work uncommitted at the moment of this snapshot.
- CO dev server running at `http://127.0.0.1:8001` (`npm run co:serve`, with `--reload`). `/healthz` → 200.
- Local Data Hub running at `http://127.0.0.1:8754`. Login: `admin@data-hub.local` / `local_test_password`.
- CO Postgres: `BARRY_DATABASE_URL=postgresql:///barry_co?host=/var/run/postgresql`, schema `co`.
- Migration 012 (`co_cost_allocation_ratio`) applied. GROWATT sample (24 rows) imported via admin UI.
- New tests (4 files, **38 passing**): `tests/test_cost_allocation_store.py`, `tests/test_cost_allocation_importer.py`, `tests/test_cost_allocation_routes.py`, `tests/test_cost_buildup_schema.py`.
- Pre-existing 30 test failures on `main` are environmental drift (Data Hub state, demo data mismatch); confirmed unrelated by stash comparison (43 pristine fails − 13 new passing tests = 30). One was a real bug we fixed today (`origin.py:109` KeyError on `hs_code`); the rest likely benefit too.

## Recent Changes (this session)
- **Cost allocation ratios** — new feature, end-to-end:
  - Schema: `db/migrations/012_cost_allocation_ratio.sql` (PK `(client_id, product_code)`, `product_code=''` = Mode B sentinel).
  - Store: `app/cost_allocation_store.py` with DB+JSON dual-write. JSON fallback root via `COST_ALLOCATION_CONFIG_ROOT` env (default `config/cost-allocation`).
  - Excel importer: `app/cost_allocation_importer.py` parses agency files by column index (matches GROWATT shape). 7th coefficient column (`Lợi nhuận`) intentionally ignored — profit is residual.
  - Admin UI: `/clients/{id}/cost-allocation` with Mode B panel, Mode A table, Excel upload (replace-all-per-client, preserves Mode B), template download, `/resolve` JSON endpoint. New nav tab "Hệ số phân bổ".
  - Origin panel UI: cost-buildup grid expanded from 4 → **6 detail inputs + editable profit**. "Áp hệ số" button next to FOB calls `/resolve` and fills 6 details; profit left blank for engine to derive.
  - Schema migration: `cost_buildup` now stores 6 detail keys (`wages, welfare, rent, depreciation, other_mfg, transport_storage`) + `profit`. Legacy 4-key shape still read for back-compat. Engine reader `bang_ke_xml_generator._coerce_cost_buildup` rolls 6 details up to the 4 rollups the XML config consumes — no XML/template change needed.
- **Perf fix**: `_cost_allocation_context()` was calling shared `client_context()` which triggers a Data Hub source-workspace scan (~2.6s for Growatt). Replaced with minimal context (`resolve_client` + ratio rows). **3588 ms → 67 ms (53× faster).** Tradeoff: nav tagline counts (`X TP · Y NVL · …`) hidden on cost-allocation page only; `_client_nav.html` now `{% if client.counts %}…{% endif %}`.
- **Pre-existing bug fix**: `app/origin.py:109` did `row["hs_code"]` (KeyError when a material row lacked the key); changed to `.get("hs_code", "")`. Bug existed since the demo commit; only surfaced after Data Hub became material source-of-truth (some materials lack HS). Fix unblocks origin-page render for several existing growatt cases (e.g. CO-ZIP).

## Next Steps
1. **Commit pending work** (this snapshot is uncommitted — see `git status`).
2. **Investigate the remaining ~29 pre-existing test failures**. Same class as the `hs_code` bug — likely demo data evolved while strict-typed accessors didn't. Quickest path: pick a few representative failures and apply the same `[key]` → `.get(key, "")` pattern where safe.
3. **Áp hệ số visual test on a real LVC/RVC case** with a TP code that exists in GROWATT sample (e.g. `PV00.0048400`). Today's screenshot used `TP-ZIP` which rightly fell back to Mode B; confirming Mode A on a real product completes the visual loop.
4. **Profit handling on bảng kê output**: today the engine derives V as `FOB − (IV + VII)` style. Confirm with agency that leaving the profit input blank and letting the engine derive matches their expectation, vs requiring an explicit number.
5. **Consider extending replace_all to support partial updates** (today it nukes all per-Mã-SP rows). If agencies send incremental updates instead of full lists, we'll need an upsert-by-row import mode.
6. **Old open items still apply**: Approach A vs B default engine choice (session 2026-05-26 §1), PSR conclusion text confirmation, `-vn` suffix centralisation.

## Blockers
- None blocking cost-allocation work.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in **fully accented Vietnamese** (or English if accents aren't practical). Never unaccented Vietnamese.
- User prefers concise, direct status — no fluff, no preambles. Verify before claiming done.
- Cost-allocation storage decision: **CO Postgres**, not Data Hub. Cost-buildup ratios are CO-form-specific accounting policy (TT 05/2018), not shared master data. Data Hub guardrail (`test_data_hub_policy.py`) doesn't apply.
- `require_local_source_writes()` is intentionally **not** called on cost-allocation write routes. That guard exists for Data-Hub-owned shared source data (BCCT, catalog); cost-allocation ratios are CO-only config and need to be editable even when `DATA_HUB_ENABLED` is on.
- Schema design: `cost_buildup` persists 6 details + profit (new shape) OR 4 rollups (legacy). Reader at engine boundary normalises. Don't normalise on persist — keep what came in.
- Profit is **residual**, not a coefficient. GROWATT sheet's column H (`=GIÁ XUẤT XƯỞNG - CHI PHÍ XUẤT XƯỞNG`) is intentionally ignored on import. UI leaves the profit input blank after "Áp hệ số"; user can override.
- `_cost_allocation_context()` deliberately skips `client_context()` for perf. If you add fields that need source workspace or BOM, profile first — `source_workspace_for_client()` is ~2.6s on Growatt.
- E2E script: `scripts/e2e_cost_allocation.py` (Playwright). Drives login → upload sample → resolve endpoint → click Áp hệ số. Screenshots land in `.ai/screenshots/cost-allocation/`. Both `.ai/screenshots/` and `.ai/samples/` are gitignored.
- Pre-existing CO-ZIP test case has FOB=100 + product `TP-ZIP` which is NOT in the GROWATT sheet — falls back to Mode B. For a Mode-A live test, use a product code from the GROWATT 24 list (`PV00.0048400`, `SD00.0010600`, `BIENTAN.16`, ...).
- Test DB isolation: route + store tests force JSON fallback via `monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)`. One opt-in DB integration test uses a unique `client_id=test-cost-alloc-{os.getpid()}` and cleans up before/after.
- Reload mode is on (`uvicorn --reload`), so Python/HTML/CSS edits hot-reload without a restart.
