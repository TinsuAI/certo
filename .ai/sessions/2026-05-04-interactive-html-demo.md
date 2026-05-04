# Session: Interactive HTML Demo

## What Was Done
- Refreshed project context from `AGENTS.md`, `.ai/STATUS.md`, `.ai/DECISIONS.md`, and recent session summaries.
- Started the CO dev server at `http://127.0.0.1:8001`; unauthenticated requests still redirect to `/auth/login`.
- Confirmed the user needed a customer demo because Data Hub data is currently not stable enough.
- Created `barry-co-interactive-demo.html`, a self-contained static HTML demo that opens directly in a browser and does not call FastAPI or Data Hub.
- Reflected the current Barry CO app structure in the demo:
  - company workspace and client module tabs
  - C/O case workflow steps
  - catalog, BOM, CO stock, BCCT, client config, customs exchange rates, and C/O Form Index
  - Growatt case `GIN01425L031` with sample products, materials, documents, BCCT rows, BOM versions, and origin evidence
- Added interactive client-side behavior:
  - invoice/market form inference
  - table filtering
  - mock upload/save/refresh actions
  - document checklist toggling
  - BOM TP version switching
  - editable FOB/material values/origin and live Build-down LVC/RVC recalculation
  - warning display for missing material valuation
  - demo Origin Snapshot CSV export
- Ran verification:
  - `node --check` on the inline script passed.
  - Puppeteer smoke test passed for loading the file, opening `Xuất xứ`, verifying Build-down LVC/RVC, switching a BOM variant to trigger missing valuation warnings, and navigating catalog/materials.
  - `npm test` was run and failed 3 existing legal lookup tests about `raw-binary` source links; this is unrelated to the static demo.

## Decisions Made
- Build a static, self-contained HTML file instead of modifying the FastAPI/Jinja app because the immediate need is a stable customer demo while Data Hub source data is unreliable.
- Keep all demo data local inside the HTML file and clearly mark Data Hub-dependent sections as mock/static.
- Use Growatt and the existing `GIN01425L031` case as the demo storyline so the demo matches the project vocabulary and recent origin workflow.
- Make the C/O case workflow the first screen because customer value is in preparing/reviewing a C/O dossier, not in a generic landing page.
- Demonstrate Build-down LVC/RVC only: `(FOB - VNM) / FOB x 100`. Do not imply direct/build-up support or a complete legal PSR engine.
- Commit only the new static demo and handoff artifacts. Older uncommitted application changes were left untouched and unstaged.

## What Didn't Work
- Initial Puppeteer smoke test failed because `node_modules/` was absent even though `puppeteer` is already in `package-lock.json`.
- Ran `npm ci` to install dependencies into ignored `node_modules/`; no package metadata changed.
- Full `npm test` is still red in legal lookup tests expecting `raw-binary` source links. The failure predates and is unrelated to `barry-co-interactive-demo.html`.
- Browser availability checks did not find system Chrome/Chromium, so Puppeteer from the project dependency was used after `npm ci`.

## Open Items
- Manually review `barry-co-interactive-demo.html` with the customer presentation flow and adjust copy/density if needed.
- Decide whether the static demo should remain repo-root or move under a dedicated demo/docs folder.
- Separately review and either commit or revise the older origin-web-snapshot changes in `app/` and `tests/`.
- Keep the static demo disconnected from Data Hub until Data Hub data and contracts are stable enough for customer-facing live behavior.
