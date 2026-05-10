# Session 2026-05-11 — Track D Phase 1 (BOM dependency staleness)

User asked to continue Track D from previous session deferral
(2026-05-10 PM brief, "Track D — DEFERRED" section). Full
discovery → TDD → review → polish → commit cycle in one session.

## What Was Done

### Discovery (~30 min)

Audited 8 staleness dimensions in code via 2 parallel Explore
agents. Key findings beyond BACKLOG draft:

1. `post_ingest_hooks` scaffold (`app/parsers/bom_adapters/__init__.py:
   47-223`) was fully built since Phase 3c — Protocol, HOOKS map,
   runner — but **never invoked from production code**. Half of
   Track D plumbing already in tree.
2. Mig 045 (`materials_audit_trigger`) proves trigger-on-materials
   pattern is comfortable. Adding 1 more trigger safe.
3. 8 dimensions split into 3 categories: easy single-table (D1, D7,
   D8), medium BOM ingest path (D2), hard cross-table cascading
   (D3, D4, D5, D6 — defer to Phase 2).

Wrote brief `.ai/features/2026-05-11-bom-staleness-track-d/brief.md`
with Phase 1 (4 dims) + Phase 2 deferred dims rationale.

### TDD implementation (~2h)

Phase A — Mig 053 + 5 triggers + 14 schema/trigger tests.
- Helper `hub.bom_mark_stale(text[], dim, source_table, source_pk)`
  with derived-only filter.
- D1/D7/D8 single trigger function on materials column updates,
  one trigger fires when any of 3 columns change with WHEN clause
  + DISTINCT FROM (NULL-safe).
- D2-INSERT trigger on bom_artifacts WHERE source_bom_kind='technical_raw'
  marks parents that reference this product_code.
- D2-tombstone symmetric on UPDATE WHERE OLD.tombstoned_at IS NULL
  AND NEW.tombstoned_at IS NOT NULL.

Phase B — Wire post_ingest_hooks in `app/routes/bom.py:516-543`.
- Adapter resolution: profile IS adapter name; for technical_raw,
  parse from `diff_summary.proposed_by="parser_fallback:<adapter>"`.
- Failure handler: log + raw UPDATE marking new artifact stale with
  `dim=derive_hook_failed` (intentional exception to derived-only
  filter, per brief).
- 3 tests (success path, no-op when adapter has no hooks, failure
  isolation).

Phase C — Refresh routes + new module `app/stores/bom_staleness.py`.
- `refresh_artifact(client_id, artifact_id)` — finds raw ancestor
  for derived shape, calls materialize SQL via existing
  `scripts/materialize_shallow_and_full_flat.derive`, calls
  `create_artifact` (idempotent), clears flag.
- `refresh_product` iterates derived artifacts.
- 5 route tests (success, 404, cross-tenant rejection, product-level,
  no-op).

Phase D — UI badges + i18n + API expansion.
- Templates: per-row stale marker on bom_artifacts.html, heading
  badge + reasons box + Refresh form on bom_artifact_detail.html,
  per-product n_stale aggregate badge on bom.html.
- 12 i18n keys VN+EN: `bom.stale.badge`, `bom.stale.tooltip`,
  `bom.stale.heading`, `bom.stale.refresh`, plus 6 dim labels.
- `get_artifact_with_rows` + `list_artifacts_for_product` +
  `list_products_with_bom` SELECT additions.
- 5 tests (API exposure, badge rendering on stale + fresh).

Total: 27 tests, 820 → 847 green.

### Real-data testing (~30 min)

Started dev server on 8754, user tested live with johnson catalog
edit `0000082212` PIECES → KG → PIECES. Surfaced 3 critical insights:

1. **Only full_flat marked stale, not shallow.** Verified in DB:
   shallow's bom_artifact_rows contain BTPs not NVL leaves; trigger
   join misses. **Correct semantic** — shallow doesn't reference
   the changed NVL directly.
2. **PIECES → KG → PIECES still stale, with 2 entries in
   stale_reasons** (same dim+source_pk). No dedup. JSONB bloat
   risk over time.
3. **Refresh doesn't actually convert UoM.** `materialize_shallow_and_full_flat.py`
   SQL multiplies qty through `bom_edges` chain without consulting
   `materials.uom` or `uom_conversions`. Output UoM = whatever raw
   edges stored. Same hash → idempotent dedup → flag clears, data
   unchanged. **Phase 2 gap.**

### /rev (~20 min)

Self-review + critic agent in parallel. 4 findings, user asked
"are these legitimate or hallucinated?". Verified each by reading
actual code:

| # | Claim | Verified | Action |
|---|---|---|---|
| 1 | Hook-fail bypasses derived-only invariant | Per-spec (brief explicit exception) | Skip |
| 2 | Refresh loses user attribution | True | Fix |
| 3 | JSONB bloat | True (verified in DB) | Fix |
| 4 | Hooks not re-run on retry | False (critic mis-read create_artifact dedup return) | Discard |

