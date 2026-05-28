# 2026-05-29 — State machine overhaul, Load BOM perf, 2-day gap rule

26 commits across 3 cohesive themes. All pushed to `tinsu/main`, CI green,
demo deployed after every push. 360 tests passing locally.

## What Was Done

### 1. BOM picker filter sprint (5 commits)
Tightened `/clients/.../co-case/.../origin` BOM picker so operators only see
currently-active, flat BOMs scoped to this case.

- `4dd2558` — DH API request artifact for `/bom/artifacts?lifecycle=active&shape=flat&latest_per_variant=true&intents=...&case_id=...`.
  Data Hub shipped at commit `316ec57`.
- `488215e` — Consume the DH filter: new `list_bcct_artifacts_filtered`
  adapter + `filter_applied` echo for graceful fallback + thread `case_id`
  through `bom_service.workspace()`. Falls back to client-side filter when
  DH doesn't ship the contract.
- `2f01f6c` — Picker dropdown enrichment: option label becomes
  `#N · X dòng · YYYY-MM-DD · {kind} · v:{variant} · {state_glyph}`. Meta
  strip under the select shows kind / strategy / variant id / freshness
  badges with `stale_reasons` tooltip.
- `3babb33` + `b53633f` — Local and demo verify scripts.

### 2. State machine sprint (HIGH #1, HIGH #2, Phase 1-3, 10 commits)

User wanted the case Open/Close × Sheet Chốt/Mở chốt × Tồn CO Giữ/Nhả triad
audited and tightened. Audit doc lives at
`.ai/audits/2026-05-28-case-sheet-stock-state-machine.md`.

#### HIGH #1 — Server gate on locked-sheet edits (`286573d`)
substitute-row / edit-row / add-row / save endpoints used to accept POSTs
when sheet was `locked`, mutate `material_overrides`, flip to `stale`, and
leave the existing `co_stock_claims` rows referencing the old materials —
quiet Tồn CO leak via UI bypass. Added `reject_if_sheet_locked()` 409 guard.

#### HIGH #2 — Delete-case releases claims with explicit confirm (`2ad0f22`)
`delete_case_record` used to refuse only on completed / calc-lock-held and
never queried claims. Deleting an open case with locked sheets used to
strand `co_stock_claims` rows at a dead `case_id` forever. Now:
- `claims_summary_for_case()` probes count + lots.
- `delete_case_record(release_claims=False)` raises `CaseHasActiveClaimsError`
  with the claim/lot count for messaging.
- `/delete` route reads form field `confirm_release_claims`. Without it →
  409 + Vietnamese explainer. With it → `release_all_claims_for_case` runs
  before the case row is removed.
- Delete modal warning swaps text on `claims_count` from `data-claims-count`
  attached per dossier — operator sees "Hồ sơ đang giữ N dòng tồn trên M
  lot. Xác nhận xoá sẽ nhả toàn bộ tồn về kho. Thao tác không thể hoàn tác."
  before confirming, never silent auto-release.
- Flash cookie carries result; case-list page renders it.

#### Phase 1 — pessimistic lock band-aid (`11e4369`)
Postgres-mode `case_lock` also took a session-scoped `pg_advisory_lock`
keyed on client_id, on a dedicated connection held open for the duration
of the context manager. Quick win against the two-operators-same-client
clobber. New regression test runs two threads against a live DB and
asserts the second thread's lock acquisition timestamp ≥ the first
thread's save commit.

#### Phase 2 — promote `co_cases` to source of truth (5 commits)
- `edb5e93` (2.1 + 2.2) — Migration 015 adds `revision int not null default 0`.
  New `PostgresCoCaseStateStore.save_case_record(client_id, payload, expected_revision)`
  upserts with `WHERE revision = expected_revision`; raises
  `CaseRevisionConflict` carrying the current revision.
- `836bd16` (2.3) — `get_state` hydrates `cases[]` from `co_cases` rows
  ordered by `updated_at desc` and joins `co_supporting_files` on
  `case_id`. `co_case_states.payload` keeps only non-per-case state.
