# Three small independent items — 2026-05-13

Bundled here because the work landed in a single session and shares a
single UI smoke harness (`scripts/smoke_three_small_items.py`).

## Items shipped

1. **BOM upload — auto-detect adapter** (commit `8cf355e`).
   Adds `auto` as the default option in the BOM upload form. Calls
   `bom_adapters.parse_with_fallback()` with the filename stem as a
   `root_code` hint; first adapter producing non-empty rows wins.
   Skips the column-mapping page entirely (manual_flat path) and lands
   directly on the universal `/bom/preview/<id>` screen with
   `proposed_by='parser_auto:<adapter>'`. When all 5 adapters fail or
   raise: 400 with friendly Vietnamese message.

2. **Manual_flat 4-shape model** (commit `f113d17`).
   `bom_shape()` now returns `'manual_flat'` for
   `manual_flat_as_provided` strategy (was conflated with `'shallow'`).
   `BomShape` Literal extended to 4 values. `shape_badge` macro renders
   `manual_flat` with its own tooltip emphasising "source vs derived".
   Memory `project_bom_3_shapes.md` updated to 4-shape with worked
   example. 5 new tests on the function contract.

3. **UI rename "tombstone" → friendly Vietnamese** (commit `4060997`).
   UI/template/i18n only — code identifiers, DB columns, API contracts,
   CSS class names, and action URLs all stay as `tombstone`. Mapping:
   - Catalog material lifecycle    → "đã loại"
   - BOM artifact lineage / replace → "đã thay thế"
   - BOM preset retract            → "thu hồi"

## UI smoke results

Run `uv run python scripts/smoke_three_small_items.py` (requires dev
server on `:8754` + admin login). Last run 2026-05-13 — all 5 visible
checks pass; one skipped due to absent fixture.

| # | Item | Check | Status |
|---|---|---|---|
| 1a | upload form default | dropdown shows "Tự động phát hiện (recommended)" selected | pass |
| 1b | upload auto post | redirects to `/bom/preview/<id>`, not mapping | pass |
| 2 | manual_flat badge | `badge-shape-manual-flat` rendered; no `shallow + strategy` regression | pass |
| 3a | BOM tombstone labels | "Thời điểm thay thế" + "Lý do thay thế" present; old labels gone | pass |
| 3b | tombstoned material badge | "đã loại" present | skipped (no fixture) |
| 3c | catalog button rename | "⌫ Loại khỏi danh mục" present; old "⌫ Tombstone" gone | pass |

## Screenshots

- `screenshots/1a_upload_form_default.png` — upload form default option.
- `screenshots/1b_after_auto_upload.png` — preview page after auto-detect.
- `screenshots/2_manual_flat_badge.png` — artifact detail showing manual_flat shape.
- `screenshots/3a_tombstoned_bom_labels.png` — BOM artifact detail with VN labels.
- `screenshots/3c_active_material_button.png` — catalog detail with VN button.

## Cross-links

- BACKLOG entries struck through:
  - "BOM upload — auto-detect adapter (drop manual parser pick)"
  - "Re-evaluate 'shallow' shape for manual_flat artifacts"
  - "UI rename 'tombstone' → friendly Vietnamese terms (UI-only)"
- Memory updated:
  - `project_bom_3_shapes.md` — 3-shape → 4-shape
- Test deltas: +2 (auto-detect) + +5 (4-shape) + 0 (UI rename) = 978 total.
