# Session: C/O Form Index And Invoice Preview

## What Was Done
- Built a configurable C/O form index for priority forms `B`, `CPTPP`, `EUR.1`, and `AI`.
- Added `app/co_form_config_store.py` for runtime config persistence and `app/templates/co_form_settings.html` for a tabbed admin workspace covering forms, markets, and HS criteria.
- Reworked `app/co_forms.py` so market/form guidance and HS criteria previews read from config instead of fixed in-code seeds.
- Added legal-corpus extraction in `app/co_form_psr_index.py`, producing default PSR rules for Form B, CPTPP, EUR.1, and one conservative Form AI rule.
- Treated `ex` HS scopes as conditional/manual lookup rows so HS-only matching does not incorrectly apply a partial-heading rule to every product in the heading.
- Created `docs/co-form-index-confirmation.md` and `docs/co-form-index-confirmation.xlsx` for Trọng Tín confirmation.
- Expanded the workbook priority HS tab across sibling projects under `/home/vp/workspace/client`:
  - Growatt: `85044090`, `85076039`, `85371099`, `90328931`
  - Johnson: `95069100`
  - DKE: `85249900`, `85285910`
  - Đô Thành: `85419000`, `76169990`, `76042190`, `76109099`
- Added Data Hub invoice-match market hint consumption with `include_market_hint=true`.
- Added invoice preview endpoint `GET /clients/{client_id}/co-case/invoice-preview`.
- Changed the C/O create/shipment flow so invoice hints no longer silently set `destination_market`; the UI shows BCCT matches, HS/product summary, market hint reasoning, and an explicit button to apply the suggested market.
- Fixed the shipment screen layout after visual review: invoice preview now spans the form, duplicate right-side product preview was removed, and fallback Form B preview is not reset to “Chọn thị trường”.
- Saved final visual checks under `.ai/screenshots/co-invoice-preview/after-3.png` and `.ai/screenshots/co-invoice-preview/after-3-mobile-full.png`.

## Decisions Made
- Keep Form AI as `LVC/RVC 35% FOB + CTSH` until Trọng Tín or an official source confirms HS-specific PSR rows. Online sources found the general AIFTA rule but not a reliable all-HS PSR table.
- Store C/O form/market/PSR configuration in JSON for now. This is enough for current admin UI and review workflow; DB storage can wait until config ownership, audit, and multi-user requirements are clearer.
- Do not silently infer market/form from invoice data. Even high-confidence hints are now presented with source field/value and require explicit operator action.
- Use existing Data Hub `invoice-matches` contract for exact invoice preview. True remote prefix/fuzzy invoice search needs a Data Hub-side endpoint request rather than raw or assumed CO calls.
- Use workbook `docs/co-form-index-confirmation.xlsx` as the confirmation artifact for Trọng Tín because it supports multi-sheet guidance, editable confirmation columns, and broad PSR review better than a single markdown doc.

## What Didn't Work
- The first invoice preview UI squeezed the preview panel into a narrow form column, producing a tall, hard-to-read layout. The fix was to make the invoice lookup span the full shipment form and remove duplicated side content.
- Market preview JS reset Form B to “Chọn thị trường” when United States matched only through fallback behavior rather than an explicit market preset. The JS now preserves existing preview when the typed market has no direct option match.
- Running a no-auth local server with `DATA_HUB_ENABLED=0` could not load `growatt-vn` because that client exists in Data Hub/local Data Hub mode, not seed file mode. A second temporary server with only `CO_AUTH_REQUIRED=0` was used for screenshots and then killed.
- Data Hub exact invoice match is enough for preview after the user enters/picks an invoice, but not a complete remote searchable invoice index.

## Open Items
- Send `docs/co-form-index-confirmation.xlsx` to Trọng Tín and update config based on their confirmation.
- Add a Data Hub API request if live invoice prefix/fuzzy search is required beyond local/source-workspace options.
- Replace the configurable PSR preview layer with the durable legal PSR engine.
- Keep working on Data Hub migration/normalization for Growatt legacy BCCT import rows, especially the missing BOM material valuation evidence.
- Full test suite passed after the latest UI polish: `uv run pytest -q -x` passed `158` tests in `240.41s`.
