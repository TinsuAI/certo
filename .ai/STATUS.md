# Project Status

**Date:** 2026-05-11 — Track D Phase 1 shipped (BOM dependency staleness). 2 commits on `main`: `fc6e776` (Phase 1 base) + `656960c` (polish).

## Current State

**Working tree clean. Branch ahead of origin by 8 commits (not pushed).**

### Track D Phase 1 — BOM dependency staleness (`fc6e776` + `656960c`)

- Mig 053: `is_stale BOOLEAN` + `stale_reasons JSONB` + first/resolved
  timestamps + partial index on `hub.bom_artifacts`. Filter to derived
  strategies only (4: technical_exploded, purchased_btp_as_leaf,
  self_produced_btp_exploded, mixed_confirmed) per immutable principle.
- 5 triggers cover 4 dimensions: D1 catalog category, D7 materials.uom,
  D8 btp_sourcing flip, D2-INSERT BTP raw_graph appears, D2-tombstone
  symmetric.
- Mig 054: `bom_mark_stale` rewrite with `@>` containment dedup (avoids
  JSONB bloat across edit cycles).
- post_ingest_hooks scaffold (existed since Phase 3c, never invoked)
  wired into `app/routes/bom.py:516-543` confirm flow. Hook failure
  marks new artifact stale with `dim=derive_hook_failed`.
- Refresh routes: `POST /clients/{c}/bom/artifact/{id}/refresh` +
  `POST /clients/{c}/bom/{product}/refresh`. Helpers in new module
  `app/stores/bom_staleness.py`. User attribution threaded via
  `triggered_by_user_id` (commit 2 polish).
- UI badges in 3 templates (bom.html aggregate count,
  bom_artifacts.html per-row, bom_artifact_detail.html heading +
  reasons box + Refresh button). 12 i18n keys VN+EN.
- API exposes `is_stale` + `stale_reasons` in artifact endpoint.
- Tests: 820 → 849 (+29). 0 fail, 15 skip.

### Critical real-data finding (verified johnson `0000082212`)

**Refresh button does NOT convert UoM** — only clears stale flag.
`materialize_shallow_and_full_flat.py` SQL bypasses flatten engine,
copies raw `e.uom` from `bom_edges` without consulting catalog UoM
or running conversion. Re-derive produces same hash → idempotent
dedup → returns existing artifact → flag clears, data unchanged.

This is a **Phase 2 gap**, captured fully in BACKLOG. Phase 1 stale
flag still useful — semantic = "warning, please review", not
"convert and re-render".

## Recent Changes — files

```
NEW (across 2 commits):
  .ai/features/2026-05-11-bom-staleness-track-d/brief.md
  app/stores/bom_staleness.py
  db/migrations/053_bom_staleness.sql
  db/migrations/054_bom_mark_stale_dedup.sql
  tests/test_bom_staleness.py
  tests/test_bom_staleness_api_ui.py
  tests/test_bom_staleness_refresh.py
  tests/test_post_ingest_hooks_wiring.py

MODIFIED:
  .ai/BACKLOG.md            (+284 lines: 2 new entries, see below)
  app/i18n.py               (+12 keys VN+EN: bom.stale.*)
  app/routes/bom.py         (+90: hooks wire + 2 refresh routes)
  app/stores/bom.py         (+is_stale/stale_reasons in 3 SELECTs)
  app/templates/clients/bom.html             (per-product n_stale badge)
  app/templates/clients/bom_artifact_detail.html (heading + reasons + refresh form)
  app/templates/clients/bom_artifacts.html   (per-row stale marker)
```

### BACKLOG additions (planning, not code)

