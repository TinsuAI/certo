# Project Status

## Current State
- Active branch: `main`; do not push unless user asks.
- CO dev server is running at `http://127.0.0.1:8001`; `/healthz` returns `{"status":"ok"}`.
- Local Data Hub is running at `http://127.0.0.1:8754`; CO is in Data Hub consumer mode with auth enabled.
- Origin workflow remains server-rendered with AJAX shell replacement, but high-frequency Origin actions no longer serialize the full hidden origin form:
  - `GET /clients/{client_id}/co-case/{case_id}/origin/calculation-payload` returns scoped JSON for future client-side calculation work.
  - `POST /clients/{client_id}/co-case/{case_id}/origin/save` accepts compact JSON for sheet order/BOM override state.
  - Origin autosave and sheet calculate/lock/reopen now send compact JSON from the UI; legacy large-form handling remains as fallback for old tabs/export flows.
- Cached Origin pages still reuse source snapshots for speed, but live BOM artifact options are fetched from Data Hub by `bom_product_code`; snapshot-only BOM workspace is now only a fallback when live options are unavailable.
- Origin BOM artifact dropdown options from Data Hub are filtered to flattened artifacts only; `non_flattened` artifacts remain in service history/debug data but are not selectable.
- CO still matches current Data Hub vocabulary: `material_identity`, `/client-config`, `DATA_HUB_SERVICE_TOKEN`, and BOM artifact naming.

## Recent Changes
- Added compact Origin JSON payload helpers and revision checks in `app/main.py`.
- Added Origin calculation payload and save endpoints.
- Updated Origin frontend JS to submit compact JSON for autosave and per-sheet calculate/lock/reopen instead of serializing thousands of hidden material/allocation fields.
- Fixed cached Origin context so BOM dropdown options use live Data Hub artifact options even when source data is cached.
- Filtered Data Hub BOM dropdown options to flattened artifacts only.
- Added regression coverage for compact JSON Origin actions, cached live BOM options, and non-flattened artifact filtering.
- Verification run: `uv run pytest` passed with `195 passed`.

## Next Steps
1. Continue the client-side Origin calculation migration: render/calculation from `calculation-payload`, add explicit save semantics, and remove most hidden material/allocation fields after parity tests are in place.
2. Decide how Data Hub should provide NVL origin classification for C/O; Growatt still has conservative origin warnings when material catalog lacks classification evidence.
3. Decide whether duplicate finished-product codes can occur in one dossier. If yes, replace product-code keyed sheet state with a stable line identity.
4. Consider cleaning or archiving smoke case `co-case-e44fe2065b62` if it should not remain in local data.

## Blockers
- Growatt origin classification data remains incomplete; CO can allocate stock/value evidence but still defaults unclassified NVL to conservative non-origin.
- `npm test` has previously had unrelated legal lookup failures around `raw-binary` source links; Python CO tests pass.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User is sensitive to slow UX and dislikes hidden reloads. Keep case interactions shell/AJAX-based and avoid large hidden-form payloads.
- CO is a Data Hub consumer. Do not add raw `/v1/hub/*` calls outside `app/data_hub_client.py`, and do not invent Data Hub endpoints from CO.
- Data Hub BOM artifact options for Origin should come from live Data Hub workspace by BOM product code, not only from saved case snapshots.
- For `growatt-vn / SD00.0010600`, CO currently sees 4 flattened selectable artifact options after filtering, while 2 non-flattened artifacts remain excluded from the dropdown.
- Known unrelated dirty/untracked files before this handoff remain outside the focused commit: `docs/co-form-index-confirmation.*`, `.ai/screenshots/co-case-origin-ux/`, `.ai/screenshots/co-case-overview-lock/`, `.ai/screenshots/co-origin-sequence-lock/`, `.ai/screenshots/data-hub-e2e/`, `.ai/sister-app-notes/2026-05-07-bom-presets-3b.md`, and `.ai/sister-app-prompts/`.
