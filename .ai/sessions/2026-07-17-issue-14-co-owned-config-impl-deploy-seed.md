# Session 2026-07-17 — #18 + #14 CO-owned client config: implement → deploy → seed growatt-vn

`/implement` the #14 spec (S1–S4) + #18, TDD per slice, 2-axis code review, browser e2e,
push, deploy, and the growatt-vn onboarding seed on nightly then prod. **5 commits on
`origin/main`**; prod `barry-co` + nightly `demo-co` both at `d74e8fb` (STATUS docs at `6a0639c`).

## What Was Done

- **#18 (`2479111`)** — `allocation_line_matches_stock` (`co_case_context.py:1092`) dropped
  `allocation_code` from the persisted-line→lot match. It is derived + mutable per client config;
  a strategy change re-derives it and orphaned saved allocation lines from their lots. Now matches
  by `source_row`/`decl_no`/`line_no` (strategy-invariant). `tests/test_allocation_line_rebind.py`.
- **#14 (`0f0812f`)** — ownership-partition per the ADR:
  - **S1** `data_hub_client.py`: `get_client_config` = local base + DH `bcct` overlay;
    `save_client_config` writes CO-owned sections locally, rejects a `bcct` edit. DH-supplied
    `co_stock` fields (`min_days_before_export`) preserved while local `lot_policy` wins.
  - **S2** `pages.py`: config route rejects a declaration-type change UP FRONT (before any overlay
    write), then saves allocation/lot_policy — closes the partial-save-then-409 shape.
  - **S3** `co_stock_materializer.py` + `co_case_context.py`: `co_config_fingerprint` (hashes BOTH
    `allocation_code` and `co_stock`, NOT `config_hash`) in `co_stock_refresh_state`
    (**migration 021**, additive col) forces one full re-derivation on mismatch.
  - **S4** `scripts/seed_growatt_vn_allocation.py` (idempotent) + regression test.
  - New tests: `test_co_owned_client_config.py`, `test_config_route_co_owned.py`,
    `test_co_stock_refresh_config_fingerprint.py`; 3 existing refresh-dispatch tests updated.
- **Browser e2e (real CO+DH stack) caught a display bug → fix `d74e8fb`.** The config page AND the
  case-context derivation read `source_summary["client_config"]`, built via
  `normalize_data_hub_client_config` (DH `bcct` + the code default) — so a saved CO-owned strategy
  persisted (via `get_client_config`) but never SHOWED and never reached that derivation path. Fix =
  extract `_partition_merge_config`, shared by `get_client_config` AND `source_summary`. e2e then PASS.
