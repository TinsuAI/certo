# Data Hub API Request: batch BOM artifacts (multi-product, rows inline)

## Use Case

CO builds the origin-tab BOM workspace
(`bom_service.DataHubBomService._build_workspace`) by fetching, **per
product in the case**, the active+flat BOM artifacts and their flattened
rows. A product-heavy case (johnson-vn has up to 50 products) therefore
fans out into ~150 sequential Data Hub round-trips:

- 1× `list_bom_artifacts_filtered(product_code)` per product (the picker
  filter contract, `.ai/api-requests/2026-05-28-bom-artifacts-active-flat-filter.md`)
- N× `get_bom_artifact(product_code, artifact_id)` per returned summary to
  pull the rows (or 1× `get_bom_latest(product_code)` on the single-artifact
  fallback, which already embeds rows).

**Measured cost (prod, in-container `co-app-1`, johnson-vn, 50 products):**
sequential build ~**10.4s**; the per-product `product_artifact_payloads`
alone is ~10.6s. CO now fetches products concurrently
(`BOM_FETCH_MAX_WORKERS`, currently 4) which helps in the common case
(~3–6s) but is capped low and **regresses / read-times-out under load**
because prod Data Hub runs a single uvicorn worker behind the public proxy
hostname — concurrent CO requests just queue on one backend worker. See
STATUS.md (2026-05-31 BOM workspace perf) for the full benchmark.

A single batch round-trip removes the fan-out entirely and is robust
regardless of Data Hub worker count: one request, one response, the BOM
workspace assembles client-side from it.

## Existing Endpoint Gap

All BOM read endpoints are keyed on a single `{product_code}` path
segment — there is **no** multi-product variant:

- `GET /v1/hub/products/{product_code}/bom/artifacts` (+ picker filters from
  the 2026-05-28 request) — one product per call; returns summaries
  **without rows** (rows require a follow-up `get_bom_artifact`).
- `GET /v1/hub/products/{product_code}/bom/artifacts/{artifact_id}` — one
  artifact's rows per call.
- `GET /v1/hub/products/{product_code}/bom/latest` — one product per call;
  embeds rows but collapses dual-source variants to one and **409s** when
  multiple legs are alive (`DataHubBomVariantConflict`).

CO cannot ask "give me the active+flat artifacts, with rows, for these N
product_codes, in one response."

## Proposed Contract

Method and path:
`POST /v1/hub/products/bom/artifacts:batch`

POST (not GET) because the product-code list is large (50+) and would breach
URL length / proxy limits as a query param. The body carries the list; all
filters mirror the per-product `/bom/artifacts` picker contract so behavior
is identical, just fanned in.

Query parameters: none (all inputs in the body).

Request body:

```json
{
  "client_id": "johnson-vn",
  "product_codes": ["PV00.0048500", "PV01.0117600", "..."],
  "intents": ["asserted_technical", "staff_edit", "derived", "customs_declared", "modified_for_case"],
  "lifecycle": "active",
  "shape": "flat",
  "latest_per_variant": true,
  "case_id": "co-case-0605189d5eea",
  "include_rows": true,
  "cursor": null,
  "limit": 200
}
```

- `client_id` — required. Single client per request (matches the client
  scoping rule; no cross-client batching).
- `product_codes` — required, non-empty, deduplicated server-side. A hard
  cap (e.g. `<= 500`) → `400 too_many_product_codes` above it; CO chunks.
- `intents` / `lifecycle` / `shape` / `latest_per_variant` / `case_id` —
  **identical semantics and defaults** to the per-product picker contract
  (`active` / `flat` / `latest_per_variant=true`, `case_id` required when
  `intents` includes `modified_for_case`). The filter is applied
  independently per product.
- `include_rows` — boolean, default `true`. When `true`, each artifact item
  embeds its flattened `rows` (the same payload `get_bom_artifact` returns),
  so CO needs no per-artifact follow-up. `false` → summaries only (parity
  with the list endpoint) for callers that only need version metadata.

Response body:

```json
{
  "results": {
    "PV00.0048500": {
      "items": [
        {
          "artifact_id": "ba_01HX...",
          "artifact_no": 7,
          "product_code": "PV00.0048500",
          "client_id": "johnson-vn",
          "status": "published",
          "tombstoned_at": null,
          "intent": "staff_edit",
          "source_bom_kind": "manual_flat",
          "flatten_status": "flattened",
          "flatten_strategy": "manual_flat_as_provided",
          "bom_variant_id": "default",
          "bom_code": "PV00.0048500",
          "row_count": 42,
          "published_at": "2026-05-24T03:11:00Z",
          "context": {"case_id": null},
          "rows": [
            {"material_code": "NVL-1", "qty_per_unit": "1", "uom": "PCS", "hs_code": "...", "payload": {"material_name": "..."}}
          ],
          "unresolved": [],
          "decisions": []
        }
      ],
      "filter_applied": {
        "lifecycle": "active",
        "shape": "flat",
        "intents": ["asserted_technical","staff_edit","derived","customs_declared","modified_for_case"],
        "latest_per_variant": true,
        "case_id": "co-case-0605189d5eea"
      }
    },
    "PV01.0117600": { "items": [ "..." ], "filter_applied": { "..." } }
  },
  "missing": ["PRODUCT-WITH-NO-ARTIFACTS"],
  "next_cursor": null
}
```

