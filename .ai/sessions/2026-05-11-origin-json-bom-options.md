# Session Summary: Origin JSON Payloads And BOM Options

Date: 2026-05-11

## What Was Done
- Replaced the main Origin action payload path with compact JSON:
  - added `GET /clients/{client_id}/co-case/{case_id}/origin/calculation-payload`,
  - added `POST /clients/{client_id}/co-case/{case_id}/origin/save`,
  - added revision hashing for source/BOM/origin state,
  - updated autosave and sheet calculate/lock/reopen to accept JSON while preserving legacy large-form fallback.
- Updated Origin frontend behavior:
  - sheet order and BOM artifact changes now save compact JSON,
  - calculate/lock/reopen send product-level metadata and BOM override fields only,
  - existing server-rendered shell replacement remains in place.
- Investigated why Data Hub showed multiple BOM artifacts for `growatt-vn / SD00.0010600` while Origin showed only one.
  - Root cause: cached Origin context used `bom_workspace_from_case_snapshot(case)`, which only contains the artifact already bound in the saved case.
  - Fix: Origin now builds live BOM workspace from Data Hub by `bom_product_code` even when source context is cached; snapshot BOM workspace is fallback only when live product versions are unavailable.
- Filtered selectable Data Hub BOM options to flattened artifacts only.
  - `non_flattened` artifacts stay in `product_versions` for history/debug visibility,
  - dropdown options are now flattened/current/published artifacts only.
- Verified live local Data Hub behavior for `SD00.0010600`:
  - before dropdown filtering, CO saw 6 product versions,
  - selectable options now show 4 flattened artifacts,
  - 2 non-flattened artifacts are excluded.

## Decisions Made
- Keep Python/server-side Origin calculation canonical for now. The new JSON payload endpoint is groundwork for client-side calculation, not a full port yet.
- Preserve legacy form fallback routes so existing browser tabs and export flows continue working during migration.
- Source data can remain cached for Origin speed, but BOM artifact options must come from live Data Hub workspace to expose newly published/selectable artifacts.
- Do not allow non-flattened BOM artifacts in Origin sheet dropdowns because they are not usable for calculation.

## What Didn't Work
- Using saved BOM snapshot as the dropdown source was too narrow: it only represented the artifact already selected in the dossier, not all Data Hub artifacts for that BOM product.
- Preloading Origin context before rendering `/origin` caused a regression in local BOM version dropdown tests because the page fell into snapshot mode too early and lost full workspace options. That preload change was removed.
- A first compact calculate payload omitted basic product fields like `fob`, causing backend result attachment to fail before recalculation. The compact payload now includes the small product metadata needed by the server path.
- A temporary live debug case was created while checking Data Hub options and then removed (`co-case-31edd301ff49`).

## Open Items
- Finish replacing hidden material/allocation form state with JSON-rendered Origin state and explicit save.
- Add parity fixtures before porting any Origin calculation logic client-side.
- Confirm stable sheet identity if duplicate finished-product codes can occur in one dossier.
- Decide Data Hub contract/data process for NVL origin classification evidence.
