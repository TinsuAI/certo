# Session: CO Dossier Polish

## What Was Done
- Refreshed the project context from `AGENTS.md`, `.ai/STATUS.md`, `.ai/DECISIONS.md`, and recent session summaries.
- Restarted/reused the CO dev server at `http://127.0.0.1:8001`; Data Hub was already running at `http://127.0.0.1:8754`.
- Polished the C/O dossier workflow:
  - generated case codes when operators leave `case_code` blank
  - added data-aware workflow step statuses and Vietnamese labels
  - added stored supporting-file download links and a safe download route
  - changed the origin tab from edit-heavy product/material inputs to a read-first calculation surface backed by hidden snapshot fields
  - removed the legacy `Xuất evidence XLSX` action from the C/O origin workflow
  - replaced visible "coming soon" copy with Vietnamese operational copy
- Added tests for the new dossier behavior:
  - generated case codes
  - workflow status labels
  - supporting file download
  - origin tab no longer exposing table inputs or evidence export
- Captured browser screenshots under `.ai/screenshots/co-dossier-polish/`.
- Investigated why `http://localhost:8001/clients/growatt-vn/co-case/co-case-cd2e73c5250a/origin` showed demo rows:
  - the case has invoice `GIN01425L031`
  - Data Hub returns `0` invoice matches for that invoice
  - `origin_demo_active=True`, so the tab is showing `Demo tự nạp`
- Verified Data Hub no-auth read API after the user toggled auth:
  - `GET /v1/hub/dncxs` returns `200` without bearer
  - `GET /v1/hub/bcct/invoice-matches?...GUS28826A131-3F...` returns `200` and one E42 row
  - CO itself still redirects unauthenticated users to `/auth/login`
- Investigated whether CO can infer market from BCCT:
  - local parsed BCCT has `unloading_location` from raw `Địa điểm dỡ hàng`, e.g. `USLAX`, `INMAA`, `INNSA`
  - Data Hub BCCT list exposes destination/consignee fields, but `invoice-matches` does not return `unloading_location` or `consignee_name`
  - `destination_location_name` is Vietnam-side logistics data and must not be used as the importing market
- Created `.ai/api-requests/2026-05-03-bcct-invoice-market-fields.md` using the Data Hub API request protocol.

## Decisions Made
- Keep the C/O origin tab read-first. It can still post snapshot data for recalculation, but operators should not be dropped into a spreadsheet-like edit grid as the main experience.
- Keep `Demo tự nạp` only as an explicit fallback when invoice/BCCT/BOM data is not enough; do not persist demo data into case records or exports.
- Do not implement CO market inference against unapproved Data Hub fields. The Data Hub contract must first expose `unloading_location` / `market_hint`.
- Use `unloading_location` as the primary market signal because it carries UN/LOCODE-style prefixes (`US`, `IN`). Do not use `destination_location_name` for market because observed values are Vietnam-side ports or bonded transport destinations.
- Data Hub contract request is additive to `/v1/hub/bcct/invoice-matches` rather than a new endpoint, so existing consumers can keep working.

## What Didn't Work
- Testing `growatt-vn` case `co-case-cd2e73c5250a` with invoice `GIN01425L031` did not produce real origin products because Data Hub returned no invoice matches.
- Disabling Data Hub auth was not enough to make CO UI public; CO has its own `CO_AUTH_REQUIRED` setting and still redirects unauthenticated requests to `/auth/login`.
- A sub-agent exploration attempt errored with a token refresh issue. Direct targeted reads and Data Hub API checks were enough to complete the investigation.
- Data Hub `invoice-matches` currently strips the market-relevant fields from BCCT rows, so CO cannot infer market from that endpoint yet.

## Open Items
- Data Hub side: approve and implement `.ai/api-requests/2026-05-03-bcct-invoice-market-fields.md`.
- CO side after approval: extend `app/data_hub_client.py` to preserve the added invoice-match fields and add market-hint inference with manual confirmation on missing/conflicting hints.
- Re-test known invoices after the Data Hub contract lands:
  - `GUS28826A131-3F` currently returns one Data Hub E42 row
  - `GIN01425L031` currently returns zero Data Hub rows for `growatt-vn`
- Continue replacing demo origin calculation with real legal PSR engine, allocation ledger, and durable case-level Data Hub BOM binding.
- Existing pre-session untracked artifacts remain outside this work unless explicitly requested:
  - `.ai/features/2026-05-02-co-bom-data-hub-migration.md`
  - `.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md`
  - `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md`
