# Project Status

## Current State
- Active branch: `main`.
- CO dev server is running at `http://127.0.0.1:8001`; unauthenticated requests redirect to `/auth/login`.
- Sibling Data Hub dev server remains expected at `http://127.0.0.1:8754`, but this session avoided relying on it because the user said Data Hub data is not stable enough for the customer demo.
- CO remains a Data Hub consumer. Keep raw `/v1/hub/*` endpoint strings inside `app/data_hub_client.py`; `tests/test_data_hub_policy.py` enforces this.
- A self-contained customer demo now exists at `barry-co-interactive-demo.html`. It opens directly in a browser and does not require FastAPI login, Data Hub, or any API calls.
- The static demo models Growatt, C/O workflow, background data, C/O Form Index, customs FX, origin calculation, BOM switching, editable material values/origin, and demo snapshot export.
- Current uncommitted application changes from the prior origin-web-snapshot work remain separate and were not included in this demo commit:
  - `app/main.py`
  - `app/templates/co_case.html`
  - `app/co_case_store.py`
  - `app/demo_data.py`
  - `app/static/css/app.css`
  - `tests/test_co_demo.py`
- Pre-existing untracked artifacts remain separate and should not be committed unless explicitly requested:
  - `.ai/features/2026-05-02-co-bom-data-hub-migration.md`
  - `.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md`
  - `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md`
  - `.ai/sessions/2026-05-04-origin-web-snapshot.md`

## Recent Changes
- Refreshed context from `AGENTS.md`, `.ai/STATUS.md`, `.ai/DECISIONS.md`, and the latest session summaries.
- Started the CO dev server on `http://127.0.0.1:8001`.
- Created `barry-co-interactive-demo.html` as a single-file static customer demo because Data Hub data is currently unstable.
- Built the demo around the current Barry CO product surfaces:
  - company workspace and module navigation
  - C/O case workflow steps: `Lô hàng`, `Chứng từ`, `Tờ khai xuất`, `Form & PSR`, `Xuất xứ`, `Review & xuất`
  - `Danh mục mã hàng`, `BOM`, `Tồn CO`, `BCCT`, `Config`
  - app-level `Tỷ giá hải quan`
  - `C/O Form Index` with overview/forms/markets/HS criteria tabs
- Added client-side interactions:
  - market/form inference from invoice workflow
  - searchable/filterable tables
  - mock upload/save/refresh actions
  - document checklist toggling
  - BOM product version switching
  - editable FOB, material values, consumed quantities, and material origin
  - live Build-down LVC/RVC recalculation
  - origin warning display for missing material valuation
  - demo Origin Snapshot CSV export from the displayed data
- Verification completed:
  - Extracted inline script from `barry-co-interactive-demo.html` and ran `node --check`; passed.
  - Ran a Puppeteer smoke test against the local file; passed key flows for origin tab, BOM variant warning, and catalog/material navigation.
  - Ran `npm test`; it still fails 3 pre-existing legal lookup tests around missing `raw-binary` source links. These failures are unrelated to the new HTML demo.

## Next Steps
1. Open `barry-co-interactive-demo.html` in a browser and run through the customer demo script manually.
2. If the demo direction is accepted, polish customer-facing copy and visual density in the static file before sending it externally.
3. Keep the static demo disconnected from Data Hub until the Data Hub source data is stable enough for live customer use.
4. Review and commit or revise the older origin-web-snapshot application changes separately; they were intentionally not bundled with the static demo commit.
5. For production CO behavior, continue enforcing the Data Hub API guardrail: request approved Data Hub contract changes through `.ai/api-requests/` before consuming new Hub behavior.

## Blockers
- Data Hub data is currently not stable enough for a customer-facing live demo, which is why the new demo is static and self-contained.
- Direct/build-up value-content calculation is still not implemented and should not be inferred from legacy workbook footer cost fields.
- CTC/CTSH in current CO surfaces is still only a preview based on HS comparison; it is not a legal PSR engine.
- Exact template-copy Excel parity for `LVC`, `RVC`, `CTH`, `CTSH`, and `EUR1` has not been implemented yet.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User is sensitive to hidden business logic. Briefly explain what was inspected, what was tried, and what conclusion is evidence-backed.
- The customer demo should be described as static/mock data, not live Data Hub output.
- `npm ci` was run to install ignored `node_modules/` from the existing lockfile so Puppeteer smoke tests could run; no package files changed.
- The static demo intentionally starts at the C/O case workflow because that is the main customer-facing value, with company/data tabs available around it.
- Current origin/product logic demonstrated in the static HTML is Build-down LVC/RVC: `(FOB - VNM) / FOB x 100`.
- Keep Data Hub API literals inside `app/data_hub_client.py`.
