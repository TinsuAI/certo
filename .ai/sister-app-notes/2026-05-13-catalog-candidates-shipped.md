# Adoption guide — Mã chờ duyệt (catalog candidates) shipped

**Date:** 2026-05-13 (back-filled — feature shipped 2026-05-09)
**For:** CO + BCQT (read-only consumers of `hub.materials`)
**Data Hub migrations:** `047_ma_cho_duyet_catalog_candidates.sql`,
`048_catalog_candidates_extra_stats.sql`,
`049_catalog_candidates_richness.sql`
**Brief:** `.ai/features/2026-05-09-ma-cho-duyet/brief.md`
**Predecessor note:** `2026-05-09-catalog-multi-source-and-vocab.md`
covered mig 042-043; this note covers the post-rollout catalog
candidate flow (mig 047-049) that was missed in the predecessor.

## TL;DR

Three additive migrations to the catalog flow. **Pure additions** —
no schema renames, no breaking changes for sister-app consumers.

1. **Mig 047** — `hub.catalog_candidates` + `hub.catalog_candidate_rejections`
   tables. New route `/clients/<id>/catalog/candidates` (Mã chờ duyệt
   feed). Adds `materials.production_source` text column with
   CHECK enum.
2. **Mig 048** — `catalog_candidates` enriched with import / export /
   declaration counts + `bom_role` + `bom_sample` + co-occurrence count.
3. **Mig 049** — `catalog_candidates` enriched with `hs_code`,
   `hs_alternates_count`, `uom`, `origin`, `inferred_production_source`.

**What this affects for sister apps:** if you read `hub.materials`
joined with anything else, only the **`materials.production_source`**
column is new (mig 047) and worth knowing. The candidate tables are
internal staging — sister apps don't read them directly.

## Schema change relevant to sister apps

`hub.materials` gains:

```sql
production_source text
  check (production_source in ('nk', 'sx', 'mixed', 'unknown'))
```

Backfilled on existing rows via mig 047 logic:
- `materials.category = 'tp'` and `direction='export'` in BCCT → `'sx'`
- BCCT shows imports for the code → `'nk'`
- Both directions present → `'mixed'`
- Otherwise → `'unknown'` (default)

API impact: existing `/v1/hub/materials` and
`/v1/hub/materials/{material_code}` endpoints are NOT yet updated to
expose this field — TODO if sister apps need it. Read directly via DB
query if necessary.

## What `catalog_candidates` is

A passive feed table populated by a refresh script (`scripts/refresh_catalog_candidates.py`
or via the UI button) that watches BCCT + BOM data graphs and surfaces
codes NOT yet in `materials`. Staff Accept / Reject via the
`/clients/<id>/catalog/candidates` UI; Accept inserts a `materials`
row with `source='bcct_observed'` or `'bom_observed'`.

Sister apps do NOT consume this table. Mentioned here only so cross-repo
audits don't flag it as an unknown table.

## Cross-references

- Brief: `.ai/features/2026-05-09-ma-cho-duyet/brief.md`
- Memory: `project_bom_code_multirole.md` (multi-role context that
  drives candidate enrichment).
- Predecessor note (mig 042-043 + naming):
  `2026-05-09-catalog-multi-source-and-vocab.md`.
