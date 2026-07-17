# Session 2026-07-17 — Codebase audit + BOM :batch modified_for_case fix

## Context / why this session happened

The maintainer reported feeling overwhelmed — not grasping the logic/code of a
codebase built at very high velocity with AI assistance (~450 commits since
2026-04-25, peaking 44/day). He was the reviewer/approver, not the author. Ask
started as "is there a skill/agent that reviews + refactors" and evolved into
"assess whether the codebase is actually in trouble" + "I need comprehension,
not to code by hand."

Key framing decision (advisor consult, run on **fable** per user rule): the
overwhelm was produced by throughput, not by missing docs (repo already has
~26k lines of `.ai/` docs). More docs is the wrong prescription. Comprehension
comes from *construction/active reconstruction*, not consumption. Delegating a
one-time **assessment** is legitimate; delegating the *fixing* perpetuates the
approver gap.

## What Was Done

### 1. Three-axis codebase audit (parallel general-purpose agents)
Verdict: **system is sound — no rot, no corruption risk, no data-loss bug.**
The valuable output is the ranked findings list (below) + the large "verified
CLEAN" list.

**Verified CLEAN (as important as the findings):**
- No SQL injection across 474 query sites (one exception, S3 below).
- JWT/SSO correct: EdDSA pinned, no alg-confusion, iss/exp/aud verified,
  service tokens re-checked against DB + jti blacklist each call.
- **Migration redefinition chains CLEAN** — traced every multiply-defined PG
  object (`materials_propagate_on_insert` 058→069→071→093;
  `materials_propagate_staleness` 053→057→069→071; `v_material_roles` 6 defs
  033→…→091; `v_material_classification` 078→079→091; `bom_mark_stale`
  053→054; `has_drift_remaining` 071→077). No silent revert. The hazard
  STATUS warned about did not occur.
- `customs_relevance` 3-home duplication is byte-identical + parity-locked
  (NOT drifting).
- Data writes atomic (single-txn migrations); zip-slip clean; no command
  injection; no committed secrets; every route guarded; client scoping
  server-side.

**Findings (ranked; ✅=fixed this session, 📋=existing issue, 🆕=unfiled):**

Tier 1 — worth acting on:
- ✅🆕 **C1 = finding 2** — `:batch`/`bom/artifacts` default path leaked
  `modified_for_case`, diverging from `/bom/latest`. **Fixed, issue #47, PR
  #48.** (details §2)
- 📋 **S1 = #26** — `/v1/hub` fails OPEN on fresh/restored DB. Code default
  permissive; prod closed only by a hand-set `hub.app_settings` row, no
  seeding migration, fallback branch still in `_require_token`
  (`api.py:68-108`). Every new agency install starts wide open. **Highest
  real risk.**
- 🆕 **C3** — `GET /v1/hub/products` silently truncates to 50 (store default
  `limit=50` `stores/bom.py:544`; handler passes no paging `api.py:1698`), no
  cursor. A consumer enumerating products then fanning into `:batch` misses
  products 51+. Growatt & Johnson both >50. **Verified.**
- 📋 **C2 = #28-D3** — float `normalized_hash` drift CONFIRMED (proven live):
  ingest rounds half-even (`stores/bom.py:79`), DB stores half-up
  (`numeric(20,9)`), refresh re-hash reports unchanged BOM as changed →
  false staleness / version churn.

Tier 2:
- 🆕 **S2** — no rate limit on `/login` + `/v1/auth/token` (argon2 64MiB/89ms;
  brute-force + cheap 4-worker DoS). No nginx `limit_req`.
- 🆕 **S3** — stored SQLi: `client_parser_rules.source_field` spliced unbound
  into SELECT (`clients.py:489,511`); dev-role only, but agent proved it live
  (leaked admin argon2 hash into HTML). Allowlist `source_field` + DB CHECK.
- 📋 **C6 = #37** — BCCT identity resolver serves dead materials
  (`bcct_material_identity.py:133`, no status filter) vs `/v1/hub/materials`
  alive-only. Latent until first tombstone. Ready-for-human, may be intended.
- 📋 **D3 relates to #46** — the #46 functional index CANNOT be built as a boot
  migration: `apply_migrations` runs all pending in ONE txn → forbids `CREATE
  INDEX CONCURRENTLY`; plain build locks 112k-row `bcct_rows` during deploy.
  Run #46 out-of-band with CONCURRENTLY, not as a boot migration.
- 🆕 **C8** — UI preset-create 500s: `bom.py:1754` subscripts a frozen `User`
  dataclass (`user["user_id"]` vs `.user_id`). Fails closed, broken feature.
- 🆕 **S4** — `hub:read` service tokens can perform `/v1/hub` preset writes
  (`api.py:1810,1895,1942` — `_require_can_edit_client` checks client
  whitelist, never scope). Should require an explicit write scope.

