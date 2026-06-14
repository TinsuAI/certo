# Project Status

**Date:** 2026-06-14 — **v0.14.0 cut**; UI redesign + Vietnamese sweep + admin
nav + adapter-binding fix bundled in **PR #4** (`feat/ui-redesign-vi-sweep`),
merging to `main` (→ auto-deploys prod). Plus an important correction to the
prod/declarability state recorded below.

## Current State

**Release 0.14.0** (`pyproject` bumped 0.13.1 → 0.14.0). CHANGELOG `[0.14.0]`
folds in everything live-but-unreleased since 0.13.1: PR #2 (declarability,
mig 078/079), PR #3 (adapter module-mgmt, mig 080/081), and this session's
PR #4 work.

**PR #4 — `feat/ui-redesign-vi-sweep`** (4 commits): G.2 adapter-binding fix
(tree adapters via binding/dropdown now route through raw_graph, not flat-stash),
G.1 shared grouped admin sub-nav, clients-page search + top-nav user menu +
Vietnamese sweep of high-visibility surfaces, docs. Suite **1480 passed / 16
skipped**. Briefs + screenshots under `.ai/features/2026-06-14-nav-redesign/` and
`.ai/features/2026-06-14-clients-topnav-vi-sweep/`.

**⚠️ Correction — CD deploys PROD, and prod ALREADY has mig 078–081.** The
earlier STATUS claim that 078/079 were "gated, not yet applied to prod" was
**wrong**. Facts (verified 2026-06-14):
- `docs/release-engineering.md:84`: prod = `https://ttdatahub.tinsu.ai` =
  the `/home/tinsu/data-hub` docker stack the CI **Deploy** job rebuilds.
- The `deploy` job fires on **push to `main`** (i.e. after every PR merge) — the
  `runs-on: data-hub-demo` label is the runner's name, NOT the target; it deploys
  **prod** (and then best-effort refreshes the `tinsu-deploy` nightly *demo* stack).
- `app/main.py:89` runs `apply_migrations()` at app boot → each deploy applies
  pending migrations to the **prod DB**.
- The PR #2 and PR #3 merges (2026-06-13) both ran `Deploy to tinsu: **success**`
  → **prod already applied mig 078–081** that day.
- ⇒ Declarability schema + johnson `client_material_group_map` seed + classification
  are **live on prod**. User-facing impact is still **zero** because
  `exclude_non_declarable` is **default-OFF**. The separate backfill
  (`scripts/backfill_johnson_material_group.py --apply`) is **not** a migration and
  has **not** run on prod yet.

**PR #4 adds NO new migrations** (latest is 081, already on main) → merging it
applies nothing new to the prod DB; only UI/i18n/bom-routing code ships.

## Next Steps

1. **Merge PR #4** → `main` push → CI **Deploy** redeploys prod (v0.14.0). Watch
   the deploy job to green. Optionally tag `v0.14.0` on the merge commit.
2. **Declarability rollout — decide on the backfill** (schema already on prod,
   default-OFF): whether/when to run `backfill_johnson_material_group.py --apply`
   on prod (idempotent, import-aware; key check after: rows with
   `excluded_at is not null and customs_relevance='declarable'` **must be 0**).
   Then **CO adoption** (swap `is_bom_technical_noise` → DH `customs_relevance`,
   `.ai/sister-app-notes/2026-06-09-co-consumer-spec-declarability.md`); only after
   CO is on it, flip `exclude_non_declarable` for johnson-vn.
3. **Outage ops follow-up:** after ~**20/06** confirm pre-fix appfiles tars pruned
   via GFS (`~/logs/verify-old-tars.log` self-removes when clean; raises
   `ALARM-PRUNE-CHECK` if GFS failed).
4. **Backlog, unblocked:** B.0b rename `material_group` → `item_type_token`;
   A.0 RD07 drawing name-level auto-hide; D.2 BOM staleness fingerprint (needs
   A.4.4 `classify_uom_relation` first). Language follow-up: deep BOM-flatten
   vocabulary + admin-staff sentences (see clients-topnav-vi-sweep brief).

## Notes for Next AI Session

- **CD = prod deploy.** Any merge to `main` redeploys `https://ttdatahub.tinsu.ai`
  and applies pending migrations at boot. Treat every merge as a prod release:
  per the standing rule, **update `CHANGELOG.md`** (and `docs/API_CHANGELOG.md`
  if the `/v1/hub` surface changed) and bump `pyproject` version when cutting one.
  The nightly **demo** stack (`/home/tinsu/tinsu-deploy`, DH :8764) is refreshed as
  a secondary best-effort step in the same job.
- **Migration gotcha:** any client-specific seed in a migration that FKs to
  `hub.clients` MUST be guarded `where exists (select 1 from hub.clients …)` —
  CI/fresh installs apply migrations before clients are seeded. Precedent:
  mig 036/037 (growatt), 078 (johnson).
- **Throwaway-DB repro** (CI's fresh DB): `sudo -u postgres createdb -O vp <db>`;
  pre-create `vector` + `pg_trgm` as `postgres`; then
  `DATA_HUB_DATABASE_URL=postgresql:///<db> uv run python -c "from app.database
  import apply_migrations; apply_migrations()"`. `psql` does NOT read
  `DATA_HUB_DATABASE_URL` — pass the dbname explicitly.
- **Branch convention:** `main` uses **merge commits** for PRs (PR #1–#4);
  `delete_branch_on_merge` is **off** (delete manually).
