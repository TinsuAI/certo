# Feature: BOM stale-UX rebuild (audit 2026-05-27)

**Date:** 2026-05-27 · **Status:** shipped local (demo sync pending).

## Why

Audit during this session identified the `/bom/stale` page was unusable
at scale: Johnson dev DB showed 1,336 rows under 8 dims × 3 categories,
99% non-actionable. Users could not understand the rows ("tombstone",
"hook", "derive", "1:1 default") and could not bulk-act on them
(no /refresh-all endpoint, no pagination, 1,206 single-row buttons).

Root causes diagnosed:

1. **Source-side `has_uom_drift` is a dead-end flag.** Once raised on
   raw_graph artifact, only re-upload clears. No staff-facing ack.
   Result: every catalog correction permanently flags 1,000+ source
   BOMs that ARE NOT actually drifting.
2. **Triggers fire unconditionally.** D7/D9 mark stale on any catalog
   uom UPDATE regardless of whether NEW.uom actually creates drift.
   Bug fixes (G→EA on `1000430256`) flag BOMs whose actual uom was
   already EA → false positives.
3. **UI bug — `_primary_action` shows "Reupload" for manual_flat**,
   but manual_flat can be refreshed via `_rederive_manual_flat`
   (mig 057).
4. **Tombstoned artifacts retain `is_stale=true`** (2,719 Johnson
   rows). Filtered out of UI but pollute audit queries.
5. **No bulk action.** `/bom/refresh-all-stale` was planned in brief
   2026-05-11 but never shipped.
6. **8 dims → 3 categories → 4 buttons** = too many shapes for staff.
   Labels in i18n use engineer jargon (tombstone, hook, derive_hook_failed).
7. **Rows-per-artifact display**, not cluster-by-root-cause. Same
   catalog uom change → 1,206 separate rows.

## What changed

### Schema (mig 067–071, 5 migs)

- **067** Clear `is_stale`/`has_uom_drift` on tombstone. Backfill + trigger.
- **068** `state` GENERATED column on `bom_artifacts`:
  `clean | needs_refresh | needs_input | broken`. Auto-maintained
  by Postgres from existing flags + reasons jsonb.
- **069** `hub.is_uom_aligned(a, b)` helper + conditional D7/D9.
  Triggers now skip flagging when NEW.uom aliases-with BOM row uom.
- **070** Backfill cleanup using alias check.
- **071** `hub.has_drift_remaining()` helper (extends alignment with
  per-material override check). Triggers + second backfill round.

### Application code

- `app/stores/bom_staleness.py::reconcile_for_material()` — auto-heal
  affected artifacts after catalog edit or override insert. Cap 50
  synchronous, surplus deferred (returned in counts dict).
- `app/routes/catalog.py::edit_material_submit` — wires reconcile.
- `app/stores/client_uom_overrides.py` — wires reconcile on
  create/update/delete factor.
- `app/stores/provenance.py::derive_from_bcct` — on-conflict path now
  fills `name` when placeholder (= material_code). Closes the
  "bom_only codes never get name even when BCCT arrives later" gap.
- `app/stores/bom.py` — API responses include `state` (additive).

### UI

- New `GET /clients/{cid}/bom/needs-action` — cluster page. Each row
  = (cause × related_code) cluster. Bulk action button per cluster.
  Pagination 50/page. 3 tabs (all / needs_refresh / needs_input).
- New `GET /clients/{cid}/bom/audit-log` — forensic history of
  catalog→BOM impact events.
- New `POST /clients/{cid}/bom/refresh-cluster` — bulk refresh,
  artifact_ids form param, cap 200.
- Legacy `/bom/stale` **removed** (route + template + dead helpers
  + dead i18n keys). Replaced by a 308 redirect to `/needs-action`
  so bookmarks + sister-app deeplinks still land. The deprecation
  banner approach was reverted: leaving the old page accessible
  preserved the confusion the rebuild was meant to fix.
- `_primary_action()` distinguishes manual_flat (refresh) vs
  technical_raw (reupload).
