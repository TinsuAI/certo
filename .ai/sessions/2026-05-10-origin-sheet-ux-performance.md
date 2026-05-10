# Session: Origin Sheet UX and Performance

## What Was Done
- Validated Data Hub product identity from CO for Growatt rows, including `BIENTAN.17 -> PV01.0117500`, and updated the Data Hub API request with live evidence.
- Added a CO consumer plan for migrating from temporary `code-mappings` BOM resolution to `product_identity.bom_product_code`.
- Implemented sheet-only origin calculation so `Tính bảng kê` recalculates the target sheet only while preserving previous locked/posted sheet consumption.
- Added cached origin context:
  - persisted `source_snapshot` and `source_invoice_matches`,
  - preloaded origin context when opening a persisted case,
  - used cached source/BOM snapshots for state-only actions such as `Chốt` and `Mở chốt`.
- Added sequential sheet workflow enforcement:
  - cannot calculate/lock sheet N until earlier sheets are locked,
  - cannot reopen an earlier sheet while a later sheet is locked,
  - releasing the origin stock lock marks all sheets stale.
- Added AJAX shell replacement and toast feedback for in-case operations so C/O workflow actions avoid full-page reloads.
- Fixed the `Method Not Allowed` symptom on `/origin/sheet/{code}/calculate`:
  - root cause was AJAX `FormData` sending huge origin forms as multipart, hitting Starlette parser field limits before route logic,
  - normal non-file AJAX forms now send `application/x-www-form-urlencoded`,
  - backend origin form parser limit was raised as a fallback for legacy/open tabs,
  - AJAX no longer redirects to POST-only action URLs when the server returns a non-shell error body.
- Added discovery brief for future client-side origin calculation with preload JSON and explicit Save/persist.

## Decisions Made
- Keep server-side origin calculation as canonical for now. Client-side calculation is promising for UX but needs a dedicated JSON payload/save design and parity tests before implementation.
- Do not load all BOM rows or all BOM versions client-side. Future client-side payload should load version metadata for candidate TP BOMs and rows only for selected product versions.
- Do not use the HTML form as a database for long-term origin state. The current hidden-field approach is the immediate source of large-payload/slow-interaction problems.
- Keep lock/export server-validated from persisted state even if calculation previews move client-side.
- Do not commit unrelated screenshots, sister-app notes/prompts, or `docs/co-form-index-confirmation.*` changes in this focused commit.

## What Didn't Work
- Raising parser limits alone did not solve the core UX issue. It only masked the multipart field-limit failure while leaving DOM serialization and request size too large.
- Direct curl/TestClient against the live authenticated Growatt origin page could not fully reproduce browser actions because unauthenticated requests redirect through auth/Data Hub login.
- `npm test` was run and failed in unrelated legal lookup tests expecting `raw-binary` source links. This was not part of the C/O origin change.

## Open Items
- Implement CO consumption of Data Hub `product_identity.bom_product_code` and remove temporary `code-mappings` BOM resolution.
- Add scoped JSON preload/save endpoints for origin calculation if moving calculation to browser.
- Port or share the calculation core carefully if client-side calculation is implemented; golden fixtures should cover multi-lot allocation, shortages, previous-sheet consumption, missing unit values, mixed currency, and BOM overrides.
- Browser-test the authenticated `growatt-vn` case manually, especially `BIENTAN.19` calculate after the form encoding fix.
- Decide stable sheet identity if duplicate finished-product codes can occur in one dossier.