- `0c15ba4` (2.4) — `create_case_record` / `update_case_record` /
  `delete_case_record` forward to per-case methods via new helper
  `_persist_case_row`. Retry loop on `CaseRevisionConflict` (dormant
  under the case_lock band-aid but ready for Phase 3.2).
- `2b4b553` (2.5) — Stop writing `cases[]` into `co_case_states.payload`.
  Existing stale `cases[]` shed naturally on next save (read path already
  ignores it).

#### Phase 3.1 — FK on `co_stock_claims` (`7c1d81d`)
Migration 016 adds `(client_id, case_id) → co_cases(client_id, case_id)
ON DELETE CASCADE` after backfilling any pre-existing orphans. Defense in
depth on top of the application-level HIGH #2 fix.

#### Phase 3.2 — drop case_lock band-aid (2 commits)
- `8121823` (partial) — Documented case_lock as defense-in-depth, opened
  follow-up task for supporting_files refactor (the actual prereq).
- `4758fac` (final) — Added `PostgresCoCaseStateStore.save_case_supporting_files`
  which wipes + rewrites a single case's file rows (not the whole client's).
  `co_case_store.save_supporting_file` calls it alongside the per-case
  `co_cases` write. With supporting_files now per-case, the pg_advisory_lock
  branch was removed from `case_lock`; file-only `fcntl.LOCK_EX` remains
  as same-host belt-and-braces.

#### Critical bug fix (`b09507d`)
Phase 2.2 erroneously treated `expected_revision <= 0` as "this must be a
fresh insert" with `INSERT ON CONFLICT DO NOTHING`. Existing rows from
the migration backfill came in at `revision = 0`, so every Load BOM POST
hit the conflict branch and returned 500. User saw this as "Load BOM bị
Internal Server Error". Rewrote to always try UPDATE first; only INSERT
when the row genuinely doesn't exist. Smoke covers fresh insert,
update-at-0, update-at-1, and conflict on stale revision.

### 3. Load BOM perf sprint (4 commits)
Local Johnson Load BOM was taking 30-45s on every click because
`/calculate` set `force_source_refresh=True` → `co_case_source_context`
→ `list_bcct(client_id)` full pull → 60k rows over HTTP.

- `dc0571f` — Fast path: `_refresh_co_stock_delta_or_full(client)` syncs
  the snapshot via the existing delta contract, then
  `read_co_stock_rows(client_id)` reads from local PG. invoice_matches +
  material_rows come from the cached origin context the shipment step
  populated. Falls back to legacy full-pull when snapshot empty or delta
  errored. **45s → 6s.**
- `104ab96` — In-process cache for `read_co_stock_rows` keyed by
  `(max(indexed_at), count)` so it auto-invalidates on materializer
  UPSERT/DELETE but no-op delta refreshes preserve it. Cap of 4 clients
  per worker. Snapshot read 2.8s → 0.09s. **6s → 4-5s.**
- `3b19dad` — 30s freshness TTL on the delta refresh itself. Profile
  showed the DH delta round trip + `source_summary` was costing ~4s even
  when zero rows changed; operators clicking Load BOM repeatedly don't
  need to re-poll DH. Explicit `/refresh-co-stock` button bypasses TTL.
  **4-5s → 2-3s warm.**
- `5367315` — Demo timing harness.

Final: **45s → 2-3s warm** (15-20× faster). Cold (after server restart) is
~9s because snapshot cache is also cold.

### 4. 2-day import→export gap rule (4 commits + brief)

Feature brief at `.ai/features/2026-05-29-import-export-gap-rule.md` with
8 decisions and 5 risks. User answered the open spec questions inline.

- `35686c9` — `app/co_stock_eligibility.py` with `is_stock_lot_eligible`
  returning `EligibilityVerdict(ok, reason)`. Status gate + 2-day calendar
  gap. Inclusive (`>=`). Helpers: `parse_flexible_date` (ISO, ISO datetime,
  DD/MM/YYYY, YYYYMMDD), `earliest_export_date` (multi-export anchor),
  `min_gap_days_from_config`. 27 unit tests cover edges.
