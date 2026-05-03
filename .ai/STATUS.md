# Project Status

## Current State
- Active branch: `main`.
- CO dev server is running at `http://127.0.0.1:8001`; unauthenticated requests redirect to `/auth/login`.
- Sibling Data Hub dev server is running at `http://127.0.0.1:8754`.
- CO remains a Data Hub consumer. Keep raw `/v1/hub/*` endpoint strings inside `app/data_hub_client.py`; `tests/test_data_hub_policy.py` enforces this.
- C/O case tab performance was investigated and fixed. Measured on a no-auth local CO server (`http://127.0.0.1:8014`, now stopped) against `growatt-vn/co-case-f78ab7a0ba8b`: normal tabs dropped from about `4.4-4.6s` to `0.5-1.1s`, and the origin tab dropped from about `20.3s` to `0.74s`.
- Runtime C/O form config remains in-app at `/settings/co-forms` for priority forms `B`, `CPTPP`, `EUR.1`, and `AI`, including market aliases and HS-scope PSR preview rules.
- Default PSR seed is extracted from the local legal corpus: `B` 5,609 rows, `CPTPP` 1,156 rows, `EUR.1` 128 rows, `AI` 1 general AIFTA rule. `EUR.1` still needs refresh/confirmation against `14/2026/TT-BCT`.
- Client-facing confirmation workbook is at `docs/co-form-index-confirmation.xlsx`. Tab `04_HS kiểm trước` prioritizes export products/HS from Growatt, Johnson, DKE, and Đô Thành across sibling projects under `/home/vp/workspace/client`.
- Invoice entry on the C/O shipment screen supports lookup/preview before save: BCCT export matches, HS/product summary, market hint explanation, and explicit “Dùng thị trường …” action. It no longer silently sets `destination_market` from invoice hints on create/update.
- Pre-existing untracked artifacts remain separate and are not part of this work unless explicitly requested:
  - `.ai/features/2026-05-02-co-bom-data-hub-migration.md`
  - `.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md`
  - `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md`

## Recent Changes
- Added file-signature caching for sanitized C/O form config so the 2.9 MB runtime PSR config is not reparsed repeatedly during a page request.
- Added an indexed PSR lookup path in `app/co_forms.py` so HS matching no longer scans 6,894 rules repeatedly for every form lane and criteria preview.
- Limited Data Hub BOM workspace loading for C/O origin to product codes present in invoice matches/current case products instead of fetching all BOM products and versions for the client.
- Added short-lived Data Hub BOM workspace caching keyed by Data Hub identity, client, token, and requested product codes.
- Avoided an unnecessary client-side invoice-preview fetch when the shipment tab already rendered invoice preview HTML server-side.
- Confirmed the slowness was mostly CO-side repeated broad loading/indexing, not a single slow Data Hub API call. Direct Data Hub checks were roughly `30ms` for source summary, `49ms` for materials, `125ms` for BCCT page 1, and `135ms` for products.

## Verification
- `uv run pytest -q -x` passed `158` tests in `27.90s`.
- `git diff --check` passed.
- Targeted checks also passed for Form/PSR settings, C/O shipment/origin/guidance, Data Hub BOM adapter behavior, and Data Hub endpoint policy.
- HTTP timings after the fix on the temporary no-auth server:
  - shipment: `1.06s`
  - documents: `0.66s`
  - exports: `0.51s`
  - guidance: `0.55s`
  - origin: `0.74s`
  - review: `0.54s`

## Next Steps
1. Send `docs/co-form-index-confirmation.xlsx` to Trọng Tín and update `/settings/co-forms` if they correct market aliases, HS scopes, or criteria.
2. If real search-as-you-type invoice suggestions are required from live Data Hub, create a Data Hub API request first. Current CO preview still uses exact invoice match plus local/source-workspace option filtering; do not invent a new Data Hub endpoint in CO.
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
