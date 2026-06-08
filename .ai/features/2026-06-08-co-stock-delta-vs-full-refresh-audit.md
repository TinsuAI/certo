# Feature: D1 — CO-stock delta-vs-full refresh audit + parity

Discovery for BACKLOG D1. Risk class: **SAI TỒN** (wrong tồn → over/under-claim downstream).
Prior patch `039baeb` fixed one symptom (empty snapshot + leftover `server_time` → delta no-op).
This audits the whole `_refresh_co_stock_delta_or_full` / `_try_delta_refresh` / `_full_refresh` /
`record_refresh_state` machinery (`co_case_context.py:2904-3004`) + `co_stock_materializer`.

## Scope
- **In:** correctness audit of delta vs full refresh; identify every vector where the materialized
  `co_stock_rows` snapshot can silently diverge from upstream BCCT; design a delta-vs-full parity
  test harness; propose surgical fixes ordered by risk.
- **Out (this brief):** P1 index N+1 perf, the trừ-lùi fold (separate, already shipped), DH-side
  `since`/tombstone contract changes (CO is a consumer — file an api-request if DH change needed).

## Findings (severity-ordered)

### A — Tombstone + new-row keys break under `aggregate_by_declaration_and_allocation_code` (LATENT)
Delta deletes via `tombstone_source_rows = ["import-row-<sha1(transaction_key)[:16]>", …]`
(`co_case_context.py:2945`). The snapshot's delete key is `co_stock_rows.source_row`. For
`lot_policy == "line_level"` (and `manual_review`) these match 1:1 — `source_row = import_row_id(txn)`
(`co_stock_derivation.py:29`). But under `aggregate_by_declaration_and_allocation_code`, multiple
import rows collapse into one lot whose `source_row` is **comma-joined** ids
(`co_stock_derivation.py:180`). Then:
  - `removed = {k for k in tombstone_source_rows if k in old_payloads}` (`materializer.py:118`) — a
    single `import-row-X` is a *substring* of `"import-row-X,import-row-Y"`, never `==` a key →
    **tombstone silently dropped → lot never deleted → phantom stock → over-claim.**
  - A new/changed row in an existing group re-derives `co_stock_rows_from_bcct([delta_items])` over
    only the delta, producing a fresh aggregate with a *different* comma-joined `source_row` → UPSERT
    on `(client_id, source_row)` **INSERTs a duplicate lot** instead of merging → **double-counted tồn.**
- **Blast radius today: zero.** Both prod clients (johnson-vn, growatt-vn) are `line_level` (verified).
  This is a landmine for any future aggregate-policy client; `aggregate_*` is a supported, tested policy.

### B — Full refresh captures `server_time` AFTER the data pull → gap-window data loss (PROD/line_level)
`_full_refresh` pulls via `source_workspace` (t0), then `_probe_server_time` does a **second** full
envelope pull `since=""` (t1 > t0) only to grab `server_time`, discarding items (`co_case_context.py:2974-2992`).
  - **Correctness:** any BCCT row created in (t0, t1] is absent from the full pull (already snapshotted at
    t0) and excluded from the next delta (`since = t1` ⇒ its `server_time ≤ t1`). **Permanently missing →
    under-count → under-claim.** Holds regardless of `since` being `>=` or `>`.
  - **Cost:** doubles the ~12s Johnson pull every full refresh.
  - Delta path does NOT have this bug — its `server_time` comes from the same envelope as the items
    (`co_case_context.py:2940`), which is the correct pattern.
- **Fix direction:** capture the high-water mark *before/with* the data, never after. Cheapest safe fix:
  probe `server_time` BEFORE the full pull (conservative — next delta re-pulls the gap, idempotent
  UPSERT), or derive the full snapshot from the envelope call itself so items+server_time are atomic.

### C — Deletes depend entirely on tombstones; claim-blocked tombstones are consumed once (line_level)
In delta mode the ONLY delete signal is the tombstone list. Two leaks:
  - If DH ever drops/voids a row **without** emitting a tombstone, delta never removes it (full would,
    via `removed = old - new`). Need to confirm DH's tombstone completeness guarantee.
  - `_claims_blocking_removal` keeps a tombstoned lot that has a locked claim (`materializer.py:121`) —
    correct — but the tombstone is consumed in that one delta and **never re-sent**. After the claim
    releases, no future delta carries that old tombstone ⇒ **phantom lot survives forever** until a full
    refresh self-heals. Over-claim risk against an upstream-deleted lot.
- **Fix direction:** persist unapplied/claim-blocked tombstones and retry on next refresh, and/or run a
  periodic/threshold full refresh as the reconciliation backstop.

### D — A successful-but-empty full pull WIPES the whole snapshot (PROD/line_level)
`_full_refresh` eagerly calls `source_workspace`; a hard DH failure raises and is caught upstream (no
wipe — safe). But a *successful* pull returning **0 published_rows** (empty page, pagination/auth-scope
glitch, transient upstream) flows as `co_stock_rows = []`, and full mode computes `removed = all old
keys` → **mass DELETE of every lot** (except claim-locked) → records `snapshot_row_count = 0`. The
`039baeb` guard only covers the *read* side (empty snapshot ⇒ force full); nothing guards the *write*
side. The now-empty snapshot then keeps forcing full — same johnson-vn "stuck empty" symptom, different
root cause.
- **Fix direction:** in full mode, if derive returns 0 rows but the existing snapshot has N>0, treat as
  suspicious — skip the wipe, log, do NOT record state. Add an explicit "client truly has no BCCT"
  escape (e.g. only allow full→empty when DH confirms 0 source rows).

