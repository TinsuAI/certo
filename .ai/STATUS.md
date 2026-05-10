# Project Status

**Date:** 2026-05-13 — Phase 3 G refresh-preview shipped + 3 small backlog
items closed (BOM auto-detect, manual_flat 4-shape, UI tombstone rename).
12 commits on `main` ahead of `origin/main`, working tree clean.

## Current State

**Branch:** `main`, ahead of `origin/main` by 12 commits, working tree clean.
**Tests:** 978 passed, 15 skipped, 0 fail (baseline 953 → +25 this session).
**Migrations:** at mig 058 applied (no new migration this session — Phase 3 G
reused `hub.bom_audit_events` from mig 006 instead of creating a new table).
**Dev server:** running on `:8754` (uvicorn auto-reload, bg task `ba0m8ewqn`).

Phase 3 G brief at
`.ai/features/2026-05-13-bom-refresh-preview/brief.md`. Done criteria all
ticked. Three-small-items brief + UI smoke screenshots at
`.ai/features/2026-05-13-three-small-items/`.

## Recent Changes — files touched this session

```
NEW code:
  app/templates/clients/bom_refresh_preview.html  (Phase 3 G preview)
  scripts/screenshot_refresh_preview.py           (Playwright smoke)
  scripts/smoke_three_small_items.py              (Playwright smoke for 3 items)

MODIFIED code:
  app/stores/bom.py                  (BomShape literal + bom_shape() 4-shape;
                                      list_artifacts_for_product exposes
                                      has_uom_drift + uom_drift_reasons)
  app/stores/bom_staleness.py        (plan_refresh, commit_refresh,
                                      refresh_artifact wrapper, RefreshPlan
                                      + PlanRow TypedDicts)
  app/routes/bom.py                  (GET /refresh/preview route +
                                      POST extensions skip + inline_factor;
                                      auto profile in upload route)
  app/templates/clients/bom_artifact_detail.html  (POST→GET preview swap;
                                                    VN tombstone field labels)
  app/templates/clients/bom_artifacts.html        (VN tombstoned label)
  app/templates/clients/bom_presets.html          (VN retract dialog)
  app/templates/clients/_bom_macros.html          (manual_flat shape badge;
                                                    VN lineage marker)
  app/templates/clients/catalog_detail.html       (VN button + dialog +
                                                    badge + status select)
  app/templates/clients/catalog_material_edit.html (VN status select labels)
  app/templates/clients/catalog.html              (VN badge + tooltip)
  app/templates/clients/bom_upload.html           (auto profile dropdown)
  app/i18n.py                                     (VN values for
                                                    status.tombstoned and
                                                    bom.stale.dim.btp_bom_tombstoned)

NEW tests (+25):
  tests/test_bom_refresh_plan.py                  (10: plan + commit)
  tests/test_bom_refresh_preview_route.py         (4: GET preview)
  tests/test_bom_refresh_post_extensions.py       (4: POST skip/edits/no-op)
  tests/test_bom_shape_function.py                (5: 4-shape contract)
  tests/test_bom_flexible_flow.py (+2)            (auto profile)

NEW docs:
  .ai/features/2026-05-13-bom-refresh-preview/brief.md
  .ai/features/2026-05-13-bom-refresh-preview/screenshots/01_preview_mixed_tiers.png
  .ai/features/2026-05-13-three-small-items/brief.md
  .ai/features/2026-05-13-three-small-items/screenshots/*.png  (5)

UPDATED docs:
  .ai/BACKLOG.md                                  (4 entries struck through:
                                                    Phase 2 main, Phase 3 G,
                                                    auto-detect, manual_flat
                                                    shape, UI tombstone rename)
  .ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md
                                                  (Done criteria ticked)

UPDATED memory:
  feedback_reuse_audit_events.md  (NEW — reuse hub.bom_audit_events)
  project_bom_3_shapes.md         (3-shape → 4-shape)
  MEMORY.md                       (new index entries)
```

## Architecture LOCKED this session (don't relitigate)

- **plan_refresh / commit_refresh / refresh_artifact** in `bom_staleness.py`:
  - `plan_refresh()` is the pure planner. No DB writes. Returns `RefreshPlan`
    with `rows[]` (per-row plan: source_qty/uom, target_uom, factor,
    factor_source, status), `drifts[]`, `would_be_hash`, `has_blocking`,
    `skipped_reason`. Status enum: `ready | unconfirmed_default |
    blocked_no_factor | blocked_catalog_missing`.
  - `commit_refresh()` re-plans at top (TOCTOU defeat), supports
    `skip=True` (writes `event_type='refresh.skipped'` into existing
    `hub.bom_audit_events` — NOT a new audit table), `edits=[…]`
    (upserts `client_uom_overrides` rows before commit).
  - `refresh_artifact()` is a thin wrapper for back-compat.
