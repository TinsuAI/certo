# Project Status

**Date:** 2026-07-11 (marathon session) — **Catalog phases 0+2+3+4 shipped**:
#30 (PR #41, `4d74819`), #32 (PR #42, `15ad288`), #33 (PR #43, `2f68100`),
#34 (PR #44, `58e1994`). All merged, deployed, prod-verified. Session log:
`.ai/sessions/2026-07-11-catalog-phases-0-2-3-4.md`.

## Current State

- **Prod healthy — verified 2026-07-11 ~06:30Z.** `ttdatahub.tinsu.ai/version`
  → git_sha `58e1994`; `/healthz` 200. Prod oracle: `catalog_candidates`
  dropped, `hub.catalog_discovery('growatt-vn')` pending = 3,306 (exact
  preservation), 1,207 decision tuples in `bom_audit_events`,
  `bcct_nb_codes` = 35,349 (boot backfill self-healed).
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

1. **`/implement #35`** (bulk approval UI — final catalog phase, unblocked
   by #33+#34). **Plan the mig-058 staleness mass-fire** (brief Risk 2):
   bulk-accepting ~2,157 flattened-leaf codes fires the trigger per row —
   batch it or suspend-and-recompute once. Filters come free from
   `catalog_discovery` output (`customs_relevance`, `bom_role`, `sources`);
   `excluded_non_material` out by default; one audit event carrying
   predicate + count + code list; `decided_by` = the operator.
2. **Decide #37** (user): dead materials in CO's BCCT identity payload
   (`bcct_material_identity.py:120-133`) — hide vs document-and-keep.
3. **Release cut 0.21.0** when convenient: CHANGELOG `[Unreleased]` holds 4
   entries; bump pyproject + uv.lock together.
4. Housekeeping: `docs/agency-staff-guide` branch (385-line VN guide,
   nowhere else) — PR or drop; `v0.19.0` tag absent; prod Postgres
   collation-version mismatch (REINDEX + REFRESH COLLATION VERSION in a
   maintenance window — data-integrity investigation, not quick).

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