### E — `bcct_row_count_at_refresh` is a count, not a content marker → masks drift
Both paths record `bcct_row_count_at_refresh = source_summary.bcct.published_row_count` (total ~65846),
even on delta (`co_case_context.py:2968, 2987`). `compute_sync_status` decides `in_sync` purely on
`current_count - snapshot_count == 0` (`materializer.py:897-899`). Two different row-sets with equal
count read as `in_sync`; a net-zero add+remove upstream shows in-sync while content drifted. Combined
with C/A, under-applied deltas are invisible to the operator.
- **Fix direction:** add a content axis to sync status — track `last_bcct_server_time` divergence and/or
  a cheap content hash; stop equating count parity with content parity.

### F — Refresh result `{ok:true, rows:0}` is ambiguous (UX)
"0 rows" can mean "nothing changed" OR "snapshot error / empty pull". Operator can't tell. Surface the
mode + reason (full-because-empty, delta-N-changed, M-tombstoned, K-blocked-by-claims).

## Decisions
- **Parity is the acceptance gate.** The core invariant: applying the same sequence of upstream states
  through full vs through delta+tombstone must yield byte-identical `co_stock_rows`. Build this as a
  reusable harness (fake DH envelope source) and make it the regression net for every fix below.
- **Full refresh is the reconciliation backstop.** Delta is an optimization; it must never be the only
  thing standing between the snapshot and truth. A periodic/threshold full is required (drift in C/E).
- **Gate delta on invariants it actually holds.** Delta is only sound for `line_level`/`manual_review`.
  Cheapest correct guard for A: force full whenever `lot_policy != line_level` until aggregate-aware
  delta exists.

## Risks
- Fixes touch the live tồn snapshot for both prod clients — every change needs the parity harness green
  + a DB-mode run on a johnson-vn-sized fixture before deploy. Memory [[test-env-filemode-vs-datahub]]:
  DB co_stock tests need `.env`; file-mode run must stay green too.
- Tests writing to the shared dev DB is exactly BACKLOG **T1** — schema-isolate this harness or it adds
  cruft (memory [[co-case-store-db-json-reseed]]).
- D's "don't wipe on empty" must not mask a legitimate client-emptied-upstream case → needs the DH
  "0 source rows confirmed" signal, else a real deletion is stuck forever.

## Open Questions (need answers before coding)
1. **DH `since` semantics:** inclusive (`>=`) or exclusive (`>`)? Is `server_time` monotonic per row's
   create/update, and does an upstream **edit** (qty correction on an existing import row) bump it so
   delta re-pulls that row? If not, edited-in-place lots drift until full. (CO is a consumer — confirm
   from the DH BCCT contract; file an api-request if the guarantee is missing.)
2. **Tombstone completeness:** does DH guarantee a tombstone for every row removal, with full tombstone
   set on page 1 of a `since` pull (the adapter assumes this — `data_hub_client.py:529`)?
3. **Aggregate policy roadmap:** any near-term client on `aggregate_by_declaration_and_allocation_code`?
   Decides whether A is "guard + force full" (cheap) or "make delta group-aware" (real work).
4. **Full-refresh cadence:** is there any scheduled/periodic full today, or only lazy-on-empty + the
   30s-stale `/calculate` trigger? If only lazy, C/E have no backstop.

## Suggested next step
`/tdd` in risk order: D → B → C → E/F → A, each fix landing with a test that fails before it.

## Progress (2026-06-08, `/tdd`)
Contract confirmed from `.ai/api-requests/2026-05-28-bcct-incremental-since-filter.md`: `since` is
EXCLUSIVE (`indexed_at > since`); `server_time` = gap-safe high-water mark; tombstones one-shot
(`removed_at > since`, never re-sent). transaction_key cross-reimport stability sign-off still BLANK.

- **D — DONE.** `_plan_removed_keys` (pure, tested) aborts the wipe when a full pull derives 0 rows over a
  non-empty snapshot (`aborted_empty_full_pull`); `_full_refresh` skips state advance on abort. Caveat:
  a *legitimately* emptied client now also preserves stale tồn until a DH "0 source rows confirmed" escape
  is added — safe-over-destructive for now.
- **B — DONE.** `_full_refresh` now probes `server_time` BEFORE the data pull (was after → gap-window loss).
  Residual double-pull also eliminated: new `DataHubClient.bcct_server_time` probes page 1 only
  (`limit=1`), instead of `list_bcct_with_envelope(since="")` re-paginating ~60k rows to discard them.
  `_probe_server_time` prefers it, falls back to the envelope path for fakes/old backends.
- **A — DONE (guard).** `_refresh_co_stock_delta_or_full` forces full when
  `lot_policy == aggregate_by_declaration_and_allocation_code`. Aggregate-aware delta deferred.
- Tests: `tests/test_co_stock_empty_pull_guard.py` (13). Full suite 557 passed / 9 skipped (file-mode).
  Note: `/v1/hub/bcct` belongs only in code literals, not docstrings — `tests/test_data_hub_policy.py`
  regex-scrapes any quoted span containing `/v1/hub` and flags unapproved ones.

## Remaining (need decisions)
- **C (prod, open):** claim-blocked one-shot tombstone never re-applied → phantom lot after claim release.
  Fork: (C1) persist+retry blocked tombstones (new schema/state) vs (C2) periodic/triggered full-reconcile
  backstop (no periodic full exists today). Needs user decision.
- **E:** `compute_sync_status` is count-only → masks content drift; switch to a server_time/content axis.
- **F:** surface refresh mode/reason (full-because-empty, delta-N, M-tombstoned, K-blocked) — UX.
- **Parity harness** (full vs delta+tombstone → identical `co_stock_rows`) still unbuilt; gated by T1
  (DB isolation) for a clean DB-mode run.
