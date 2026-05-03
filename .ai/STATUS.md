# Project Status

## Current State
- Active branch: `main`.
- CO dev server is running at `http://127.0.0.1:8001`; unauthenticated requests redirect to `/auth/login`.
- Sibling Data Hub dev server is running at `http://127.0.0.1:8754`.
- CO remains a Data Hub consumer. Keep raw `/v1/hub/*` endpoint strings inside `app/data_hub_client.py`; `tests/test_data_hub_policy.py` enforces this.
- CO form index is now configurable in-app at `/settings/co-forms` for priority forms `B`, `CPTPP`, `EUR.1`, and `AI`, including market aliases and HS-scope PSR preview rules.
- Default PSR seed is extracted from the local legal corpus: `B` 5,609 rows, `CPTPP` 1,156 rows, `EUR.1` 128 rows, `AI` 1 general AIFTA rule. `EUR.1` still needs refresh/confirmation against `14/2026/TT-BCT`.
- Client-facing confirmation workbook is at `docs/co-form-index-confirmation.xlsx`. Tab `04_HS kiểm trước` prioritizes export products/HS from Growatt, Johnson, DKE, and Đô Thành across sibling projects under `/home/vp/workspace/client`.
- Invoice entry on the C/O shipment screen now supports lookup/preview before save: BCCT export matches, HS/product summary, market hint explanation, and explicit “Dùng thị trường …” action. It no longer silently sets `destination_market` from invoice hints on create/update.
- Latest UI check used local no-auth server `http://127.0.0.1:8013` temporarily; it was killed after screenshots. Final screenshots are under `.ai/screenshots/co-invoice-preview/`.
- Pre-existing untracked artifacts remain separate and are not part of this work unless explicitly requested:
  - `.ai/features/2026-05-02-co-bom-data-hub-migration.md`
  - `.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md`
  - `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md`

## Recent Changes
- Added runtime C/O form config storage, tabbed admin UI, market alias editor, and filtered HS Criteria editor.
- Wired `app/co_forms.py` to configurable forms/market presets/PSR rules, with HS matching by specificity and guarded handling for `ex` HS scopes.
- Added legal-corpus PSR extraction for Form B/CPTPP/EUR.1 and a conservative Form AI AIFTA rule (`LVC/RVC 35% FOB + CTSH`) because no official public all-HS AI PSR table was found.
- Created `docs/co-form-index-confirmation.md` and `docs/co-form-index-confirmation.xlsx` for Trọng Tín confirmation, then expanded the priority HS tab using Growatt, Johnson, DKE, and Đô Thành export data.
- Added Data Hub invoice match market hint consumption through `app/data_hub_client.py` with `include_market_hint=true`.
- Replaced silent invoice market inference with explicit invoice preview UI and JSON endpoint `GET /clients/{client_id}/co-case/invoice-preview`.
- Fixed the shipment screen layout after review: invoice preview now spans the form, duplicate side preview was removed, and fallback Form B is not overwritten by client-side market preview JS.
- Added/updated regression tests for configurable form index, Data Hub invoice hints, invoice preview behavior, and workflow screens.

## Verification
- Targeted invoice/workflow tests passed:
  - `uv run pytest tests/test_co_demo.py::test_co_case_create_explains_invoice_market_hint_without_auto_selecting tests/test_co_demo.py::test_co_case_shipment_step_updates_metadata_without_dropping_origin_view tests/test_co_case_guidance_maps_invoice_bcct_products_to_form_instrument_and_hs_criteria -q`
  - `uv run pytest tests/test_data_hub_policy.py -q`
- Final full suite after the invoice preview layout polish passed: `uv run pytest -q -x` passed `158` tests in `240.41s`.
- `git diff --check` passed after the final layout changes.
- `docs/co-form-index-confirmation.xlsx` opens/saves with `openpyxl`; tab `04_HS kiểm trước` has `44` priority rows covering `4` clients, `11` export HS groups, and `4` priority forms.
- Visual screenshots after layout fix:
  - `.ai/screenshots/co-invoice-preview/after-3.png`
  - `.ai/screenshots/co-invoice-preview/after-3-mobile-full.png`

## Next Steps
1. Send `docs/co-form-index-confirmation.xlsx` to Trọng Tín and update `/settings/co-forms` if they correct market aliases, HS scopes, or criteria.
2. If real search-as-you-type invoice suggestions are required from live Data Hub, create a Data Hub API request first. Current CO preview uses exact invoice match plus local/source-workspace option filtering; do not invent a new Data Hub endpoint in CO.
3. Continue replacing the configurable PSR preview with the durable legal PSR engine and allocation ledger.
4. Migrate/normalize missing Growatt legacy BCCT import data into Data Hub before relying on all LVC valuations for `growatt-vn`.

## Blockers
- Form AI still has only the general AIFTA rule from available sources. Any HS-specific AI PSR rows need Trọng Tín or official source confirmation.
- Live Data Hub Growatt data still lacks some legacy BCCT import evidence needed for complete BOM material valuation.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User is sensitive to hidden business logic. Do not silently infer market/form from invoice; show the evidence and require operator action.
- For customs data, never assume `currency` labels `total_value/customs_value`; BCCT customs values are VND and declared foreign currency must stay separate.
- Do not reintroduce criteria workbook upload in the C/O origin tab; criteria should be system-generated/configured.
- Do not infer C/O market from Vietnam-side logistics fields like `destination_location_name = CANG LACH HUYEN HP`.
- Keep Data Hub API literals inside `app/data_hub_client.py`.
- Do not commit or modify the pre-existing untracked `.ai/features/...` and `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md` files unless asked.
