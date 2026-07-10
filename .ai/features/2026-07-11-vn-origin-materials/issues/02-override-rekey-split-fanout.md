# 02 — Override identity re-key + render-split fan-out machinery

Status: ready-for-agent — tracked on GitHub: [TinsuAI/co#7](https://github.com/TinsuAI/co/issues/7) (tracker of record)

## Parent

`.ai/features/2026-07-11-vn-origin-materials/spec.md` (build-order ticket 2).

## What to build

Per-material overrides (rename, code, delete, substitute, …) stop being identified by
the positional render index and become identified by `material_sequence` (BOM rows)
and `added_<n>` (manually added rows), bound to the BOM version they were made
against. Staff edits survive recalculation and never misapply to the same position of
a different BOM version — this closes a pre-existing bug, independent of origin work.

Also lands the render-split fan-out machinery: one source material can emit N display
rows keyed `(material_sequence, origin_status, column9_text)`, with the source
materials list unchanged. With today's data every material's key set is uniform, so
exactly one row renders per material — no visible change until tickets 04/07 make
keys differ.

## Acceptance criteria

- [ ] Overrides are written and read keyed by `material_sequence` / `added_<n>`,
      bound version-aware (BOM version artifact id) — an override made under version
      A does not apply under version B (regression test for the version-switch
      misapply bug).
- [ ] Legacy positional override keys migrate deterministically (index+1); existing
      cases keep all their overrides after upgrade.
- [ ] Fan-out: a source material with N distinct `(origin_status, column9_text)`
      groups renders N rows; each row keeps the merged-declaration behaviour within
      its part; the N parts sum exactly to the line's quantity and money totals.
- [ ] With uniform keys (all of today's data) rendering is unchanged — one row per
      material, export == web intact.
- [ ] Undo/redo, the diff counter, and autosave behave as before (overrides stay
      material-scoped; no display-only data enters the override map).
- [ ] No new persisted per-material UUID is introduced.

## Blocked by

None — can start immediately.