Tier 3 (known/minor/by-design): 📋 S7=#29-a CSRF absent (LOW —
`SameSite=Lax` mitigates); 🆕 S5 open redirect `/settings/theme|lang`; 🆕 S6
session cookie `Secure` off unless `DATA_HUB_FORCE_HTTPS_COOKIE=1` (Cloudflare
HTTPS-only mitigates); 🆕 D1 mig 092 truncate+boot-backfill coupling not
enforced; 🆕 D2 no advisory lock in migration loop (prod `--workers 1` immune;
`--workers>1` races); 📋 C5=#28-D5 SAP indented-walk L4→L2 level-skip
(mechanism confirmed, no current prod data triggers); C7 by-codes case-fold
asymmetry (relates #46); C4 `/bom/latest` 409-dual-source vs `:batch`
returns-both (design-ambiguous).

### 2. Finding 2 fix (issue #47, PR #48)
Root cause: `_apply_bom_artifact_filters` (`app/routes/api.py:1248`) gated the
`modified_for_case` case-scoping on `intents is not None`. A default call
(no intents/case_id) skipped the whitelist, the case-scoping, AND the
`case_id_required` guard — all three coupled to that one condition — so an
unscoped `modified_for_case` artifact won the `latest_per_variant` partition.
Fix: un-gate `_scope_ok` so it runs on every path (no-op for other intents).
Shared filter → `:batch` and per-product `/bom/artifacts` stay in parity.
- Test-first: `test_bom_artifacts_picker_filter.py::test_default_call_never_surfaces_modified_for_case`
  (red on `PB_v5` leak → green).
- Full suite: **1611 passed, 16 skipped.**
- **Cross-repo verify:** CO calls `:batch` with explicit `intents=PICKER_INTENTS`
  + `case_id` (`barry-CO-main/app/bom_service.py:245`), never the default path
  → **CO unaffected.** Severity revised HIGH→MEDIUM (latent).
- Changelog: `CHANGELOG.md [Unreleased] ### API` (VN) + `docs/API_CHANGELOG.md`
  2026-07-17 Additive (silent).

### 3. Test DB hygiene (conftest sweep)
User flagged tests leaving junk in the DB. Root cause: local tests default to
`postgresql:///data_hub` (the shared dev DB); only CI overrides
`DATA_HUB_DATABASE_URL`→`data_hub_test`. Killed/timed-out runs skip fixture
teardown → random-suffixed clients accumulate (**547 junk vs 6 real** found).
- Deleted 547 (`client_id ~ '-[0-9a-f]{8}$'`); FK ON DELETE CASCADE (27/28
  child tables) cleaned children. Real clients + growatt/johnson 105k
  bcct_rows intact.
- `tests/conftest.py` now runs `_sweep_test_junk_clients()` at session
  start + teardown. Verified: post-run DB = 6 clients, 0 junk.
- Real/stable clients that never match the regex (do not delete):
  `growatt-vn`, `johnson-vn`, `demo-furniture`, `nxt_tier_test`,
  `sa-test-allowed`, `sa-test-blocked`.

## Decisions Made
- **Assessment delegated, fixing not.** Ran the audit as a one-time assessment
  to bound the unknowns; comprehension itself stays with the maintainer via
  guided walkthrough (did finding 2 as a live Socratic trace before he opted
  to skip the rest).
- **Advisor must run on fable** (user rule, saved to memory).
- **Branch, don't commit to main.** Push to `main` auto-deploys prod, so work
  landed on `fix/bom-batch-modified-for-case-scoping` for a PR.
- **API change classified Additive** (silent) not Breaking: no sister app must
  act (CO passes explicit intents+case_id). Follows the 2026-07-11 alive-only
  precedent.
- **Two focused commits** (fix vs test-hygiene), no Co-Authored-By trailer.

## What Didn't Work
- First advisor launch inherited Opus; user required fable → stopped + relaunched.
- Correctness audit agent returned meta-commentary instead of findings on first
  completion; had to re-message it (and a child agent) for the actual list.

## Open Items
1. **PR #48 — merge PENDING CI.** User authorized "merge đi"; at handoff time
   Docker build + Test were still `pending` (state UNSTABLE). A background
   `gh pr checks 48 --watch` was running. **Next: when green, `gh pr merge 48
   --squash` (or merge), then it auto-deploys prod — verify
   `https://ttdatahub.tinsu.ai/version` shows the new git_sha + `/healthz` 200.**
   If CI red, do NOT merge; show the failure.
2. **After merge:** `[Unreleased]` API note ships but version stays 0.21.0
   (merge doesn't bump). Decide whether to cut `v0.21.1` (changelog rule).
   Consider a `/security-review` pass since #48 touches `/v1/hub`.
3. **File the unfiled audit findings** (🆕 above) the user wants tracked —
   at least C3 (products truncation), S2 (rate limit), S3 (parser-rule SQLi),
   C8 (preset-create 500). Others map to existing #26/#28/#37/#46.
4. **Top real work from audit**, ranked: S1/#26 (fail-open, highest risk) →
   C3 (products truncation, live) → #46 (index, run CONCURRENTLY out-of-band) →
   S2/S3 (security). The 4 issues the user earlier agreed to file were the
   pre-audit set; the audit expands the list.
5. **Comprehension thread** — the maintainer wants to understand the ~5
   load-bearing seams (`/v1/hub` auth gate, BOM latest-vs-batch CO contract,
   migrate-at-boot pipeline, staleness triggers, ingest/hash path) via guided
   Socratic walkthroughs on real code, no hand-coding. Finding 2's trace
   covered the BOM latest-vs-batch seam. Four seams remain if he wants them.
6. **Stronger test-DB fix not done:** point local runs at `data_hub_test` like
   CI so tests never touch the dev DB. Offered; user chose the sweep for now.