- **Docs** `f240964` (STATUS/DECISIONS/GLOSSARY + the #14 spec + pending `.ai/` artifacts);
  STATUS refresh `6a0639c`.
- **Deploy**: pushed → CI/CD green → prod `barry-co` + nightly `demo-co` both `/version`
  `git_sha=d74e8fb`; migration 021 ran on deploy.
- **Seed growatt-vn** — nightly THEN prod, in-container. Both: strategy → `description_regex`,
  forced full re-derivation `mode=full rows_persisted=38287`, fingerprint `44176834c0abb7b1`
  (identical), **34,388/38,287 (90%) rows now carry dotted internal `allocation_code`**
  (DIOT→008.0035900, PCBA→B700.0141600) vs 4,469 short-code fallback. 4.5% → ~96% BOM-code match
  unblocked on growatt-vn.

## Decisions Made

- **`source_summary` must use the same partition-merge as `get_client_config`.** Both feed the
  display and the case-context derivation; fixing only `get_client_config` left the page/derivation
  on the DH-default allocation. This was the browser-e2e finding — unit tests tested
  `get_client_config` directly and missed the consumer path.
- **Preserve DH-supplied `co_stock` fields (min_days) while local owns `lot_policy`** — beyond the
  literal S1 spec, prevents an eligibility regression (`effective_min_gap_days` fallback).
- **S2 gate moved up-front** (before overlay/`upsert_client` writes) to fully close the
  partial-save-then-error shape the Spec review flagged.
- **Prod seed approved after advisor (Fable 5) verified prod directly**: growatt-vn has **0 cases /
  0 claims / no aggregate-policy `client_configs` row** → the #18 rebind had nothing to orphan;
  `client_configs` empty → `lot_policy=line_level` → `source_row = hash(transaction_key)` is
  strategy-invariant; fingerprint already `''` → next refresh goes full regardless; johnson-vn
  untouched. Rollback is a pure re-derivation: set strategy back + refresh.
- **In-container seed method**: `docker exec -i {co-app-1|nightly-co-app-1} /app/.venv/bin/python -`
  with the logic piped on stdin — `scripts/` is NOT in the Docker image (Dockerfile copies `app/`
  only), and bare `python` lacks `httpx` (deps are in `/app/.venv`). Verified each container's
  `co-db` DNS resolves to its own DB (nightly 172.29.0.2, prod 172.24.0.3) before mutating.

## What Didn't Work / Corrected

- First browser e2e: `waitForNavigation` timeout — a programmatic submit-button `.click()` didn't
  fire a native navigation (JS submit handler). Fixed with native `form.submit()` + `waitUntil:load`.
- Unit tests were green but the config PAGE rendered the stale strategy — the `source_summary`
  consumer path the tests didn't cover. The browser e2e was essential; added a regression test.
- Standards review: 3 fixes applied — middle-man `_dh_client_config` + duplicated store-dispatch
  collapsed into `_local_config_store()`; renamed the `record_refresh_state` param that shadowed the
  module-level `co_config_fingerprint` function.
- Advisor baseline dotted-code count (7,427) differed from mine (1,059) — same snapshot, different
  regex strictness; compared against my own strict-pattern baseline instead. Post-seed 34,388 matched
  nightly exactly.

## Open Items

- **USER manual step (independent of the seed):** flag 2 NCC on growatt-vn
  `/clients/growatt-vn/suppliers` — `CONG TY TNHH MINGJIE VIET NAM` + `CONG TY TNHH MINGHUI VIET NAM`
  (verify spelling vs live BCCT; NEVER the HK namesake `MINGJIE INDUSTRIAL (HK)`).
- **Held back from git (needs cleanup):** `.ai/features/2026-06-20-co-datahub-user-guide/` — its
  screenshot-harness scripts hardcode `/home/vp/...` absolute paths and the dev password `admin123`;
  do not commit until paths → env/relative and the password → env var. Also uncommitted:
  `docs/huong-dan-su-dung/` (image output tree) and `uv.lock` (pre-existing unrelated).
- **Code-vocab batch remaining** (GitHub `TinsuAI/co`): #19 (T2 helper renames), #20 (T3 invariant
  tests + adapter docs), #21 (T4 allocation_code value cleanup — **now unblocked** by S3), #22 (T6
  DH→CO fallback — needs a human keep/tighten/remove decision first).
- **Local dev state:** the Data Hub dev server (`:8754`) was started this session and left running;
  local `barry_co` DB growatt-vn was restored to the `same_as_customs_code` baseline after e2e (not
  onboarded locally, unlike prod/nightly).
- **Rollback for growatt-vn** (if the onboarding ever looks wrong): set `allocation_code.strategy`
  back to `same_as_customs_code` (config UI, now editable in DH mode) + Refresh tồn — fingerprint
  mismatch forces a full re-derivation to the old codes; no case/claim state to unwind.
- **Handoff convention pinned (decision) but not enforced (pending):** session-end = `/v_handoff` only
  (STATUS + `.ai/sessions/`); Pocock's global `/handoff` is a fork-bridge (live-conversation compaction),
  not a session-end tool, and is rarely needed here (harness auto-summarizes). Ad-hoc handoff this session
  (hand-wrote the summary) is the anti-pattern to stop. **PENDING user approval:** edit `CLAUDE.md`
  "Session end: /handoff" → `/v_handoff` + save a `feedback` memory so it's deterministic, not from memory.
