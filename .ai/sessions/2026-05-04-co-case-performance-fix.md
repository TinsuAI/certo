# Session: C/O Case Performance Fix

## What Was Done
- Started the CO dev server at `http://127.0.0.1:8001`; Data Hub was already running at `http://127.0.0.1:8754`.
- Reproduced the user-reported C/O case tab slowness on a temporary no-auth CO server at `http://127.0.0.1:8014`.
- Measured baseline tab loads for `growatt-vn/co-case-f78ab7a0ba8b`:
  - shipment/documents/exports/guidance/review were about `4.4-4.6s`
  - origin was about `20.3s` and returned about `441 KB` of HTML
- Checked Data Hub directly and found individual API calls were not the main bottleneck:
  - source summary about `30ms`
  - materials about `49ms`
  - BCCT page 1 about `125ms`
  - products about `135ms`
- Profiled CO code paths and found repeated CO-side work:
  - repeated read/sanitize of the 2.9 MB C/O form config
  - repeated scans over 6,894 PSR rules for form lanes and criteria preview
  - origin tab loading the full Data Hub BOM workspace for 211 products and 13,715 rows even when the invoice needed one finished product
  - shipment tab making an extra client-side invoice preview request after the server had already rendered the same preview
- Implemented performance fixes:
  - cached sanitized C/O form config by file mtime/size signature
  - indexed PSR rules by form with precomputed HS scope ranges/specificity
  - allowed BOM workspace loading to be filtered by requested product codes
  - added a short-lived Data Hub BOM workspace cache keyed by Data Hub identity, client, token, and product code filter
  - changed C/O origin context to request BOM only for products present in invoice matches/current case state
  - skipped the initial client-side invoice preview fetch when preview markup already exists
- Re-measured after the fix:
  - shipment: `1.06s`
  - documents: `0.66s`
  - exports: `0.51s`
  - guidance: `0.55s`
  - origin: `0.74s`
  - review: `0.54s`

## Decisions Made
- Treat the reported slowness as a CO-side data-loading/indexing problem, not a Data Hub outage, because direct Data Hub timings were low while CO tab timings were high.
- Keep the first fix narrowly scoped to caching/indexing and product-scoped BOM loading rather than changing Data Hub contracts or redesigning the tab navigation.
- Use a short TTL for Data Hub BOM workspace caching so repeated tab clicks are fast without making long-lived stale BOM state likely during local workflow.
- Keep Data Hub endpoint usage centralized. No new raw `/v1/hub/*` literals were added outside `app/data_hub_client.py`.

## What Didn't Work
- Measuring only unauthenticated requests on the normal `8001` server showed fast `303` redirects and did not exercise the slow tab handlers.
- The temporary no-auth server was needed to measure the actual C/O pages without SSO friction.
- Direct Data Hub timings alone were misleading in the other direction: the APIs were fast enough, but CO multiplied the cost through repeated broad loading and local rule scans.

## Open Items
- `invoice-preview` exact lookup still does broad source-context work and measured around `2s` over HTTP in the local setup. The tab-load regression is fixed, but true remote search-as-you-type should use an approved Data Hub search endpoint request before CO adds a new contract.
- Origin HTML for the measured case is still large because it renders 130 material rows plus hidden form fields for the LVC statement. It is now under one second locally, but future cases with many finished products may need pagination or progressive rendering.
- Continue the existing legal PSR engine and allocation ledger work; this session only optimized the current preview/workflow layer.
