# Project Status

## Current State
- Active branch: `main`; do not push unless user asks.
- Local CO dev server is listening on `http://127.0.0.1:8001`; auth is enabled, so unauthenticated origin URLs redirect to `/auth/login`.
- Origin workflow now has sheet-level controls and stricter sequential rules:
  - each finished-product sheet has `Tính bảng kê`, `Chốt`, and `Mở chốt`,
  - `Tính bảng kê` recalculates only the target sheet, not the whole case,
  - sheets must be calculated/locked in order; later locked sheets block reopening earlier sheets,
  - releasing the origin stock lock marks all origin sheets stale,
  - stale/draft/unlocked sheets block export.
- Performance work reduced repeated source reloads:
  - opening a persisted case preloads origin context once,
  - state-only actions such as lock/reopen use cached case/source snapshots,
  - AJAX shell replacement avoids full-page reload inside a C/O case and shows toast feedback.
- Large origin form failure was addressed:
  - AJAX non-file forms now submit as `application/x-www-form-urlencoded` instead of multipart `FormData`,
  - origin backend routes use a larger parser guard as fallback for legacy/open tabs,
  - regression test covers 21k-field origin actions.
- Client-side origin calculation is only discovered/planned, not implemented. Brief: `.ai/features/2026-05-08-client-side-origin-calculation.md`.
- Data Hub product identity was validated locally, but CO has not yet fully migrated to consuming `product_identity.bom_product_code`; temporary `code-mappings` support remains.

## Recent Changes
- Added sheet-only origin calculation path and tests so one sheet can be recalculated without rebuilding previous sheets.
- Added cached origin source/BOM context persistence via `source_snapshot` and `source_invoice_matches`.
- Added preload on case open and fast context mode for lock/reopen to reduce repeated Data Hub/BOM calls.
- Added sequential sheet state rules and UI disabling/tooltips for calculate/lock/reopen.
- Added AJAX case shell replacement and toast feedback for in-case operations.
- Fixed `Method Not Allowed` symptom from failed AJAX POSTs by avoiding multipart for normal forms and preventing AJAX error responses from redirecting to action URLs.
- Updated Data Hub product identity API request and CO consumer plan docs with live validation evidence.
- Added discovery brief for future client-side calculation with preload JSON + save JSON patch architecture.

## Next Steps
1. Implement `.ai/features/2026-05-07-co-product-identity-consumer-plan.md`: consume `product_identity.bom_product_code` and remove temporary `code-mappings` BOM resolution.
2. Replace large hidden origin form state with JSON payload endpoints per `.ai/features/2026-05-08-client-side-origin-calculation.md`.
3. Add browser-level verification for authenticated `growatt-vn` origin case UX, especially `BIENTAN.19` calculate/lock/reopen.
4. Decide whether duplicate finished-product codes can occur in one dossier. If yes, replace product-code keyed sheet state with a stable line identity.

## Blockers
- Browser verification is limited by authenticated local session access; unauthenticated direct curls redirect to auth.
- `npm test` currently has unrelated legal lookup failures around `raw-binary` source links; Python CO tests pass.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User is sensitive to slow UX and dislikes hidden reloads. Keep case interactions shell/AJAX-based, but avoid huge hidden-form payloads.
- CO is a Data Hub consumer. Do not add raw `/v1/hub/*` calls outside `app/data_hub_client.py`, and do not invent Data Hub endpoints from CO.
- Verification already run after current changes: `uv run pytest` passed with `187 passed`.
- Do not commit unrelated local artifacts unless explicitly requested. Known unrelated dirty/untracked files include `docs/co-form-index-confirmation.*`, `.ai/screenshots/co-case-origin-ux/`, `.ai/screenshots/co-case-overview-lock/`, `.ai/screenshots/co-origin-sequence-lock/`, `.ai/sister-app-notes/2026-05-07-bom-presets-3b.md`, and `.ai/sister-app-prompts/`.
