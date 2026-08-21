# BOM auto-detect tree-flat fix + honest upload signals

**Date:** 2026-06-05 · **Commits:** `90ba345` (logic), `0bd85d2` (UX) · **Shipped to prod.**

## Problem

`profile=auto` (the default "Tự động phát hiện") routed every adapter's flat
parse through `create_artifact` → `source_bom_kind=manual_flat`,
`flatten_status=not_applicable`. Single-rooted explosion trees
(`sap_indented_walk`, `multi_sheet_per_root`, `emits_intermediate_btp_versions=False`)
therefore landed FLAT: no `raw_graph`, no `shallow`/`full_flat` derived — yet
`parse_status='done'`. The `materialize_shapes` hook ran but no-op'd (it only
acts on published `technical_raw` artifacts, none existed).

Repro: johnson-vn `MPL0100-39.XLSX` (8-level deep `_node_path`, 244 rows) stored
as flat with no flattening, on prod.

## Fix (logic — `90ba345`)

In the `auto` branch of `app/routes/bom.py`: when the detected adapter is a tree
adapter and a raw-edge parser also matches, set `profile='technical_raw'` and
fall through to the raw-edges path (`parse_raw_edges_with_fallback` →
`create_raw_artifact` → materialize). Falls back to the flat path if no raw-edge
parser matches (no regression).

## Fix (UX — `0bd85d2`)

- **Preview destination banner**: states whether confirming will auto-derive
  flat shapes (technical_raw) or store as-provided flat. A red warning fires
  when a multi-level `_node_path` file is about to land flat.
- **Honest post-ingest toast**: confirm redirect carries `kind` + `flat`; the
  list toast distinguishes technical-OK / technical-no-flat-WARNING / flat —
  instead of a flat "done". The warning is the exact signal the original bug
  swallowed.

## Prod remediation

Tombstoned 2 stuck artifacts (`MPL0100-39`, `MFW0537-39`). Re-ingested via the
fixed flow: `MPL0100-39` now has raw + shallow + full_flat (published).
`MFW0537-39` already had good shapes (the 2026-06-04 re-upload was a
byte-identical stray manual_flat); duplicates from re-ingest were tombstoned.

Note: `create_raw_artifact` dedup keys on `actor`, so an `erp_pipeline` raw and
an `agency_staff` raw with identical edges do NOT dedup.

## Screenshots

`screenshots/` (light, vi) — captured via `scripts/screenshot_bom_flow_signals.py`:

1. `01_upload_form` — upload form, auto default.
2. `02_preview_technical_will_flatten` — technical BOM → "tự động sinh BOM phẳng".
3. `03_preview_flat_as_is` — flat BOM → "lưu nguyên trạng, không phân rã cấp".
4. `04_preview_multilevel_warning` — multi-level file landing flat → red warning.
5. `05_toast_technical_ok` — raw + flat shapes derived.
6. `06_toast_technical_warning` — raw but NO flat shapes (silent-skip signal).
7. `07_toast_flat_stored` — flat stored as-provided.

## Self-service retraction (follow-up)

Staff previously had no UI to remove a wrongly-stored confirmed artifact —
the MPL0100-39 fix needed a developer SQL tombstone. Added:

- **Tombstone a BOM version** — `POST /clients/{id}/bom/artifact/{aid}/tombstone`
  + danger-zone form on the artifact detail. Requires a reason, writes a
  `version.tombstoned` audit row, and **cascades to derived shapes**: it
  resolves the version root (a shape's raw_graph parent, else the artifact)
  and tombstones root + children, so no orphaned shallow/full_flat. Confirm
  dialog warns sister apps (BCQT/CO) may consume the version. Soft only
  (never DELETE — BOM immutable principle).
- **Delete a failed upload** — `POST /clients/{id}/uploads/{uid}/delete`
  + "Xoá" button in the uploads list, restricted to `error`/`rejected`
  rows (a `done` row backs an artifact via `source_upload_id`).

Shots `08_artifact_danger_zone`, `09_uploads_delete_error`.

## Tests

`tests/test_bom_flexible_flow.py::test_auto_profile_tree_adapter_lands_as_raw_graph`
asserts tree→raw routing, materialized shape, preview banner, and the
`kind=raw&flat=1` redirect signal. Full suite: 1341 passed.
