# Project Status

## Current State
- Active branch: `main`.
- CO dev server is running at `http://127.0.0.1:8001`; unauthenticated requests still redirect to `/auth/login`.
- Sibling Data Hub dev server is running at `http://127.0.0.1:8754`.
- CO remains a Data Hub consumer. Data Hub API calls should stay behind `app/data_hub_client.py`; do not add raw `/v1/hub/*` calls elsewhere.
- The C/O origin tab now builds a real LVC statement from invoice-matched BCCT export rows, Data Hub/local BOM rows, BCCT-derived CO stock rows, and material catalog fallback.
- Case `growatt-vn/co-case-f78ab7a0ba8b` with invoice `GUS28826A131-3F` now rebuilds stale origin snapshots, shows FOB/customs value as `8,710,950,816 VND`, keeps declared tờ khai currency separately as `USD`, and finds unit values for most BOM materials from BCCT import/CO stock.
- Product-level BOM selection is now supported in the origin GUI. Each TP gets a `BOM TP` dropdown populated from `bom_workspace.product_version_options_by_code`; changing it rebuilds the LVC snapshot and persists `bom_product_version_overrides`.
- Current Data Hub data for `SD00.0010600` exposes only one BOM version, so the dropdown appears but has one option in that case.
- Pre-existing untracked discovery artifacts remain separate and were not part of this session:
  - `.ai/features/2026-05-02-co-bom-data-hub-migration.md`
  - `.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md`
  - `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md`

## Recent Changes
- Added LVC statement construction in `app/main.py` using BCCT export value, selected BOM rows, BCCT import/CO stock valuation, and material catalog fallback.
- Added stale origin snapshot detection with build signatures, so saved cases rebuild when source/BOM/stock inputs change.
- Added per-product BOM version switching in the origin UI and Data Hub BOM workspace support for multiple product BOM versions when `/bom/versions` exposes them.
- Added numeric formatting and explicit value currency display in `app/templates/co_case.html`; `total_value/customs_value` is treated as VND and no longer displayed with declared foreign currency.
- Extended source/Data Hub normalization to carry `value_currency`, CO-stock unit value, material currency, and export declared currency separately.
- Extended dossier workbook export with currency columns in the `LVC Statement` sheet.
- Added regression coverage in `tests/test_co_demo.py` and `tests/test_data_hub_integration.py` for LVC valuation from BCCT stock, stale snapshot rebuild, BOM dropdown switching, Data Hub multi-version BOM options, and VND-vs-declared-currency handling.

## Verification
- `uv run pytest -q` passed: 149 tests.
- `git diff --check` passed.
- Runtime context check for `growatt-vn/co-case-f78ab7a0ba8b` showed `fob=8710950816`, display `currency=VND`, `declared_currency=USD`, and first material unit value in `VND`.

## Next Steps
1. Review remaining 12 BOM material codes in case `co-case-f78ab7a0ba8b` that still lack BCCT import/CO-stock unit value: `018.0888201`, `018.0888301`, `018.0888401`, `018.0888501`, `020.0068000`, `940.0222900`, `960.0005900`, `960.0024200`, `B700.0202900`, `B700.0277100`, `B700.0277200`, `TV03.0015200`.
2. Confirm with Data Hub/data team whether missing material codes are absent from BCCT import data, mapped under alternate internal/customs codes, or need additional allocation mapping.
3. Continue replacing placeholder PSR lookup with the real legal PSR engine and durable allocation ledger.
4. When Data Hub adds more BOM versions for a TP, verify the dropdown against live multi-version data, not just tests.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese when the user writes Vietnamese.
- User is sensitive to wrong business logic and currency labels. For customs data, never assume `currency` labels `total_value/customs_value`; those fields are VND when sourced from BCCT customs value. Keep declared foreign currency separate.
- The user wants the origin GUI to be a practical operator bảng kê LVC, not a generic “Xuất xứ” view with unrelated fields.
- Do not reintroduce criteria workbook upload in the C/O origin tab; criteria should be system-generated.
- Do not infer C/O market from Vietnam-side logistics fields like `destination_location_name = CANG LACH HUYEN HP`.
- Keep Data Hub API literals inside `app/data_hub_client.py`; `tests/test_data_hub_policy.py` enforces this.
- Do not commit or modify the pre-existing untracked `.ai/features/...` and `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md` files unless asked.