- `2a02160` — `co_stock_allocation_pool` now accepts `export_date` +
  `min_gap_days`, annotates each row with `_eligibility_ok` +
  `_eligibility_reason`. `co_stock_is_usable` trusts the annotation when
  present. New `case_allocation_pool` wrapper computes the anchor.
  Wired into 4 pool builds (prepare_origin_products, prepare_origin_sheet,
  recalculate_origin_sheet_edits, substitute-stock).
- `6d9cc43` — `substitute-stock` endpoint ships per-lot `eligibility_ok`,
  `eligibility_reason`, `eligibility_label`, `registration_date`. Modal
  JS renders rejected rows with strike-through + red badge "Ngày nhập
  quá gần ngày xuất khẩu". CSS for ineligible / reason / date.
- `bcc224d` — Wire `client_config["co_stock"]["min_days_before_export"]`
  via `min_gap_days_from_config` into `prepare_case_origin_sheet` +
  `recalculate_origin_sheet_edits` (other 2 sites already had it).
- `ad25ffb` — **CO-local UI editor**. New form field on `/clients/<id>/config`
  "Tồn C/O" section. Persists to `clients.payload.co_stock_overrides` in
  the local app_state store (bypasses `require_local_source_writes` because
  it's a CO-side overlay, not DH source data). New helper
  `effective_min_gap_days(client, client_config)` centralises resolution
  order: CO-local override > Data Hub config > DEFAULT (2). 4 new unit
  tests pin the order.

Locked sheets are grandfathered (rule applies only at pool build, not on
the persisted claims). DEFAULT_MIN_GAP_DAYS = 2, value = 0 disables the
rule.

## Decisions Made

- **Notify before delete, not after.** User explicitly insisted ("nhớ là
  phải thông báo chứ không phải auto-release im lặng"). Modal warning is
  the contract — server explicit confirm flag (`confirm_release_claims=1`)
  is the bypass guard.
- **Phase 1 = band-aid, Phase 2 = proper.** User accepted that the
  `pg_advisory_lock` was a quick win that would be dropped once per-case
  writes landed. They chose "1+2+3" knowing Phase 3.2 final would remove
  the lock.
- **Grandfather locked sheets for the 2-day rule.** Filter only at pool
  build, not on persisted claims. Audit-friendly + avoids invalidating
  prior work.
- **CO-local overlay for the threshold, not DH config edit.** User asked
  for a UI editor; DH writes are blocked when `DATA_HUB_ENABLED`. Storing
  the override on `clients.payload.co_stock_overrides` keeps the operator
  in CO UI and avoids a DH API request. `effective_min_gap_days`
  centralises the override-vs-DH-vs-default order.
- **30s freshness TTL on /calculate's delta refresh**, NOT a fixed cache
  window. Explicit `/refresh-co-stock` bypasses it. Trade-off accepted:
  operator who just imported BCCT in DH and clicks Load BOM within 30s
  would see stale data — but they would also click Refresh tồn for that
  workflow.
- **Fall back, never block.** Both perf paths (snapshot read, delta
  refresh) keep the legacy full pull as a fallback so the operator
  never silently calculates against an empty or stale snapshot.

## What Didn't Work

- **First `save_case_record` design** (commit `edb5e93`): treated
  `expected_revision <= 0` as "fresh insert" which broke every UPDATE
  against backfilled rows. Bug only lit up when actual production-shaped
  data hit the path (legacy revision=0 rows). User caught it via "Load
  BOM bị Internal Server Error". Fixed in `b09507d`.
- **First `case_lock` advisory lock with autocommit=True**: psycopg3
  errored because the connect path set search_path in an implicit
  transaction. Switched to manual `commit()` after `pg_advisory_lock`.
- **Initial perf assumption: 1-2s achievable on first commit.**
  Profile showed read_co_stock_rows alone was 2.8s for 60k rows. Took
  3 commits to actually hit warm 2-3s.
- **Demo can't visually verify perf or 2-day rule UI**: growatt-vn on
  demo has 1 case with no BOM picked, so the fast path doesn't activate
  there. Local Johnson (60k stock + populated source_snapshot) is the
  representative test. Demo verify confirmed schema migrations applied
  + no regression but couldn't show the speedup.
- **Trying to drop `case_lock` advisory lock before refactoring
  supporting_files**: the per-client wipe + rewrite of `co_supporting_files`
  in save_state was the actual race condition. Phase 3.2 had to be split
  into a "partial" doc-only commit + a "final" commit that did the
  supporting_files refactor first.

## Open Items

- **Visual perf demo on remote**: needs a populated growatt-vn case
  with confirmed shipment + materialized snapshot. Either seed manually
  or accept local-only verification.
- **`prepare_case_origin_products`** appears to be dead code (no live
  callers in `app/`, only docs). Confirm + remove.
- **`acquire_client_lock` / `release_client_lock`** on
  `PostgresCoCaseStateStore` are unused after Phase 3.2 final. Defer
  decision: keep as defensive opt-in or delete with the dead-code sweep.
- **Carry-over from prior sessions** (none made progress this session):
  customs FX historical backfill, origin calculation lock TTL, claim_id
  stability, seed missing CO forms (D / E / AK / ...), `can_view_client`
  short→long fallback, HS↔form coherence.

## Reusable Lessons (worth surfacing cross-project)

1. **"Default zone" trap in migrations.** Adding a column with
   `DEFAULT 0` means every existing row reads `0` as "default", but code
   that interprets `0` as "this is a sentinel value" will break against
   the backfilled data. Specifically: a `revision` column where `0`
   means "fresh row" silently misclassifies every legacy row as needing
   `INSERT`. Always smoke test the new code against pre-existing data,
   not just fresh inserts. Caught only when the user saw Load BOM 500
   in production-shaped local data.

2. **Two-step cache invalidation key for materialized snapshots.**
   `max(indexed_at)` catches UPSERT (the `indexed_at = now()` trick on
   `ON CONFLICT DO UPDATE`). But pure DELETE doesn't change any other
   row's `indexed_at`, so `max` can stay the same after a delete. Add
   `count(*)` as the second axis: `(max_indexed_at, row_count)`. Either
   axis changing invalidates the cache. Cheap (single aggregate query),
   covers the 4 cases (insert, update, delete-newest, delete-older).

3. **TTL "user-perceived stale OK" vs "stale forbidden".** Some hot
   paths benefit from a TTL on the freshness check itself even if the
   semantic is "give me the latest data". Operators clicking Load BOM
   3 times in 10 seconds don't expect 3 DH polls — they expect one
   poll's worth of data. The trick is an explicit "force refresh"
   surface (the existing `/refresh-co-stock` button) so the workflow
   that DOES need bypass has it.

4. **Refactor in 5 small steps, not 1 big one.** State-machine sprint
   shipped 10 commits over Phase 1 → 2.1 → 2.2 → 2.3 → 2.4 → 2.5 →
   3.1 → 3.2 partial → 3.2 final + a bug fix. Each commit was
   independently reviewable, kept tests green, and didn't break the
   demo. The discipline came from a feature audit doc that listed all
   the invariants up front — the next AI working in this area can
   keep the doc updated as the spec.

5. **"Notify before mutation, not after"** as a hard UX rule. User
   pushed back when initial HIGH #2 design auto-released claims and
   only showed a toast afterward. The redesign moved all the operator
   communication BEFORE confirm (modal warning swaps text on
   `claims_count`), then explicit `confirm_release_claims=1` flag is
   the bypass guard against curl / dev-tools bypass. Same surface
   in 2 places: UI tells the operator, server enforces against
   non-UI callers.

6. **Probe-based DH endpoint detection** continues to pay off. The
   `filter_applied` echo (this session) + `server_time` echo (prior
   session) + `download.zip` probe (prior session) all let CO ship
   the consumer before DH ships the producer and auto-upgrade with
   zero coordination. Pattern: write the request artifact, stub the
   consumer with graceful fallback, ship. When the sister repo lights
   up the feature, CO picks it up on the next request.
