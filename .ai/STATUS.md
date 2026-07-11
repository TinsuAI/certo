# Project Status

**Date:** 2026-07-11 — **Catalog rework COMPLETE (phases 0–5):** #30 (PR
#41), #32 (PR #42), #33 (PR #43), #34 (PR #44), and **#35 bulk approval**
(PR #45, merge `297f775`). All merged, deployed, prod-verified, and
shipped as **release `v0.21.0`** (commit `d58e4e8`, tag `v0.21.0`).
Session logs: `.ai/sessions/2026-07-11-catalog-phases-0-2-3-4.md` and
`.ai/sessions/2026-07-11-catalog-bulk-approval.md`.

## Current State

- **Prod healthy — on `v0.21.0`, verified 2026-07-11 ~15:53Z.**
  `ttdatahub.tinsu.ai/version` → `version=0.21.0`, `git_sha=d58e4e8`;
  `/healthz` 200. mig 093 applied at boot. Prod oracle unchanged from #34:
  `hub.catalog_discovery('growatt-vn')` pending = 3,306, `bcct_nb_codes` =
  35,349. **No bulk-accept executed against prod** — the button is live
  for an operator to press.
- **Release `v0.21.0` (2026-07-11)** bundles catalog phases 0–5.
  `pyproject.toml` + `uv.lock` = 0.21.0; CHANGELOG `[Unreleased]` rolled
  to `## [0.21.0] — 2026-07-11`; tag pushed; `/whats-new` renders it.
  `[Unreleased]` is now empty.
- **#35 bulk approval live:** discovery page has filter-as-rule (leaf /
  source chips / observed_count / machinery toggle) + «Duyệt N mã đang
  lọc». mig 093 = D9 trigger guarded by `hub.bulk_load` GUC +
  `hub.materials_propagate_bulk` (batched staleness, parity-tested).
  Growatt leaf rule → 2,156 approvable. Deviation flagged (not certified):
  source filter is single-select, not multi-select `sources[]`.
- **customs_relevance still lives in 3 places** (view + 2 inline mirrors,
  parity-tested) — unchanged by #35, which only reads/filters it.
- **The catalog now has ADR-0001's three homes:** pending =
  `hub.catalog_discovery(client)` set-returning SQL function (mig 092,
  ~0.6–1.3s/client, page 1.8s live); rejected = `hub.catalog_rejections`
  (by string, ships in promotion bundle); accepted = `hub.materials` row
  (source derived from originating stream). No candidate_id anywhere —
  routes/templates key on (code, code_kind).
- **Machinery marking live:** placeholder-only codes (207 Growatt) carry
  `customs_relevance='excluded_non_material'` through all three surfaces
  (view + 2 inline mirrors, parity-tested) and through the discovery
  output for #35's default filter. Deviation from issue text (207/11 vs
  210/8): 3 direct-declared codes spared by design — user has not
  explicitly certified, see session log decision 1.
- **`hub.bcct_nb_codes`** (mig 091, widened mig 092): persisted paren
  extraction incl. unified self-links; delete-and-rebuild ~2-3s; triggers =
  BCCT apply, 6 rule-edit routes, promotion import, «Làm mới» button, boot
  backfill-if-empty. `v_material_roles` (6th def) joins it — paren-only NB
  codes finally show observations (A.5 closed; `material_observations.py`
  deleted).
- Full suite green: **1591 passed, 16 skipped**.
- Dev server on :8754 runs merged main code (left running).

## Next Steps

1. **Decide #37** (user, ready-for-human): dead materials in CO's BCCT
   identity payload (`bcct_material_identity.py:120-133`) — hide (apply
   #31 predicate) vs document-and-keep.
2. **#35 follow-up:** source filter multi-select (`sources[]`) — decide
   if wanted (deferred, PR #45 note).
3. Housekeeping: `docs/agency-staff-guide` branch (385-line VN guide,
   nowhere else) — PR or drop; `v0.19.0` tag absent; prod Postgres
   collation-version mismatch (REINDEX + REFRESH COLLATION VERSION in a
   maintenance window — data-integrity investigation, not quick).
4. Remaining ready-for-agent backlog (non-catalog): #23 B.5, #22 B.4,
   #21 B.2, #19 B.0b, #14–18 A.x, #26 C.2, #29 E.4.

## Notes for Next AI Session

- **Read this file and the last 2-3 session summaries BEFORE touching
  anything.**
- **customs_relevance lives in 3 places** — `hub.v_material_classification`
  + inline mirrors in `app/routes/api.py` (`_MATERIALS_SELECT_WITH_ROLES`)
  and `app/routes/catalog.py` (`_query_materials`).
  `tests/test_customs_relevance_parity.py` locks them; touch all three or
  the parity test goes red.
- **Discovery router registers BEFORE catalog in main.py** — its fixed
  `/catalog/candidates/*` paths must beat catalog's
  `{material_code:path}` patterns. Don't reorder.
- **Editing an applied migration locally:** delete its
  `hub.schema_migrations` row, drop the object, re-run
  `apply_migrations()`; after any 092 re-apply, refill via
  `backfill_if_empty()` (092 truncates `bcct_nb_codes`).
- **`create or replace function` must start from the LATEST prior
  definition, not the original.** The D9 insert trigger
  (`materials_propagate_on_insert`) was defined in mig 058, redefined in
  069 + 071, guarded in 093. A rebuild from an older body silently
  reverts later logic — `git grep "function hub.<name>"` for every def
  first. Parity/behaviour tests catch it (069/071 has_drift_remaining).
- **Batching around a per-row AFTER trigger:** `SET LOCAL
  hub.bulk_load='on'` no-ops the D9 trigger (mig 093 guard); run
  `hub.materials_propagate_bulk(client, codes)` once after the bulk
  insert. Works for a non-superuser and is pool-safe (txn-scoped).
  `session_replication_role` needs superuser (denied); `DISABLE TRIGGER`
  needs ownership + ACCESS EXCLUSIVE lock.
- **Multi-referenced CTEs in views are materialized** — client predicates
  do NOT push down. EXPLAIN first; prefer a set-returning function
  parameterized by client (the `hub.catalog_discovery` precedent).
- **Restarting the dev server:** `pkill -9 -f "uvicorn app.main:app --host
  127.0.0.1 --port 8754"` kills the master but its 4 workers keep the port.
  Then `kill -9` the PIDs from `fuser 8754/tcp`, confirm `fuser` exits 1,
  then launch `exec uv run uvicorn app.main:app --host 127.0.0.1 --port
  8754 --workers 4` as a background task. Don't touch :8001/:8014.
- **Auth surfaces split:** `/v1/auth` public, `/v1/hub` guarded; error
  responses centralized in `app/main.py` handlers; never widen refresh
  scope; single-use consume pattern for sso codes/refresh (see
  2026-07-10/11 session logs).
- **Merge auto-deploys prod** (runs migs at boot via lifespan + backfills).
  Update CHANGELOG before merging; API_CHANGELOG only if `/v1/hub` surface
  changed (this session: no API surface change). `[skip ci]` for docs-only
  pushes to main.
- **After `gh pr merge`: `git fetch` then `git merge --ff-only origin/main`.**
- **Real-data E2E auth on dev:** admin password is `admin123` after any
  suite run (conftest resets it).
- **Pre-existing dirty tree is NOT from recent sessions — leave alone:**
  `M .ai/BACKLOG.md`; untracked `.ai/sessions/*` (old ones),
  `docs/training/*`, `scripts/*`.
