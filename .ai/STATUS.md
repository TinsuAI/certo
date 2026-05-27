# Project Status

**Date:** 2026-05-27 — BOM stale-UX rebuild shipped. Cluster-by-cause action queue + audit log split + self-healing reconcile + state column. Local at `5cdf7fe`. **Demo NOT yet synced.**

## Current State

**Branch:** `main` at `5cdf7fe`. Ahead of `origin/main` by 3 commits.

Recent commits:
- `5cdf7fe` — feat(bom): cluster needs-action page replaces /bom/stale
- `99abbec` — feat(catalog): fill placeholder name from BCCT on conflict
- `637046e` — feat(bom): conditional staleness model + state column (migs 067-071)
- `a331c74` — chore(ui): hide notification bell from navbar
- `db0a86f` — feat(declarations): keep #bulk hash on bulk-upload redirects

**Tests:** 1,224 passed, 15 skipped (+38 new + several updated).

**Migrations:** at mig **071** (5 new this session, 067-071).

**Working tree:** clean of code drift relative to HEAD. Untracked items unchanged from prior sessions (training scripts, old session notes, demo-company-feed PNGs).

**Dev server:** `:8754` running (background `nohup … --workers 4`); healthz HTTP 200.

**Demo box (`ttdatahub.tinsu.ai`):** at `bc4fb3b` — **3 commits + 5 migrations behind**. Pending sync.

**Local DB final state (Johnson + Growatt):**
```
Johnson:  10,255 clean  ·  20 needs_input (11 derived + 9 raw)  ·  0 needs_refresh
Growatt:  606    clean  ·  1  needs_input                       ·  0 needs_refresh
```
The 20 Johnson + 1 Growatt all trace to mã `1000469803` (mixed EA/KG BOM); open item awaiting Johnson evidence.

## Recent Changes (this session)

### 1. Stale-UX rebuild (commits `637046e` + `5cdf7fe`)

Audit 2026-05-27 found `/bom/stale` unusable at scale: 1,336 Johnson
rows, 99% non-actionable, engineer jargon, no bulk action. Full
rebuild:

- **Migrations 067–071:**
  - 067 clear stale flag on tombstone.
  - 068 `state` GENERATED column (clean / needs_refresh / needs_input / broken).
  - 069 `hub.is_uom_aligned()` + conditional D7/D9 triggers (skip flag when alias-aligned).
  - 070 backfill round 1 (alias-aligned cleanup).
  - 071 `hub.has_drift_remaining()` (extends alignment with override lookup) + backfill round 2.
  - Net: Johnson 1,336 → 20 actionable.

- **Self-healing:** `reconcile_for_material()` called from catalog edit
  + override CRUD. Cap 50 sync, deferred surface.

- **New UI:**
  - `/clients/{cid}/bom/needs-action` — cluster by (cause × code), bulk
    refresh per cluster, 3 state tabs, pagination.
  - `/clients/{cid}/bom/audit-log` — forensic event log.
  - `POST /bom/refresh-cluster` — bulk refresh up to 200.
  - Legacy `/bom/stale` removed (308 redirect, template + dead helpers
    + dead i18n keys pruned).

- **Vocabulary cleanup:** bom.stale.* dim/tab/action labels replaced by
  bom.state.* / bom.cause.* / bom.action.* in plain Vietnamese (VN + EN).

- **API:** additive `artifact.state` field on
  `/v1/hub/products/{p}/bom` + `/bom/artifacts`. Legacy `is_stale` +
  `has_uom_drift` retained for backward compatibility. Documented in
  `docs/API_CONTRACT.md`. Sister-app notes at
  `.ai/sister-app-notes/2026-05-27-bom-state-field-shipped.md`.

### 2. Provenance name backfill gap (commit `99abbec`)

3,822 Johnson catalog rows have `name=material_code` placeholder
(bom_observed codes never reached BCCT). `derive_from_bcct` on-conflict
path now fills `name` when current value is placeholder. Idempotent.
No backfill source available today (bom_only set disjoint from
BCCT-visible set); patch takes effect on future BCCT ingest.

## Next Steps

Priority order:

1. **Sync demo box** (`ttdatahub.tinsu.ai`) — push origin, apply migs
   067-071 inside data-hub-db-1 container, git pull + docker compose
   build app + up -d app. Verify state distribution matches local.

2. **Memory updates** — reinforce `project_bom_staleness` (state column),
   add `feedback_self_healing_via_reconcile` if useful.

3. **Wait for CO consumer PR** on declaration file status endpoint
   (carry-over).

4. **Re-enable notification bell** when feature finishes — uncomment
   `app/templates/base.html:39`.

5. **Fix CI "Smoke LLM /models (best effort)" step** (carry) — chronic
   401 from `codex-lb-demo.sgnai.dev/v1/models` makes deploy-to-tinsu
   job report failure even when deploy succeeds. Easy fix: append
   `|| true` after the curl, or pass token, or remove the step.

6. **Resolve `1000469803`** — mixed EA/KG BOM, needs Johnson evidence
   (override or catalog correction). 20 stale artifacts depend on this.

7. **70 sản phẩm XK 2026 thiếu BOM** (carry) — get from Johnson or
   document.

8. **CO repo dropdown logic for dual_source 409** (carry).