Notes on the shape:
- `results` is keyed by `product_code`; each value is exactly the
  per-product `{items, filter_applied}` envelope CO already consumes, so the
  client-side normalization (`normalize_hub_artifact` / `normalize_hub_row`)
  is unchanged.
- Each `items[*]` is the existing artifact summary **plus** `rows`,
  `unresolved`, `decisions` when `include_rows=true` — identical fields to
  `get_bom_artifact`'s payload. No new per-artifact fields requested.
- `missing` lists requested `product_codes` that resolved to zero artifacts
  after filtering (so CO can distinguish "no flat BOM" from "not requested").
  Alternatively these appear in `results` with `items: []`; CO accepts
  either, but `missing` is clearer.
- Dual-source variants are returned as **multiple items** under the product
  (same as the filtered list) — the endpoint never 409s. This replaces the
  per-product `/latest` 409 path; CO surfaces them as separate selectable
  versions.
- `filter_applied` echo per product lets CO detect server-side support and
  fall back to the per-product path if absent.

Error cases:
- `400 missing_client_id` — `client_id` absent.
- `400 empty_product_codes` — `product_codes` missing/empty.
- `400 too_many_product_codes` — list exceeds the server cap.
- `400 case_id_required` — `intents` includes `modified_for_case` and
  `case_id` omitted (same rule as the per-product contract).
- `400 invalid_lifecycle` / `invalid_shape` / `invalid_intents` — same
  validation as the per-product contract.
- `401` / `403` — unchanged (token / client-scope failures).
- Unknown `product_codes` do **not** 404 the whole request — they land in
  `missing`. A 404 is reserved for an unroutable path.

## Auth

Required scope:
`hub:read` (same as the existing `/bom/artifacts`). Read-only — no mutate
scope.

Client scoping rule:
Single `client_id` per request; the service-token `client_ids` whitelist (or
user-JWT claim) must include it, else `403`. `case_id` is not authorized
server-side beyond client scoping — CO is the case authority. No
cross-client batching (one client per call) keeps scoping trivial.

Token type:
User JWT or service token (matches the current `/bom/artifacts`).

## Data Semantics

Source of truth:
`bom_artifacts` + the flattened-rows store — the same tables behind
`/bom/artifacts` and `get_bom_artifact`. The batch endpoint is a fan-in over
the existing per-product query, not a new data path; results MUST be
identical to calling the per-product endpoint for each `product_code`.

Precision requirements:
Same partition tiebreaker as the per-product contract: within a
`(bom_variant_id, flatten_strategy)` partition, newest `published_at` wins;
ties broken by `artifact_no DESC` then `artifact_id DESC` for determinism.
Row order within an artifact must match `get_bom_artifact` (CO re-sorts
globally, but stable per-artifact order keeps parity checks clean).

Pagination:
`cursor` / `limit` over a deterministic flattening of
`(product_code ASC, published_at DESC, artifact_no DESC)`. A page boundary
must not split a single product's items across pages unless that product
alone exceeds `limit` — prefer to over-fill slightly and keep each product's
`items` whole, so CO can assemble per product without merging across pages.
For johnson-scale (50 products, < ~5k rows total) one page suffices;
pagination is defensive against a pathological client.

Idempotency:
Read-only. Same `(client_id, sorted product_codes, filter params)` returns
the same set across calls modulo new artifact creation.

Versioning or pinning:
New endpoint, no back-compat concern. Filter defaults match the picker
contract. If the per-product picker contract changes, this endpoint MUST
track it (shared filter implementation).

## Tests Required In Data Hub

Provider tests:
- Two products, each with one active+flat artifact → `results` has both
  keys, each `items` length 1, `rows` embedded, `filter_applied` echoed.
- `include_rows=false` → items present, `rows` absent/empty; no
  per-artifact row fetch performed.
- Per-product equivalence: for each `product_code` in the batch, `items`
  equals exactly what `GET /v1/hub/products/{product_code}/bom/artifacts`
  with the same filters returns (plus rows) — golden parity against the
  per-product endpoint.
- `latest_per_variant=true` with a dual-source product → both legs returned
  as separate items; **no 409**.
