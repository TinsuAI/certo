# Project Status

## Current State
- Branch `main` at `ad25ffb`, **26 commits ahead** of prior STATUS snapshot (`e4888cd`).
  All pushed to `tinsu/main`; CI green; demo deployed at `https://barry-co.tinsu.ai`
  with migrations 015 + 016 applied on demo DB.
- Local CO dev at `http://127.0.0.1:8001` (`npm run co:serve` `--reload`);
  Data Hub at `:8754`. Both `/healthz` OK.
- Local suite **360 passed + 7 skipped**. CI runs the same suite green.
- Postgres test of cross-process concurrency still passes (`test_case_lock_serializes_concurrent_save_state_on_postgres`)
  even after Phase 3.2 final dropped the `pg_advisory_lock` — single-host serialization
  comes from `fcntl.LOCK_EX`, cross-process safety from per-case optimistic
  concurrency on `co_cases.revision` + per-case `co_supporting_files` writes.

## Recent Changes (this session — 26 commits, oldest → newest)

| Group | Commit | Topic |
|---|---|---|
| BOM picker | `4dd2558` | DH API request artifact for `/bom/artifacts` filter |
|  | `488215e` | Consume DH picker filter (active + flat + case-scoped) |
|  | `2f01f6c` | UI enrichment: date + source kind + variant + state badges |
|  | `3babb33` | Local verify script |
|  | `b53633f` | Demo verify script |
| State machine | `286573d` | HIGH #1: server gate on locked sheet edit endpoints |
|  | `2ad0f22` | HIGH #2: delete_case_record releases claims + confirm modal |
|  | `11e4369` | Phase 1 band-aid: pg_advisory_lock per-client in case_lock |
|  | `edb5e93` | Phase 2.1 + 2.2: revision column + save_case_record |
|  | `836bd16` | Phase 2.3: read cases[] from co_cases not payload blob |
|  | `0c15ba4` | Phase 2.4: dual-write co_cases + retry hook |
|  | `2b4b553` | Phase 2.5: cutover — drop payload.cases write |
|  | `7c1d81d` | Phase 3.1: FK co_stock_claims → co_cases ON DELETE CASCADE |
|  | `8121823` | Phase 3.2 (partial): document case_lock band-aid |
|  | `c057358` | Demo verify script |
|  | `b09507d` | **Bug fix** save_case_record: revision=0 ≠ "fresh insert" |
|  | `4758fac` | Phase 3.2 final: per-case supporting_files + drop advisory lock |
| Load BOM perf | `dc0571f` | Fast path via delta refresh + snapshot read |
|  | `104ab96` | In-process cache for read_co_stock_rows |
|  | `5367315` | Demo timing harness |
|  | `3b19dad` | 30s freshness TTL — skip DH delta on hot path |
| 2-day gap rule | `35686c9` | Predicate module + brief + 27 unit tests |
|  | `2a02160` | Wire into co_stock_allocation_pool + 4 call sites + 3 tests |
|  | `6d9cc43` | UI rejection reason in substitute modal |
|  | `bcc224d` | Configurable via client_config["co_stock"]["min_days_before_export"] |
|  | `ad25ffb` | CO-local UI editor for the threshold |

### Data Hub API requests shipped end-to-end this session
- `2026-05-28-bom-artifacts-active-flat-filter.md` → DH commit `316ec57`
  → CO `488215e` consumed.

### Migrations shipped
- `015_co_cases_revision.sql` — adds `revision int default 0` for optimistic
  concurrency on per-case writes.
- `016_co_stock_claims_case_fk.sql` — FK `(client_id, case_id)` → `co_cases`
  with `ON DELETE CASCADE`. Backfills orphan claims first.

### Local test fixture
- Same fixtures as prior STATUS (growatt `co-case-b1e2602f0d8d`,
  `co-case-36ad2da0201a`, `co-case-e44fe2065b62`; johnson `co-case-4e9f5a3b1e9c`).
- New unit test files:
  - `tests/test_bom_picker_filter.py` — 7 tests, DH picker filter consumer
  - `tests/test_co_stock_eligibility.py` — 35 tests, 2-day gap rule

## Next Steps

1. **Visually verify perf on demo** — local Johnson Load BOM 45s → 2-3s warm
   (15-20× faster). Demo growatt-vn has only 1 case w/o BOM artifacts so the
   fast path isn't exercised there. Either seed a populated growatt-vn case
   on demo OR accept local-only verification.
2. **Re-validate locked-sheet gap rule decision** — current behaviour
   grandfathers locked sheets (rule applies only at calculate/substitute build
   time). The user picked this; revisit if a customer expects locked sheets
   to flip stale when the rule changes.