**1. "BOM UoM conversion engine (ingest-time + refresh-time)"** —
   Phase 2 scope (1.5-2 weeks + 1-2d discovery). 4 sub-tasks:
   - A. Ingest-time conversion preview (BOM + BCCT) with staff
     confirm/edit factor inline.
   - B. Refresh wire flatten engine (replace raw SQL derive).
   - C. `hub.material_uom_factors` table + admin UI for cross-family.
   - D. Conversion audit trail.

   Plus Phase 3 follow-ups (after Phase 2 ships):
   - E. Manual_flat artifacts need UoM drift signal (separate from
     `is_stale` — they're source, can't re-derive).
   - F. Refresh = mint new + supersede old, not mutate (per immutable
     principle). Currently clears flag without tombstoning old data.
   - G. Transparency reinforcement: no auto-apply silent at ingest
     OR refresh; staff confirm every conversion event.

**2. "Johnson programmatic bulk re-ingest plan"** — full spec for
   `scripts/bulk_reingest_johnson.py` (3 phases: wipe / ingest /
   verify). Pre-MVP reset, blocked on Phase 2. ~1 week effort.

## Next Steps

Per `BACKLOG.md` priority:

1. **Push to origin** — 8 commits ahead, not yet pushed. User
   discretion.
2. **Phase 2 UoM conversion engine** (1.5-2 weeks) — primary unblocker
   for Refresh actually converting + bulk re-ingest plan.
3. **v_material_roles paren-aware** (~1-1.5d) — proper fix replacing
   `material_observations.py` workaround.
4. **UoM admin UI polish** — deferred 2026-05-10 AM.
5. **Phase 2 catalog** — `roles[]` + drop `category`.
6. **Wipe + re-ingest fresh Growatt + Johnson** — pre-MVP reset
   (blocked on Phase 2).

## Blockers

None hard.

Soft (carry-over):
- Refresh doesn't convert UoM (Phase 2 unblock).
- 14 orphan BTPs Growatt (data quality).
- T1-T2/2026 BCCT for Growatt missing.

## Notes for Next AI Session

**Read first** (in order):
1. This STATUS.md
2. `.ai/sessions/2026-05-11-track-d-staleness.md` — full session log
3. `.ai/features/2026-05-11-bom-staleness-track-d/brief.md` — Phase 1 spec
4. `.ai/BACKLOG.md` — entries "BOM dependency staleness" (Phase 1
   shipped), "BOM UoM conversion engine" (Phase 2 + Phase 3
   follow-ups), "Johnson programmatic bulk re-ingest plan"

**Memory updated this session:**
- `project_bom_staleness.md` (NEW) — Phase 1 schema + triggers +
  refresh + Phase 2 gap (refresh-doesn't-convert).

**Architecture LOCKED — don't relitigate**:
- `is_stale` + `stale_reasons` (JSONB) on bom_artifacts. Trigger
  filter: only derived strategies (4) get marked.
- Helper `hub.bom_mark_stale` is the single write path; uses `@>`
  dedup.
- Refresh = "I have reviewed" semantic; conversion is Phase 2 work.
- post_ingest_hooks wired only in non-flatten preview_confirm path.

**Schema evolution to expect:**
- Mig 055+ for v_material_roles paren-aware.
- Mig 056+ for Phase 2 (`material_uom_factors` table + extended
  trigger logic).
- Mig 057+ for Phase 3 follow-ups (refresh-as-new-artifact migration).

**Working-tree state**: clean. Commits `fc6e776` + `656960c` on `main`.
Branch ahead of origin 8 commits — not pushed.

**Migration state**: DB at mig 054 applied (55 total).

**User feedback this session (high-signal):**
- "Convert phải làm từ lúc ingest, không chỉ refresh" → Phase 2 scope.
- "Cross-family case có business demand thật" → `material_uom_factors`
  table required (per-material, no universal formula).
- "Refresh phải tạo BOM mới thay thế, không mutate" → Phase 3 F.
- "Manual flat cũng phải mark stale hoặc mâu thuẫn" → Phase 3 E.
- "Lên kế hoạch ingest programmatically Johnson" → separate BACKLOG.

**Demo server (tinsu)** — NOT updated this session. Track D code on
`main` local only.