- `modified_for_case` intent + `case_id` → case-scoped drafts only for the
  matching case; other-case drafts hidden; non-case intents unfiltered by
  case.
- Product with zero matching artifacts → appears in `missing` (and/or
  `results` with `items: []`), not a 404.
- Pagination: `limit` smaller than total → `next_cursor` returned, no
  product's `items` split across the boundary; concatenating pages
  reproduces the full unpaginated set.

Negative tests:
- Empty `product_codes` → `400 empty_product_codes`.
- `product_codes` over cap → `400 too_many_product_codes`.
- `intents=modified_for_case` without `case_id` → `400 case_id_required`.
- `intents=bogus` → `400 invalid_intents`; bad `lifecycle`/`shape` → 400.
- Token without `hub:read` → 403; `client_id` outside token scope → 403.

Edge cases:
- Duplicate `product_codes` in the request → deduplicated; each key appears
  once in `results`.
- Mix of multi-artifact, single-artifact, dual-source, and
  zero-artifact products in one call → each handled per its per-product
  semantics independently.
- A product whose only artifacts are `technical_non_flattened` under default
  `shape=flat` → `items: []` / `missing` (operator-facing "no flat BOM" is a
  separate CO concern).
- Large fan-in (500 products) → single response within latency budget;
  confirms the endpoint is genuinely fan-in (one query/round-trip class), not
  an internal per-product loop that re-introduces the cost server-side.

## CO Consumer Plan

Adapter method to add in `app/data_hub_client.py`:

```python
def list_bom_artifacts_batch(
    self,
    client_id: str,
    product_codes: Sequence[str],
    *,
    intents: Sequence[str] = (),
    lifecycle: str = "active",
    shape: str = "flat",
    latest_per_variant: bool = True,
    case_id: str = "",
    include_rows: bool = True,
) -> dict:
    """POST /v1/hub/products/bom/artifacts:batch.

    Returns {results: {product_code: {items, filter_applied}}, missing,
    next_cursor}. Follows next_cursor internally and merges pages so the
    caller sees one complete results map. Filter defaults match the picker.
    """
    ...
```

(Pagination handling internal to the adapter, like the existing
`_get_all_envelope`. All raw `/v1/hub` HTTP stays inside
`app/data_hub_client.py` per the repo guardrail
`tests/test_data_hub_policy.py`.)

Call sites that will consume the adapter:
- `app/bom_service.py:DataHubBomService._build_workspace` — replace the
  per-product fan-out (`_fetch_product_results` →
  `product_artifact_payloads` + `get_bom_latest` per product) with **one**
  `list_bom_artifacts_batch(client_id, product_codes, case_id=...)` call,
  then run the existing per-product assembly
  (`_build_product_result`-equivalent) over `results[product_code]`
  in-process. The ThreadPoolExecutor fan-out becomes the **fallback** path
  used only when `filter_applied` is absent (DH hasn't shipped the batch
  endpoint) — graceful degradation, no redeploy needed when DH lands it.
- Variant-conflict surfacing: the batch path returns all active-flat
  winners as separate items, so it does not hit the per-product `/latest`
  409. CO keeps `DataHubBomVariantConflict` handling only on the legacy
  per-product fallback path.

Consumer tests:
- Adapter builds the POST body correctly (filters, `include_rows`,
  dedup) and merges paginated `results`.
- `_build_workspace` with the batch adapter produces a workspace
  **byte-identical** to the current per-product build on the same fixture
  (reuse the existing full-dict parity check;
  `tests/test_bom_workspace_parallel.py` is the parity harness).
- Fallback: when the stubbed DH lacks the batch endpoint (or omits
  `filter_applied`), `_build_workspace` falls back to the per-product
  parallel path and yields the same workspace.
- `missing` products contribute no product_versions and don't error.
- Dual-source product → both legs become separate selectable versions
  (no variant-conflict path on the batch route).

## Related Operational Findings (NOT contract changes — for the DH owner)

Surfaced by the same prod benchmark; independent of this endpoint but they
gate how much the parallel fallback can ever help:

1. **Prod Data Hub runs `--workers 1`** (single uvicorn worker on a 24-core
   host). Scaling out DH workers would speed up both the current per-product
   path and any future batch path, and make CO-side concurrency safe.
2. **CO → DH over the public hostname** `https://ttdatahub.tinsu.ai` (proxy
   + TLS per request). Routing CO → DH over the internal docker network
   would cut per-request overhead substantially.

These are deployment/config items for the Data Hub side, not part of this
API contract; noted here so they're not lost.

## Approval

Data Hub contract owner:
TBD — needs sign-off before CO lands the batch consumer. CO will pre-stage
the adapter with graceful fallback to the existing per-product parallel
fetch, so the batch path activates automatically once DH ships and echoes
`filter_applied`.

Approval date:

Data Hub commit:
