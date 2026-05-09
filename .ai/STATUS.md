# Project Status

**Date:** 2026-05-10 PM — BOM vocab + 3-shape grouping + UoM ingest gate (3 tracks). Commits `2ec028f`, `fbb910d`, `06026a2` on `main`.

## Current State

**Working tree clean. 3 commits this session.**

### Track A — BOM vocab cleanup (`2ec028f`)
- Drop "v" badge → "#" everywhere; hide bom_variant_id when 'default';
  rename store dict `n_dual_variants` → `n_strategies`.
- VN i18n → "bản lưu" / "shape" / "preset"; EN → "artifact" / "shape" /
  "preset". `bom.bom_variant` VN renamed from "Phiên bản BOM" (clashed
  with logical-tuple) to "Đợt".
- 21 tests, screenshots committed.

### Track B — lineage_root_id (`fbb910d`)
- Mig 052 adds `bom_artifacts.lineage_root_id` NOT NULL + BEFORE INSERT
  trigger + recursive-CTE backfill (852 rows / 2.5ms) + index.
- `list_products_with_bom` exposes `n_logical_versions`, `n_artifacts`
  (compat aliases for legacy keys preserved).
- `bom.html` column "Versions" → "Phiên bản"; cell "1 · 3 bản lưu · 1
  non-flat".
- 12 tests.

### Track C — UoM ingest-time gate (`06026a2`)
- `app/stores/uom_drift.py::compute_uom_drifts` 3-tier severity:
  warn_cross_family / info_family / info_unknown / info_alias.
- Wired into BOM + BCCT upload preview routes; reusable banner template
  `_uom_drift_banner.html`.
- Cross-family drift requires ack checkbox; primary submit disabled
  via inline JS until checked.
- Non-mutating — flatten engine still converts at materialize time.
- 15 tests (11 helper + 4 integration).

### Track D — DEFERRED
Captured as BACKLOG entry "BOM dependency staleness". 8 dimensions of
external-state changes that silently stale BOM artifacts. Scope >>
A+B+C combined; needs 1-2d discovery before pick. Recommendation
preliminary: option 1 (staleness flag) MVP, option 4 (event-sourced
ledger) post-MVP.

## Recent Changes — files

```
NEW (across 3 commits):
  .ai/features/2026-05-10-bom-vocab-3shape-uom-gate/brief.md
  .ai/features/2026-05-10-bom-vocab-3shape-uom-gate/screenshots/01..05_*.png
  db/migrations/052_bom_lineage_root_id.sql
  app/stores/uom_drift.py
  app/templates/clients/_uom_drift_banner.html
  scripts/screenshot_track_a.py
  scripts/screenshot_track_c.py
  tests/test_bom_vocab_track_a.py
  tests/test_bom_lineage_root.py
  tests/test_uom_ingest_drift.py

MODIFIED:
  .ai/BACKLOG.md          (Track D entry)
  app/i18n.py             (VN/EN vocab + UoM drift keys + new col labels)
  app/routes/bcct.py      (UoM drift wired into preview view)
  app/routes/bom.py       (UoM drift wired + sort whitelist accepts new keys)
  app/stores/bom.py       (n_logical_versions + n_artifacts + compat aliases)
  app/templates/clients/_bom_macros.html       (#-badge, hide-default)
  app/templates/clients/_upload_preview.html   (banner include)
  app/templates/clients/bcct_upload_preview.html (form id + banner include)
  app/templates/clients/bom.html               (new col + #-badge + n_strategies)
  app/templates/clients/bom_artifact_detail.html (#-badge, hide-default Variant row)
  app/templates/clients/bom_artifacts.html     (#-badge, conditional variant col)
  app/templates/clients/bom_presets.html       (#-option, hide-default)
  app/templates/clients/bom_preview.html       (conditional variant col)
```

**Tests:** 772 → 820 (+48). 0 fail, 15 skip.

## Next Steps

Per `BACKLOG.md` priority:

1. **Track D — BOM dependency staleness** (1-2d discovery + 2-4d
   option-1 implement) — captured this session, deferred.
2. **v_material_roles paren-aware** (~1-1.5d) — proper fix replacing
   `material_observations.py` workaround.
3. **UoM admin UI polish** — deferred 2026-05-10 AM.
4. **Phase 2 catalog** — `roles[]` + drop `category`.
5. **Wipe + re-ingest fresh Growatt + Johnson** — pre-MVP reset.

## Blockers

None hard.

Soft (carry-over):
- 14 orphan BTPs Growatt (data quality).
- T1-T2/2026 BCCT for Growatt missing.

## Notes for Next AI Session

**Read first** (in order):
1. This STATUS
2. `.ai/sessions/` — write the session summary first time visiting next
3. `.ai/features/2026-05-10-bom-vocab-3shape-uom-gate/brief.md` (full
   design, 4 tracks)
4. `.ai/BACKLOG.md` — Track D entry "BOM dependency staleness"

**Key memory updated this session:**
- `feedback_bom_vocab.md` — Track A enforcement rules (badge, hide-
  default, n_strategies semantic).
- `project_bom_lineage_root.md` (NEW) — Track B schema + trigger +
  store changes.
- `project_uom_drift_gate.md` (NEW) — Track C severity tiers + wiring.

**Architecture LOCKED — don't relitigate**:
- Drop "v" letter from artifact_no badges everywhere.
- Hide `bom_variant_id` when `'default'` or NULL across all 5 sites.
- `lineage_root_id` is the logical-version-tuple key; trigger maintains.
- UoM drift gate is non-mutating; flatten engine handles convert.
- Cross-family drift requires explicit staff ack; same-family is
  info-only.

**Schema evolution to expect:**
- Mig 053+ for v_material_roles paren-aware.
- Mig 054+ for Track D (lineage_root_id stays compat).

**Working-tree state**: clean. Commits `2ec028f`, `fbb910d`, `06026a2`
on `main`.

**Migration state**: DB at mig 052 applied (53 total).
