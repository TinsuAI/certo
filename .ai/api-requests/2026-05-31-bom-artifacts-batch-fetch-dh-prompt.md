# DH-side implementation prompt — batch BOM artifacts

Hand this prompt to the Data Hub AI agent to implement the endpoint requested
in [`2026-05-31-bom-artifacts-batch-fetch.md`](2026-05-31-bom-artifacts-batch-fetch.md).
It is self-contained (does not require the CO repo). Per CO policy, DH must
agree the contract and ship provider tests before CO wires its consumer.

---

```
You are working in the Data Hub codebase. Implement a new batch read endpoint for BOM artifacts. This is a performance request from the CO (certificate-of-origin) service.

## Why
CO builds its origin BOM workspace by fetching artifacts per product. Each product costs TWO round-trips: list the active+flat artifacts, then fetch rows per artifact. A product-heavy client (johnson-vn, 50 products) fans out to ~150 sequential calls — measured ~10.4s in prod. A single batch call collapses this to one round-trip.

## What to build
Add: POST /v1/hub/products/bom/artifacts:batch

It is the multi-product, fan-in version of the existing per-product
GET /v1/hub/products/{product_code}/bom/artifacts (the active+flat picker-filter contract — lifecycle/shape/intents/latest_per_variant/case_id). Reuse the SAME filter implementation (the predicate behind `latest_flattened_versions` / the per-product artifacts filter in stores/bom.py). The batch result for each product MUST be byte-identical to calling the per-product endpoint for that product_code with the same filters — this is a fan-in, not a new data path.

Request body:
{
  "client_id": "johnson-vn",            // required, single client per request
  "product_codes": ["P1","P2", ...],    // required, non-empty, dedupe server-side, cap (e.g. 500)
  "intents": ["asserted_technical","staff_edit","derived","customs_declared","modified_for_case"],
  "lifecycle": "active",                 // active|all, default active
  "shape": "flat",                       // flat|any, default flat
  "latest_per_variant": true,            // default true
  "case_id": "co-case-...",              // required iff intents includes modified_for_case
  "include_rows": true,                  // default true -> embed flattened rows per artifact
  "cursor": null, "limit": 200
}

Response body:
{
  "results": {
    "P1": {
      "items": [
        {
          "artifact_id": "ba_01HX...",
          "artifact_no": 7,
          "product_code": "P1",
          "client_id": "johnson-vn",
          "status": "published",
          "tombstoned_at": null,
          "intent": "staff_edit",
          "source_bom_kind": "manual_flat",
          "source_channel": "dh_ui",
          "flatten_status": "flattened",
          "flatten_strategy": "manual_flat_as_provided",
          "bom_variant_id": "default",
          "bom_code": "P1",
          "row_count": 2,
          "published_at": "2026-05-24T03:11:00Z",
          "context": { "case_id": null },
          "rows": [
            {
              "material_code": "NVL-1",
              "bom_code": "P1",
              "bom_variant_id": "default",
              "qty_per_unit": "1.5",
              "uom": "PCS",
              "hs_code": "3920.62.90",
              "payload": {
                "material_name": "PET film",
                "description": "PET film 50um",
                "hs_code": "3920.62.90",
                "material_hs_code": "3920.62.90",
                "scrap_rate": "0.02"
              }
            }
          ],
          "unresolved": [],
          "decisions": []
        }
      ],
      "filter_applied": { "lifecycle":"active","shape":"flat","intents":[...],"latest_per_variant":true,"case_id":"..." }
    },
    "P2": { "items":[...], "filter_applied":{...} }
  },
  "missing": ["P3"],          // requested codes with zero artifacts after filtering
  "next_cursor": null
}

## Row schema (each items[*].rows[*])
This MUST be identical to what GET /v1/hub/products/{product_code}/bom/artifacts/{artifact_id} already returns in payload.rows — do not invent a new shape; reuse the existing serializer. The fields CO actually reads (so they must be present / correctly named):
  - material_code   : string (required)
  - qty_per_unit    : string|number  (CO also accepts legacy key `qty_per`; prefer qty_per_unit)
  - uom             : string
  - hs_code         : string         (CO falls back to payload.hs_code / payload.material_hs_code if top-level empty)
  - bom_code        : string         (optional; CO defaults to artifact bom_code/product_code)
  - bom_variant_id  : string         (optional; CO defaults to artifact bom_variant_id or "default")
  - payload         : object with:
        material_name      : string
        description        : string   (CO uses material_name, else description)
        hs_code            : string
        material_hs_code   : string
        scrap_rate         : string|number
Any extra fields you already emit are fine — CO passes them through. Numeric values may be strings; CO normalizes. Keep row order within an artifact stable (CO re-sorts globally).

## Rules
- `results` keyed by product_code; each value is exactly the per-product {items, filter_applied} envelope (so CO reuses its normalization unchanged).
- include_rows=true -> embed rows (+ unresolved, decisions) per the row schema above. include_rows=false -> summaries only, no rows.
- Dual-source variants: return ALL active-flat winners as separate items. NEVER 409 (unlike /bom/latest).
- Filter applied independently per product.
- Tiebreaker within a (bom_variant_id, flatten_strategy) partition: newest published_at, then artifact_no DESC, then artifact_id DESC (deterministic).
- Pagination over (product_code ASC, published_at DESC, artifact_no DESC); a page must NOT split a single product's items unless that product alone exceeds limit. Concatenating pages reproduces the full set.

## Auth
scope hub:read (read-only, no mutate scope). Service-token client_ids whitelist or user-JWT claim must include client_id, else 403. One client per request (no cross-client batching). case_id is NOT authorized server-side beyond client scoping — CO is the case authority.

## Errors
- 400 missing_client_id | empty_product_codes | too_many_product_codes | case_id_required (modified_for_case w/o case_id) | invalid_lifecycle | invalid_shape | invalid_intents
- 401 / 403 unchanged
- Unknown product_codes do NOT 404 the request — they go in `missing`.

## Provider tests (required)
- Two products each w/ one active+flat artifact -> both keys, rows embedded matching the row schema, filter_applied echoed.
- include_rows=false -> no rows, no per-artifact row fetch.
- PER-PRODUCT PARITY: for each code, items == GET /bom/artifacts with same filters (plus rows). Golden test.
- Row-shape parity: a batch item's rows == the same artifact's rows from GET .../bom/artifacts/{artifact_id}.
- latest_per_variant=true on a dual-source product -> both legs as separate items, NO 409.
- modified_for_case + case_id -> case-scoped drafts only for matching case; other intents unfiltered by case; modified_for_case w/o case_id -> 400.
- Zero-artifact product -> in `missing`, not 404.
- Pagination: limit < total -> next_cursor; no product split; pages concat == full set.
- Negative: empty/over-cap product_codes, bad lifecycle/shape/intents, token w/o hub:read -> 403, client_id outside scope -> 403.
- Dedupe duplicate product_codes.
- Large fan-in (500 products) within latency budget — verify it is genuinely fan-in (one query class), not an internal per-product loop that re-introduces the cost server-side.

## Constraints
- Read-only, idempotent. Same (client_id, sorted product_codes, filters) -> same set modulo new artifacts.
- Share the filter implementation with the per-product endpoint; if that contract changes, this must track it.
- If any part conflicts with Data Hub internals (e.g. you can't fan-in cheaply at the storage layer, or POST-with-body doesn't fit conventions — GET with repeated product_code params is acceptable), propose the adjustment instead of forcing this shape, and flag it back to CO before finalizing.

Do not start until the contract is agreed. After implementing, report the final endpoint shape and the provider-test results so CO can wire its consumer.
```