- **GET `/clients/{cid}/bom/artifact/{aid}/refresh/preview`** is the
  default human path; direct POST `/refresh` still works for tests +
  curl. Stale + drift blocks on artifact_detail.html link to GET
  preview.
- **No-op detection**: when `plan.would_be_hash == artifact.normalized_hash`,
  preview swaps CTA to "Xác nhận đã xem"; POST confirm clears flag
  without minting a new artifact.
- **Concurrent factor edit policy**: last-write-wins (no optimistic
  lock). Decision in brief 5.
- **4-shape model** for BOM: `raw_graph | manual_flat | shallow |
  full_flat`. `manual_flat_as_provided` is a SOURCE artifact, no
  longer conflated with derived `shallow`. Memory updated.
- **Reuse `hub.bom_audit_events`**: when adding event tracking, default
  to a new `event_type` value on the existing table — not a new table.
  Memory `feedback_reuse_audit_events.md` captures the rule.

## Next Steps

Per backlog priority + session work landed:

1. **Push 12 commits to `origin`** — user discretion. Branch is
   ahead by 12 (was already several pushed earlier this calendar week
   per git log, then this session added 12 more — but `origin/main`
   shows ahead by 12 only, so something pushed in between).
2. **Update STATUS.md when sister apps cut over** — Phase 2 sister-app
   notes already published (`.ai/sister-app-notes/2026-05-12-uom-conversion-cutover.md`)
   but BCQT/CO haven't adopted yet; behaviour diverges until they do.
3. **Send `agency_qa_johnson.xlsx` to Johnson** (Phase 2 step 9 — agency-blocked).
4. **Johnson programmatic bulk re-ingest** (BACKLOG, ~1d). Now
   doubly-unblocked by Phase 2 + Phase 3 G.
5. **`v_material_roles` paren-aware** (~1-1.5d) — proper fix for the
   `material_observations.py` workaround.
6. **Phase 2 catalog `roles[]` multi-role** (~2-3d) — drop single-value
   `category` column; encode multi-role per memory
   `project_bom_code_multirole.md`.
7. **Unified import UX across all data-import surfaces** (~1 week) —
   bigger; defer until smaller items drained.

## Blockers

None hard.

Soft (carry-over):
- Johnson factor population needs agency response (Phase 2 step 9).
- Sister apps haven't adopted Phase 2 schema (sister-app notes posted
  2026-05-12; consumer reads may produce different output until they
  update).

## Notes for Next AI Session

**Read first:**
1. This `STATUS.md`
2. `.ai/sessions/2026-05-13-refresh-preview-and-small-items.md` (this session)
3. `.ai/features/2026-05-13-bom-refresh-preview/brief.md` (Phase 3 G spec)
4. `.ai/features/2026-05-13-three-small-items/brief.md` (3 small items recap)
5. Memory `feedback_reuse_audit_events.md` (don't propose new audit tables)
6. Memory `project_bom_3_shapes.md` (now 4-shape, not 3)

**UI smoke harnesses** — re-runnable Playwright walks:
- `scripts/screenshot_refresh_preview.py` — Phase 3 G preview screen
  with mixed Tier A/B fixture. Wipes + re-seeds growatt-vn artifact
  `TEST_TP_REFRESH_PREVIEW`.
- `scripts/smoke_three_small_items.py` — 5 visible checks for the
  three small items. Outputs to
  `.ai/features/2026-05-13-three-small-items/screenshots/` (overwrites
  committed evidence on re-run).

**Auth fixture for smoke**: `admin@data-hub.local` / `admin123`
(role=dev). Live client `growatt-vn`. Login form uses
`form:has(input[name="password"]) button[type="submit"]` selector to
avoid global header buttons.

**User preferences captured this session:**
- Push back on over-engineering: when proposing a new DB table, search
  the codebase for existing audit infra first. User caught the unneeded
  `hub.refresh_skip_audit` proposal — reuse `hub.bom_audit_events`
  instead.
- "test bằng UI đi, đừng chỉ chém gió" — running tests is necessary
  but not sufficient; drive the UI for visible features and capture
  evidence. Brief progressed from "do TDD" to "verify in browser
  before claiming done".
- Vietnamese with full accents preferred when responding in VN.
- Bundle-execute is the default for review fixes (per memory
  `feedback_bundle_rev_fixes.md`); user picks which to defer.

**Demo server (tinsu)** — NOT updated this session. Phase 3 G + 3
small items on `main` local only. Per memory `reference_demo_server.md`,
demo is at `http://100.84.189.87:8754`, clone `/home/tinsu/data-hub`,
repo `TinsuAI/data-hub`.

**Migration state:** at mig 058 applied (59 total). No new migration
this session — `hub.bom_audit_events` already had the right shape for
the `refresh.skipped` event.
