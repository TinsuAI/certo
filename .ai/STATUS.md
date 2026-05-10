# Project Status

## Current State
- Active branch: `main`; do not push unless user asks.
- CO dev server was restarted during this session and should be available at `http://127.0.0.1:8001`; auth is enabled, so unauthenticated origin URLs redirect to Data Hub SSO.
- Local Data Hub was live at `http://127.0.0.1:8754` during verification. CO local runtime config was migrated from `DATA_HUB_API_TOKEN` to `DATA_HUB_SERVICE_TOKEN`.
- CO now matches the current Data Hub consumer vocabulary:
  - client runtime config reads use `GET /client-config`,
  - BCCT/invoice matching requests use `include_material_identity=true`,
  - product identity vocabulary is now `material_identity`,
  - Data Hub BOM reads use artifact vocabulary,
  - C/O BOM UI/form fields prefer artifact naming with compatibility fallback for saved `version_*` fields,
  - CO no longer calls Data Hub code-mapping endpoints for BOM resolution.
- Origin workflow still uses server-rendered forms with AJAX shell replacement. Warning filters and column toggles now re-bind after shell replacement.
- Data Hub material identity now drives CO stock allocation: import rows prefer `material_identity.internal_code` for allocation, while lot evidence still traces to `source_row` / transaction / declaration / line.

## Recent Changes
- Migrated CO Data Hub adapter/settings/docs/tests from old `product_identity`, `/co-config`, `DATA_HUB_API_TOKEN`, and BOM version vocabulary to `material_identity`, `/client-config`, `DATA_HUB_SERVICE_TOKEN`, and BOM artifact vocabulary.
- Updated Data Hub BOM adapter methods and BOM service normalization to use artifact APIs while keeping legacy fields as compatibility aliases for saved cases and local fallback stores.
- Updated C/O origin/BOM templates to display artifact vocabulary and submit `bom_artifact_id` / `bom_product_artifact_id` fields with fallback reads from older version fields.
- Fixed origin warning summary and column control buttons after AJAX case-shell replacement.
- Fixed Data Hub-mode CO stock allocation so Growatt import rows like `DAYTINHIEU -> 012.0002700` use `material_identity.internal_code` and can match BOM material codes.
- Browser E2E against Data Hub SSO created smoke case `E2E-DH-220630` / `co-case-e44fe2065b62`, opened Origin, calculated the sheet, verified filters/toggles, then released the origin lock.
- Verification run: `uv run pytest` passed with `190 passed`.

## Next Steps
1. Replace large hidden origin form state with JSON payload endpoints per `.ai/features/2026-05-08-client-side-origin-calculation.md`.
2. Decide how Data Hub should provide NVL origin classification for C/O; Growatt smoke still shows `Chưa phân loại xuất xứ` because 122 NVL have no origin classification evidence.
3. Decide whether duplicate finished-product codes can occur in one dossier. If yes, replace product-code keyed sheet state with a stable line identity.
4. Consider cleaning or archiving smoke case `co-case-e44fe2065b62` if it should not remain in local data.

## Blockers
- Data quality remains incomplete for Growatt origin classification: C/O can now allocate stock/value evidence, but still calculates conservative non-origin status when Data Hub/material catalog lacks origin classification.
- `npm test` has previously had unrelated legal lookup failures around `raw-binary` source links; Python CO tests pass.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User is sensitive to slow UX and dislikes hidden reloads. Keep case interactions shell/AJAX-based, but avoid huge hidden-form payloads.
- CO is a Data Hub consumer. Do not add raw `/v1/hub/*` calls outside `app/data_hub_client.py`, and do not invent Data Hub endpoints from CO.
- Important distinction: material code is used to find candidate stock lots; actual stock evidence must remain tied to `source_row` / `source_transaction_key` / declaration number / line number.
- Known unrelated dirty/untracked files before this handoff include `docs/co-form-index-confirmation.*`, `.ai/screenshots/co-case-origin-ux/`, `.ai/screenshots/co-case-overview-lock/`, `.ai/screenshots/co-origin-sequence-lock/`, `.ai/sister-app-notes/2026-05-07-bom-presets-3b.md`, and `.ai/sister-app-prompts/`.
- New E2E screenshots from this session are under `.ai/screenshots/data-hub-e2e/`; they are verification artifacts and are not required for the code commit unless explicitly desired.
