# Session: CO Origin LVC BOM Switching

## What Was Done
- Refreshed project context and kept the CO dev server available at `http://127.0.0.1:8001` with Data Hub running at `http://127.0.0.1:8754`.
- Reworked the C/O origin step so the LVC statement is built from real invoice + BCCT + BOM data:
  - invoice-matched BCCT export rows provide TP quantity and value
  - selected BOM rows provide material consumption
  - BCCT import-derived CO stock rows provide unit values and material values
  - material catalog remains only a fallback for material metadata/value
- Added CO stock valuation fields in `app/source_store.py`: `customs_value`, `unit_value`, `unit_value_source`, `value_currency`, and source transaction metadata.
- Added `stock_rows` into case source context for file, Postgres, and Data Hub modes.
- Fixed Data Hub source context to enrich invoice matches with full BCCT export values, since `/v1/hub/bcct/invoice-matches` did not return `total_value/customs_value`.
- Added stale origin snapshot detection with a build signature. Saved cases now rebuild origin products when invoice/BOM/material/stock inputs change; posted form data can still be preserved for export.
- Added per-product BOM switching:
  - origin GUI shows a `BOM TP` dropdown per finished product
  - dropdown is populated from `bom_workspace.product_version_options_by_code`
  - changing the dropdown submits the form and rebuilds the LVC statement
  - selected product BOM versions persist through `bom_product_version_overrides`
- Updated Data Hub BOM service to expose multiple product BOM versions when `/v1/hub/products/{product_code}/bom/versions` returns multiple versions.
- Reformatted origin statement numbers with thousands separators and explicit currency display.
- Corrected currency handling:
  - `customs_value` / `total_value` from BCCT is treated as VND
  - declared foreign currency, such as `USD`, is kept separately as `declared_currency`
  - material unit values from BCCT import/CO stock use `value_currency`
- Added currency columns to the exported `LVC Statement` worksheet.
- Added regression tests for:
  - LVC valuation sourced from BCCT import/CO stock instead of only material catalog
  - stale origin snapshot rebuild
  - product BOM version dropdown switching
  - Data Hub multi-version BOM workspace options
  - Data Hub invoice enrichment with VND value currency

## Decisions Made
- Treat Data Hub and local BCCT `total_value/customs_value` as customs value in VND, not as a value in the row's declared `currency`.
- Keep declared tờ khai currency separate from calculation/display value currency to avoid false values such as `8.7B USD`.
- Preserve posted origin form data only for form/export flows; normal GET of origin can rebuild stale snapshots when source signatures change.
- Product-level BOM selection is represented by existing `product_N_bom_product_version_id` form fields and persisted as `bom_product_version_overrides`, avoiding a new persistence model.
- Data Hub endpoint consumption remains centralized in `app/data_hub_client.py` and `app/bom_service.py`; no raw hub URL strings were added outside the existing adapter boundary.

## What Didn't Work
- Initial LVC logic only considered BOM/material catalog values and did not pull valuation from BCCT import/CO stock, causing `Thiếu đơn giá NVL`.
- Persisted case `co-case-f78ab7a0ba8b` kept an old `origin_snapshot`, so GUI appeared unchanged until stale snapshot rebuild logic was added.
- `invoice-matches` alone was insufficient for FOB/customs value because it returned the matched export row without `total_value`; the code now enriches matches from full BCCT rows.
- Displaying `total_value` with the row's declared `currency` was wrong for customs data; `8,710,950,816` is VND, not USD.

## Open Items
- Case `growatt-vn/co-case-f78ab7a0ba8b` still has 12 BOM material codes without BCCT import/CO-stock unit value:
  `018.0888201`, `018.0888301`, `018.0888401`, `018.0888501`, `020.0068000`, `940.0222900`, `960.0005900`, `960.0024200`, `B700.0202900`, `B700.0277100`, `B700.0277200`, `TV03.0015200`.
- Need confirm whether those missing codes require Data Hub import data, alternate code mapping, or allocation rules.
- Live `SD00.0010600` currently has only one Data Hub BOM version; dropdown multi-version behavior is covered by tests but needs live verification when data exists.
- Legal PSR and allocation ledger remain future work; current LVC statement is the operator-facing calculation surface, not final legal origin adjudication.
