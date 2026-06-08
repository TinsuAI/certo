# Session: CO-stock refresh audit (D1) + backbone architecture doc — 2026-06-08

## What Was Done
- **`/discover` D1** — audited the entire delta-vs-full CO-stock refresh machinery
  (`co_case_context.py:2904-3004` + `co_stock_materializer.py`), cross-referenced the DH contract
  artifact. Found 4 silent-corruption vectors + 2 secondary (E/F). Brief:
  `.ai/features/2026-06-08-co-stock-delta-vs-full-refresh-audit.md`.
- **`/tdd` — 3 correctness fixes + 1 perf fix** (commit `2c856da`, pushed + deployed prod+demo):
  - **D** — extracted pure `_plan_removed_keys(mode, new_keys, old_keys, tombstones) → (removed, abort)`;
    full mode with derive=0 over a non-empty snapshot now aborts the wipe (`aborted_empty_full_pull`),
    `_full_refresh` skips state advance on abort.
  - **B** — `_full_refresh` probes `server_time` BEFORE the pull (was after). Added cheap
    `DataHubClient.bcct_server_time` (page-1 only, `limit=1`); `_probe_server_time` prefers it, falls
    back to the envelope path for fakes/old backends.
  - **A** — `_refresh_co_stock_delta_or_full` forces full when `lot_policy` is aggregate.
  - Tests: `tests/test_co_stock_empty_pull_guard.py` (13). Full suite 557 passed / 9 skipped.
- **`/rev`** — reviewed the diff + one hop to callers. 0 Critical. Found Important-1 (the probe
  full-re-paginated ~60k rows) and fixed it within the same session (the cheap probe above).
- **Deploy** — pushed `TinsuAI/co main`, watched CI to green, verified prod + demo `/version` both serve
  `git_sha: 2c856da`.
- **Deep architecture Q&A** with user → corrected two mental-model errors, then baked the corrected model
  into **`docs/co-stock-architecture.md`** (commit `4f567ff`, unpushed) + linked from `docs/README.md`.

## Decisions Made
- **Fixed only the dependency-free vectors (D/B/A) this session.** C (tombstone retry), E (sync-status),
  F (UX) need either a DH answer or a design decision — deferred with the fork documented in the brief.
- **B's fix is conservative, not the "fully correct" rewrite.** Probing before the pull (vs deriving the
  full snapshot from the same envelope) keeps `source_workspace` untouched and needs no DH-contract
  assumption; the only cost (a second pull) was eliminated by the cheap page-1 probe.
- **D guards strictly-empty only** (full + 0 rows over snapshot>0), not a ratio threshold. Minimal, lowest
  false-positive; a ratio guard would need the DH "0 confirmed" signal. Safe-over-destructive: a genuinely
  emptied client preserves stale tồn until that escape exists — documented as a known caveat.
- **A is a guard (force full), not aggregate-aware delta.** No client uses aggregate today; the real fix
  is deferred.
- **Doc language = Vietnamese** (matches `docs/BUSINESS_LOGIC_CONFIRMATION.md`, the closest sibling, and
  the all-Vietnamese conversation), code identifiers kept in English.

## What Didn't Work / Corrected
- **First architecture review had two errors the user caught:**
  1. Called the CO-stock snapshot "just a cache" — wrong. App CO OWNS tồn CO (trừ-lùi + claims have no
     upstream). Only the BCCT-derived opening is sourced from DH; `co_stock_rows` is a rebuildable
     projection, but `co_stock_adjustments` + `co_stock_claims` are unrecoverable source-of-truth.
  2. Wrote lot identity as "mã HS hải quan" — wrong. Verified `transaction_key = direction‖declaration‖
     line‖item_code`; `item_code` is the customs ITEM/material code, NOT `hs_code` (a separate descriptive
     attribute). HS code would be useless as identity (coarse tariff bucket).
- **First full-suite run after the probe fix tripped `test_data_hub_policy`** — its regex scrapes any quoted
  span containing `/v1/hub`; my docstring's backticked `/v1/hub/bcct` + a stray `""` got slurped into a bogus
  "endpoint literal". Fix: keep `/v1/hub/*` literals in code only, reword the docstring.

## Open Items
- **C — claim-blocked tombstone never retried** → phantom lot after claim release. Fork (needs user):
  C1 persist+retry blocked tombstones (new schema) vs C2 periodic/triggered full-reconcile backstop.
- **`transaction_key` stability** — the whole identity model depends on it; DH sign-off still blank. Push DH.
- **E** (sync-status content axis, not just row count) + **F** (refresh mode/reason UX).
- **Delta-vs-full parity harness** — the core invariant has no test yet; gated by **T1** (DB isolation).
- `docs/co-stock-architecture.md` (`4f567ff`) is committed but **not pushed** — push when user asks.
