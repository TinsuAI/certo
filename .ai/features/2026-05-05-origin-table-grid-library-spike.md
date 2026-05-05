# Origin Table Grid Library Spike

Date: 2026-05-05

## Context

The origin snapshot table currently needs a compact review layout. Later, staff should be able to edit workbook-like tables in the browser without losing validation, keyboard navigation, copy/paste, and export parity.

## Recommendation

Keep the native HTML table for this sprint. The current need is layout density and source visibility, not full grid editing.

For the first editable-grid prototype, evaluate Tabulator first. It is plain JavaScript, so it fits the current server-rendered app without requiring a React migration, and its official docs cover editable cells, validation, clipboard/range workflows, responsive column handling, history, XLSX export, and a spreadsheet module with multiple sheets.

Do not adopt AG Grid before checking the exact Community vs Enterprise feature split for the features CO needs. Its editing model is strong, but advanced workbook-style behavior can move into licensed territory.

Use TanStack Table only if the app moves to a React/Vue-style frontend. It is headless and powerful, but it would push more UI/editing behavior onto our codebase.

## Library Notes

| Library | Fit | Risk |
| --- | --- | --- |
| Tabulator | Best first POC for the current stack: vanilla JS, built-in editors, validation, clipboard/range/spreadsheet modules, responsive columns. | Need to verify nested/detail row UX and Vietnamese data entry edge cases. Spreadsheet module has no formula engine today. |
| TanStack Table | Good if CO later gets a component frontend and we want total control over markup. | Headless by design; editing, keyboard UX, validation display, copy/paste, and workbook affordances would need custom implementation or companion libraries. |
| AG Grid Community | Strong data-grid option with mature cell editing, editor events, custom editors, virtualization, and keyboard behavior. | Must confirm license and which required features are Community vs Enterprise before committing. |

## Future POC Acceptance Criteria

- Editable numeric/text/select cells with domain validation and visible errors.
- Keyboard navigation close enough to spreadsheet use: arrows, Enter, Tab, Escape.
- Copy/paste from Excel for rectangular ranges.
- Frozen identifier columns and horizontal scrolling for wide CO tables.
- Expandable child rows or detail panels for stock allocation lines.
- Save only approved editable fields back to the CO case model.
- Exported workbook remains byte-level or value-level compatible with current tests.

## References

- Tabulator overview: https://tabulator.info/
- Tabulator editing: https://tabulator.info/docs/6.4/edit
- Tabulator spreadsheet module: https://tabulator.info/docs/6.4/spreadsheet
- TanStack Table docs: https://tanstack.com/table/latest
- AG Grid cell editing: https://www.ag-grid.com/javascript-data-grid/cell-editing/
- AG Grid cell editors: https://www.ag-grid.com/javascript-data-grid/cell-editors/
