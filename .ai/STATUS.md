# Project Status

## Current State
- Active branch: `main`; do not push unless user asks.
- Local CO dev server running at `http://127.0.0.1:8001`; `/healthz` returned `{"status":"ok"}` on 2026-05-07.
- `growatt-vn` Data Hub context now loads through CO after adapting BOM calls from Data Hub `versions` vocabulary to `artifacts`; direct `client_context("growatt-vn", "overview")` succeeded with Data Hub source and 162 BOM product versions.
- CO remains Data Hub consumer; raw `/v1/hub/*` endpoint strings stay in `app/data_hub_client.py`; `tests/test_data_hub_policy.py` enforces this.
- C/O dual shipment reference model remains active: invoice optional, export declarations optional, declaration-authoritative when present, invoice used for fallback and mismatch/missing-reference warnings.
- Create and shipment forms now surface invoice/export declaration reference warnings immediately, not only in the Export tab.
- C/O origin allocation remains snapshot-only with customer-scoped soft lock; no global shared stock decrement/reservation yet.
- Dossier deletion guardrails remain implemented.
- Pre-existing unrelated artifacts remain separate and should not be committed unless requested: `docs/co-form-index-confirmation.md`, `docs/co-form-index-confirmation.xlsx`, `.ai/screenshots/...`, `.ai/sister-app-notes/`.

## Recent Changes
- Added live/server-rendered warning UX for invoice vs export declaration mismatches:
  - `/co-case/invoice-preview` accepts `export_declaration_nos`
  - create form and shipment form render `Kiểm tra invoice / tờ khai xuất`
  - JS rechecks when invoice or declaration input changes
  - declaration-only and missing `invoice_ref` warnings still work
- Updated Data Hub BOM adapter for Data Hub's vocabulary/API change:
  - `/v1/hub/products/{product_code}/bom/artifacts` replaces `/bom/versions`
  - pinned BOM fetch uses `artifact_id`
  - CO normalizes artifacts back to internal `version_id`/`version_no` to avoid broad app refactor
  - proposals now send `parent_artifact_id`
- Added regression coverage for immediate reference warnings and updated Data Hub endpoint contract tests/policy.
- Verification:
  - targeted warning tests passed
  - targeted Data Hub adapter tests passed
  - `client_context("growatt-vn", "overview")` succeeded
  - `uv run pytest` passed: `181 passed in 28.12s`
  - `/healthz` returned `{"status":"ok"}`

## Next Steps
1. Browser-check `http://localhost:8001/clients/growatt-vn` after server reload and verify it no longer 500s.
2. Test live mismatch warning on `growatt-vn`:
   - `Invoice`: `WRONG-INVOICE`
   - `Số tờ khai xuất`: `308449399330`
   - expected warning: `Invoice nhập WRONG-INVOICE không khớp invoice_ref GUS28826A131-3F trên tờ khai 308449399330.`
3. Manually review create/shipment forms with real data:
   - invoice-only
   - declaration-only
   - matching invoice + declaration
   - mismatched invoice + declaration
   - declaration with missing `invoice_ref`
4. Confirm whether multi-declaration dossiers need manual row selection.
5. Confirm production completed-dossier status values for delete blocking.
6. Decide whether global stock reservation/decrement belongs in Data Hub later.
7. Revisit mixed-currency allocation rules before automatic VNM summing.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User wants concise but non-black-box explanations: say what was inspected, what failed, and how resolved.
- The term to use in Vietnamese UI is “dòng tồn”, not “lot”.
- The previous local test pair `INV-WRONG`/`XK-RIGHT` is unit-test-only; for live `growatt-vn` use `WRONG-INVOICE` + `308449399330`.
- Data Hub has active uncommitted BOM rename work in sibling repo `/home/vp/workspace/client/data-hub`; CO had to adapt to `/bom/artifacts` while keeping internal `version_id` compatibility.
- Do not add Data Hub endpoints from CO casually. This session consumed an already-running Data Hub endpoint that replaced the old alias; all raw endpoint strings remain in `app/data_hub_client.py`.
- Do not commit unrelated `docs/co-form-index-confirmation.*`, `.ai/screenshots/*`, or `.ai/sister-app-notes/` unless requested.