3. **Customs FX historical backfill** (carry-over from prior STATUS).
4. **Origin calculation lock TTL** (60 min, carry-over).
5. **Claim ID stability** (carry-over HIGH — claim_id derives from
   `material_index`, breaks on BOM reorder).
6. **Seed missing CO forms** (carry-over D / E / AK / AANZ / AJ / RCEP /
   UKVFTA / VK / VC / VJ).
7. **`can_view_client` short→long client_id URL fallback** (carry-over).
8. **HS↔form coherence + criteria token validation** (MED, carry-over).
9. **`prepare_case_origin_products`** — kept on purpose. 4 unit tests
   exercise it as entry point for invariants not otherwise covered
   (build_signature short-circuit, sequential allocation shortage trace,
   `origin_snapshot.product_order` propagation, DH `material_identity` →
   bom_product_code wiring). Removing would require either a 4-test
   refactor that drops the `product_order` snapshot assertion, or losing
   coverage.

## Notes for Next AI Session

- **Memory** at `/home/vp/.claude/projects/-home-vp-workspace-client-barry-CO/memory/`
  has 5 entries. Read MEMORY.md first.
- **Test on local by default.** Only touch prod when explicitly told.
- **Demo URLs** (in memory, not in repo): `barry-co.tinsu.ai`,
  `ttdatahub.tinsu.ai`.
- **Prod test account**: `claude-check@local` / `claude-temp-2026`. URLs MUST
  use `-vn` long form on prod until `can_view_client` is fixed.
- **Data Hub local restart**: DH worker at `:8754` runs with `--workers 4` and
  no `--reload`. If DH schema or code changes, user must restart it before
  CO sees the change. We hit this twice this session — once when migration
  072 dropped `materials.category_override` (DH workers held the old code),
  and once for the `/bom/artifacts` filter shipment.
- **CO local dev** writes profile to `/tmp/barry-co-8001.log`.
- **State machine architecture (Phase 3.2 final)**:
  - `co_cases` row per case with `revision` (optimistic concurrency).
  - `co_supporting_files` rows per case (per-case wipe + rewrite).
  - `co_case_states.payload` keeps only `origin_calculation_lock` + `schema_version` — no `cases[]`.
  - FK `co_stock_claims → co_cases ON DELETE CASCADE`.
  - `case_lock` is **file-only** now (fcntl.LOCK_EX). The Postgres advisory
    lock helpers were dropped from `PostgresCoCaseStateStore` after Phase 3.2
    final confirmed no remaining caller.
- **2-day gap rule**:
  - Predicate in `app/co_stock_eligibility.py` (`is_stock_lot_eligible`,
    `earliest_export_date`, `min_gap_days_from_config`).
  - `effective_min_gap_days(client, client_config)` in `main.py` is the
    centralised resolver — CO-local override on `clients.payload.co_stock_overrides`
    wins, else DH config, else default 2.
  - Operator edits via `/clients/<id>/config` → "Tồn C/O" section.
  - Locked sheets are grandfathered (filter only at pool build).
- **Load BOM hot path**:
  - `_calculate_stock_rows_from_snapshot` does delta refresh (skipped if
    snapshot was refreshed within 30s) + reads from
    `read_co_stock_rows_cached` (in-process snapshot cache invalidated by
    `(max(indexed_at), count)` marker on `co_stock_rows`).
  - Falls back to legacy full pull when snapshot empty or delta refresh
    errored — operator never silently calculates against stale data.
- **`save_case_record` semantics gotcha** (commit `b09507d`):
  legacy rows came in at `revision=0` after migration 015 backfill. The
  initial Phase 2.2 implementation treated `expected_revision=0` as "this
  must be a fresh insert" which broke every update against backfilled rows
  (Load BOM was returning 500). Fixed: always try UPDATE first; only INSERT
  when no row exists AND `expected_revision == 0`.
- **`require_local_source_writes` carve-outs**: legal_name / tax_code AND
  the new `co_stock_min_days_before_export` are CO-side overlays, persisted
  in `clients.payload`, NOT DH config. They write through even when
  `DATA_HUB_ENABLED` is on.

### Housekeeping (2026-05-29)
- Committed Phase-3 audits + this session's handoff log + the orphan
  2026-05-28 demo-verify log.
- Tracked `screenshot_cost_buildup.mjs`, `time_load_bom.mjs`,
  `verify_load_bom_local.mjs`, `verify_state_machine_local.mjs` under
  `scripts/`.
- Dropped `full_workflow_audit{,_v2,_v3,_v4}.mjs` (4 iterations rolled
  into `verify_state_machine_local.mjs`) and `verify_prod_deploy.mjs`
  (single-use post-deploy smoke).
- Dropped `PostgresCoCaseStateStore.acquire_client_lock` /
  `release_client_lock` (unused after Phase 3.2 final).