- i18n: new `bom.state.*`, `bom.cause.*`, `bom.action.*`,
  `bom.needs_action.*`, `bom.audit_log.*` keys in VN + EN. Replaces
  engineer jargon: "tombstoned" → "đã bị thay", "hook" → "tự sinh",
  "1:1 default" → "Quy đổi 1:1 chưa xác nhận", etc.

### Cross-repo

- `.ai/sister-app-notes/2026-05-27-bom-state-field-shipped.md` —
  CO + BCQT consumer notes (additive API).
- `docs/API_CONTRACT.md` — `state` field documented.

## Results (local DB Johnson + Growatt)

| | Before | After |
|---|---|---|
| Johnson `needs_input` artifacts | 1,336 | 20 (98.5% giảm) |
| Growatt `needs_input` artifacts | (mixed) | 1 |
| Trigger noise for future catalog edits | Always flag (false positive) | Conditional (alias + override aware) |
| Catalog edit UX | 1 click per affected BOM | Auto-reconcile, cap 50 |
| UI rows | 1,336 single-artifact rows | ~26 clusters with bulk action |

## Tests

- New: `tests/test_bom_state_and_conditional_triggers.py` (36 tests)
  — covers `is_uom_aligned`, `has_drift_remaining`, generated state
  column derivation, D7/D9 conditional behavior, reconcile cap logic.
- New: 4 tests in `tests/test_bom_staleness_api_ui.py` for the new
  routes + `state` field in API.
- Updated: `test_d9_marks_derived_artifact_stale_on_catalog_insert`
  uses non-aligned uoms now (was relying on unconditional flag).
- Updated: `tests/test_manual_flat_uom_drift.py` adds 2 tests for
  mig 067 tombstone trigger.
- Updated: `tests/test_provenance.py` adds 2 tests for name backfill.
- Full suite: 1,224 pass, 15 skip.

## Screenshots

- `01_needs_action_johnson_all.png` — cluster page Johnson, all tab.
  26 clusters from 20 artifacts (multi-cause).
- `02_needs_action_johnson_input.png` — needs_input filtered tab.
- `03_needs_action_growatt.png` — Growatt 5 clusters mixing refresh
  and fix_uom action types.
- `04_audit_log_johnson.png` — forensic event log (513 events).

## Deferred / open items

1. **`1000469803`** (Johnson) — 11 derived + 9 raw flagged. BOM has
   mixed EA/KG uoms across parents. Needs Johnson evidence to
   resolve (override or catalog correction). Memory
   `feedback_uom_factor_evidence_driven` applies.
2. **Header count discrepancy** — page title shows `total` (clusters)
   while tab badges show artifact counts. Cosmetic; low priority.
3. **3,822 `name=material_code` placeholders** in Johnson — these
   are bom_only codes (never appeared in BCCT). Patched
   `derive_from_bcct` to fill name when BCCT arrives, but no backfill
   path exists today (catalog/BCCT disjoint). Address when Johnson
   provides SAP master data sheet.
4. **Demo box sync** — local DB changes only; sister apps + demo not
   yet updated. Commit + push + sync demo box separately.

## Done criteria

- [x] State column derives correct value for all combinations.
- [x] D7/D9 conditional triggers skip alias-aligned cases.
- [x] D7/D9 conditional triggers skip override-resolved cases.
- [x] Tombstone clears flag.
- [x] `reconcile_for_material` called from catalog edit + override
      create/update/delete.
- [x] Cluster page (`/needs-action`) renders + paginates.
- [x] Audit log page (`/audit-log`) renders + paginates.
- [x] Bulk refresh endpoint (`/refresh-cluster`).
- [x] i18n vocabulary cleanup (VN + EN).
- [x] API exposes `state` field additively.
- [x] Sister-app notes posted.
- [x] API contract doc updated.
- [x] 5 screenshots committed.
- [ ] Demo box sync.
- [ ] Memory updates (deferred to handoff).
