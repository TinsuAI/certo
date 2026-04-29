# 2026-04-29 CO Dossier Supporting Files

## What Was Done
- Created branch `sprint/co-case-supporting-files-20260429` for the sprint.
- Added a discovery brief for the dossier workflow and form guidance scope at `.ai/features/2026-04-29-co-dossier-supporting-files-and-form-guidance.md`.
- Implemented persisted C/O case records in `app/co_case_store.py`, stored under `CO_CASE_STORE_ROOT` or `data/local/co-cases`.
- Added supporting-file upload with a 20 MB limit, extension allowlist, safe filenames, and invoice/B/L metadata capture.
- Added invoice matching from a C/O case to reviewed BCCT export rows, filtered by configured export declaration types.
- Added source-backed form guidance in `app/co_forms.py` for Form B, AI, CPTPP, and EUR.1.
- Extended the C/O case UI to create/open cases, upload supporting files, view form guidance, inspect BCCT invoice matches, preview a criteria table, and export a dossier workbook.
- Added XLSX export with sheets for case metadata, supporting files, BCCT invoice matches, form guidance, and criteria.
- Expanded regression tests around persistence, invoice matching, upload validation, form guidance, and workbook export.
- Prepared a manual-test case for Growatt under the temp runtime store: `TEST-AI-GIN01424L171`, invoice `GIN01424L171`, destination India/AI flow.

## Decisions Made
- Treat `temp/CO-TABLE-FORM.jpg` as an operational matrix, not legal authority.
- Keep form guidance advisory and source-backed. The app shows the relevant form/instrument candidate, but it does not claim final legal qualification without HS-specific PSR lookup.
- Model Form B as the non-preferential fallback under `05/2018/TT-BCT`; it is not part of the preferential matrix.
- Match BCCT by invoice only against `direction == export`, `review_status == reviewed`, and configured relevant export declaration types.
- Preserve demo compatibility by keeping the base `/co-case` route as the seed/demo view and using `/co-case/{case_id}` for persisted dossier detail.
- Store manual testing data under `temp/user-test/co-cases` so user testing does not pollute project runtime state.

## What Didn't Work
- Initial smoke test used `/clients/demo/...`, which failed with `KeyError: 'demo'` because valid demo client ids include `growatt`, `johnson`, and others. Retested with `growatt`.
- A Node/Puppeteer screenshot attempt failed because `puppeteer` was not installed. Playwright via `uv run --with playwright` worked.
- Early dev server launches were tied to interactive tool sessions and shut down cleanly at turn end. This looked like a crash from the browser, but Uvicorn logs showed normal shutdown and no stack trace. Relaunched detached without `--reload`.
- A review pass found and fixed several issues before handoff: base route auto-opening persisted cases, evaluate dropping metadata, invoice match not filtering reviewed rows, unbounded upload read, and unsanitized export filenames.

## Open Items
- User has not manually tested the feature yet.
- No OCR or semantic parsing exists for uploaded invoice/BL/PDF files.
- No final legal PSR/HS criteria engine exists yet; `needs_rule_lookup` is the correct current state.
- Criteria preview still uses the current demo case product/BOM snapshot, not real stock allocation or consumption.
- Market/member coverage should be hardened against authoritative legal/member datasets before production use.