Critic accuracy: 2/4 (50%). Lesson: even good critics need
verification, especially when they make claims about specific
code paths.

### Polish (commit 2)

- Mig 054: `bom_mark_stale` rewrite with `@>` containment dedup.
  Skip append when same `(dim, source_pk)` already in array.
- Routes/store: thread `triggered_by_user_id` through
  `refresh_artifact` / `refresh_product` / `_rederive_shape`.
  Default actor `'agency_staff'` (was lying `'erp_pipeline'`).
  user_id lands in context jsonb + connection app.user_id.
- 2 tests added: dedup behavior + signature assertion for actor +
  user_id kwargs.
- 847 → 849 green.

### Phase 2 + Phase 3 planning (per user direction)

User insisted: "Note lại hết những cái này để discover phase 2 sau".
Captured 2 BACKLOG entries:

1. **"BOM UoM conversion engine (ingest-time + refresh-time)"** — 4
   sub-tasks (A ingest preview, B refresh wire flatten engine, C
   `material_uom_factors` table + admin UI, D audit trail) +
   3 Phase 3 follow-ups (E manual_flat drift, F refresh-as-new
   artifact, G transparency).
2. **"Johnson programmatic bulk re-ingest plan"** — full spec for
   wipe + ingest + verify script. Pre-MVP reset, blocked on Phase 2.

### Commits + handoff

2 commits on main:
- `fc6e776` feat(bom): track D phase 1 — Phase 1 base + brief +
  BACKLOG additions.
- `656960c` fix(bom): track D polish — mig 054 + user attribution.

8 commits ahead of origin (not pushed per session policy).

## Decisions Made

1. **Phase 1 = 4 dims only (D1, D2, D7, D8).** Hard dims D3/D4/D5/D6
   defer. Rationale: indirect cascading via upstream tables
   (BCCT/parser/uom_aliases) needs broader design + cross-tenant
   ripple analysis.

2. **Mark only derived artifacts stale.** Source raw_graph + manual_flat
   are immutable. Carve-out for `derive_hook_failed` dim (raw UPDATE
   bypass helper) — intentional.

3. **Refresh = clear flag + best-effort re-derive.** Phase 1 scope.
   Not "real conversion" — that's Phase 2. Honest semantic: "I
   acknowledge the change, please review".

4. **Single trigger function for D1/D7/D8.** Cleaner than 3
   separate functions; dim attribution inside the function based
   on which column changed.

5. **JSONB stale_reasons with multi-dim accumulation + dedup.** Each
   `(dim, source_pk)` combination stays unique; first observed_at
   preserved.

6. **post_ingest_hooks wired in same feature.** Scaffold existed,
   wiring it now (not later) closes D2 staleness window for
   sap_indented_walk + multi_sheet_per_root adapters.

7. **API exposes is_stale + stale_reasons but does NOT block reads.**
   Consumer (BCQT/CO) decides tolerance. Block-on-stale would
   break BCQT during catalog edits — unacceptable coupling.

8. **2 commits not 1.** Polish (dedup + attribution) split from
   Phase 1 base for cleaner reviewer surface. Test additions
   surgically split between commits.

## What Didn't Work

1. **Initial commit message draft was bundled.** Took explicit
   surgical revert + re-edit to split tests cleanly. If splitting
   commits, edit the polish OUT of working tree first, commit base,
   then re-edit polish IN, commit polish. Don't try interactive
   add-p.

2. **Test fixture leftovers.** `test_bom_staleness_api_ui.py`
   crashed mid-run on first try due to bad service_account_tokens
   cleanup SQL referencing wrong column. Leftover rows triggered
   UniqueViolation on retry. Fixed by manual cleanup script +
   removing the bad cleanup lines.

3. **`%s::text` cast was needed.** First version of hook-fail
   UPDATE used bare `%s` for source_pk → psycopg
   `IndeterminateDatatype` error. JSONB construction with bare
   string param needs explicit cast.

4. **Critic finding #4 was wrong.** "Hooks don't re-run on retry"
   claim contradicts the actual create_artifact code (returns
   existing id on dedup, truthy, loop appends). Lesson:
   verify-don't-trust even critic agents.

## Open Items

1. **Push to origin** — 8 commits ahead, user discretion.
2. **Phase 2 UoM conversion engine** — main unblocker. Brief +
   BACKLOG fully spec'd.
3. **Demo server (tinsu)** not updated. Track D only on local main.
4. **Memory `project_bom_staleness.md`** — to be written by handoff
   skill.
5. **Stale state on test artifacts in user's local DB**
   (`0000082212` cycle) — will self-heal on Refresh click. No
   manual cleanup needed.
6. **Phase 1 known limitation** documented but staff training
   needed: "Refresh button = I reviewed, NOT convert". Until
   Phase 2, communicate clearly to operations.
