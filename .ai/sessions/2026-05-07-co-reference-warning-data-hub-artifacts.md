# Session: CO Reference Warning And Data Hub Artifact Endpoint

Date: 2026-05-07

## What Was Done
- Refreshed project state and kept local CO dev server running at `http://127.0.0.1:8001`.
- Identified the immediate next workflow: browser validation of the dual-reference C/O flow.
- Provided manual test data, then corrected the guidance after discovering `INV-WRONG` / `XK-RIGHT` was only a unit-test fixture.
- Implemented immediate invoice/export declaration warnings on C/O create and shipment forms.
  - `invoice-preview` now accepts `export_declaration_nos`.
  - Preview payloads include `reference_warnings`.
  - Create and shipment forms render a `Kiểm tra invoice / tờ khai xuất` warning panel.
  - Frontend JS refreshes warnings when invoice or export declaration input changes.
  - Existing export-tab warning remains.
- Investigated `Internal Server Error` on `http://localhost:8001/clients/growatt-vn`.
  - First failure came from Data Hub `/v1/hub/bcct` selecting `artifact_id` before migration was applied.
  - After Data Hub migration applied, the remaining failure was CO calling old BOM endpoint `/bom/versions`, which Data Hub redirects to `/bom/artifacts` with 308.
- Updated `app/data_hub_client.py` for Data Hub's BOM artifact vocabulary.
  - List BOM artifacts through `/v1/hub/products/{product_code}/bom/artifacts`.
  - Fetch pinned BOM with `artifact_id`.
  - Normalize Data Hub `artifact_id`/`artifact_no` back to internal `version_id`/`version_no`.
  - Normalize dual-source conflict variants.
  - Submit BOM proposals with `parent_artifact_id`.
- Updated Data Hub integration/policy tests for the artifact endpoint.
- Verification:
  - targeted C/O warning tests passed
  - targeted Data Hub adapter tests passed
  - direct `client_context("growatt-vn", "overview")` succeeded
  - full `uv run pytest` passed with `181 passed in 28.12s`
  - `/healthz` returned `{"status":"ok"}`

## Decisions Made
- Warnings for invoice/declaration inconsistencies belong directly in the create/shipment workflow, not only in the export match table.
- Keep CO's internal naming as `version_id`/`version_no` for now, while adapting Data Hub artifact payloads at the adapter boundary.
- Use Data Hub's new `/bom/artifacts` contract instead of following 308 redirects from the deprecated `/bom/versions` alias.
- Keep raw Data Hub endpoint references centralized in `app/data_hub_client.py`.

## What Didn't Work
- The first mismatch example `INV-WRONG` / `XK-RIGHT` did not show a browser warning because that pair only exists in unit tests and was not in the live source data.
- Initially checking only Data Hub `/bcct` was insufficient. The browser page still failed because the next failing boundary was BOM: `/bom/versions` redirecting to `/bom/artifacts`.
- The Data Hub 500 was not caused by CO's warning UI. It was a Data Hub schema/code mismatch while BOM vocabulary rename migration was being applied.

## Open Items
- Browser-confirm `http://localhost:8001/clients/growatt-vn` after reload.
- Browser-test live warning with `WRONG-INVOICE` + `308449399330`.
- Continue manual review of dual-reference scenarios with real customer data.
- Decide whether multi-declaration dossiers need manual row selection.
- Confirm final production completed-dossier statuses for delete blocking.
- Decide whether global shared stock reservation/decrement belongs in Data Hub.
- Revisit mixed-currency allocation rules before automatic VNM summing.
