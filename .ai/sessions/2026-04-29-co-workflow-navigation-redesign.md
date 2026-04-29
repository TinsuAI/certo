# Session: C/O Workflow Navigation Redesign

## What Was Done
- Got current with project state and confirmed the C/O demo/manual-test setup on branch `sprint/co-case-supporting-files-20260429`.
- Used discovery first and wrote `.ai/features/2026-04-29-co-workflow-navigation-redesign.md`.
- Reworked the C/O mental model in the UI:
  - C/O is now the primary workflow entry for a client.
  - Catalog, BOM, C/O stock, BCCT, and config remain supporting data surfaces.
  - `/clients/{client_id}/co-case` is now only for creating/opening dossiers.
  - Workflow stages appear only after opening a specific dossier.
- Added step routes for selected dossiers:
  - `/clients/{client_id}/co-case/{case_id}`
  - `/clients/{client_id}/co-case/{case_id}/documents`
  - `/clients/{client_id}/co-case/{case_id}/exports`
  - `/clients/{client_id}/co-case/{case_id}/guidance`
  - `/clients/{client_id}/co-case/{case_id}/origin`
  - `/clients/{client_id}/co-case/{case_id}/review`
- Rebuilt the C/O index dossier list from chip links into a structured work-queue style list showing title, code, market, invoice, B/L, file count, update time, and `Mở hồ sơ`.
- Added responsive styling so mobile renders each dossier as a stacked record rather than a clipped horizontal table.
- Added a dedicated shipment metadata update route so saving the shipment step does not route through the origin evaluation form and does not drop product/origin data.
- Updated regression tests for the new mental model and rebaselined snapshot checks to opened dossier steps.
- Ran verification:
  - `uv run pytest tests/test_co_demo.py -q` passed with `75 passed`.
  - Playwright desktop/mobile smoke tests passed for the C/O index and selected-dossier detail pages.
  - `git diff --check` passed.
  - `npm test` still failed the 3 known legal lookup `raw-binary` source-link tests unrelated to this work.

## Decisions Made
- The C/O index must not show the dossier workflow stepper. It is only a create/open screen.
- Workflow stages belong inside a selected dossier because they are case-specific.
- Supporting-file upload should return to the `documents` step.
- Snapshot and criteria/evaluation content should live under opened dossier steps, especially `origin` and `review`, not the dossier list.
- The dossier list should be a structured operator queue, not chips.
- Keep existing detail URL compatibility: `/co-case/{case_id}` opens the shipment step.
- Keep current file-backed storage and export behavior; this redesign is navigation and workflow presentation, not a data model migration.

## What Didn't Work
- The first redesign still showed workflow stages and source/BOM snapshots on `/co-case`. The user clarified that stages should appear only after opening a dossier, so the index was simplified.
- The first dossier list used chips, which hid important shipment metadata and made it hard to choose the correct case.
- A plain table improved desktop readability but was poor on mobile because important columns were clipped. It was replaced with a responsive record list.
- The first shipment edit form reused the `/evaluate` route. Review found that this could drop product/origin data because it was a metadata-only form, so a dedicated `/shipment` route was added.
- A Playwright run initially failed because the Chromium browser binary was missing from the local cache. Running `uv run --with playwright playwright install chromium` fixed the tooling.

## Open Items
- User still needs to manually test the new workflow in the browser using the prepared Growatt manual-test files.
- The UI may need more domain tuning after the manual test, especially around wording of step names and review/export behavior.
- The app still needs real HS/PSR legal lookup before showing final form-specific origin pass/fail.
- Criteria preview still needs real stock allocation/reservation semantics before it can become operational allocation.
- `npm test` still needs the known legal lookup `raw-binary` expectation issue resolved or intentionally rebaselined.
