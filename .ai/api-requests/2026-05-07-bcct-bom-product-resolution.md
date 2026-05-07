# Data Hub API Request: BCCT BOM Product Resolution

## Use Case
CO builds an origin workbook from export BCCT rows and BOM artifacts. For each exported finished product line, CO must know which Data Hub BOM product code to fetch before it can calculate material consumption, LVC/RVC, stock allocation, and sheet-level lock status.

Observed Growatt example:

```json
{
  "customs_code": "BIENTAN.17",
  "internal_code": "BIENTAN.17",
  "goods_name": "BIENTAN.17#&Thiết bị biến tần model MIN 4200TL-X2(Pro.E), dùng để chuyển đổi dòng điện dùng cho hệ thống điện mặt trời. Hàng mới 100% (PV01.0117500)#&VN"
}
```

The BOM artifacts are indexed by `PV01.0117500`, not by `BIENTAN.17`. In the current Data Hub payload, `PV01.0117500` is only embedded in `goods_name`; it is not exposed as a structured field. CO temporarily tried `code-mappings`, but that is not semantically safe because mappings can be many-to-many and do not prove which BOM product belongs to a specific export declaration line.

CO needs Data Hub to resolve or surface BOM product identity per BCCT export row. CO should not implement customer-specific parsing of goods descriptions.

## Existing Endpoint Gap
Checked endpoints:

- `GET /v1/hub/bcct?client_id=growatt-vn`
- `GET /v1/hub/bcct/invoice-matches?client_id=growatt-vn&invoice_no=...&declaration_types=E42&include_market_hint=true`
- `GET /v1/hub/code-mappings?client_id=growatt-vn`
- `GET /v1/hub/products?client_id=growatt-vn`
- `GET /v1/hub/products/{product_code}/bom/artifacts?client_id=growatt-vn`

Current gap:

- BCCT rows expose `customs_code` and `internal_code`, but for Growatt export rows both currently equal the customs/display code such as `BIENTAN.17`.
- The BOM product code, for example `PV01.0117500`, exists only inside `goods_name`.
- `code-mappings` can contain multiple internal codes for one customs code and multiple customs contexts for one internal code. It is useful evidence, not a line-level resolution contract.
- `/products` may not return every BOM product in the first page that CO needs for a case. CO can fetch BOM artifacts directly when it has a product code, but it first needs the correct product code.
- CO has no structured way to distinguish `resolved`, `ambiguous`, and `missing` BOM product identity for a BCCT export line.

## Proposed Contract
Method and path:

- Additive fields on `GET /v1/hub/bcct`
- Additive fields on `GET /v1/hub/bcct/invoice-matches`

Query parameters:

- Existing parameters remain unchanged.
- `include_product_identity`: optional boolean. Default `true` for `invoice-matches` because CO origin calculation consumes that endpoint directly. For `bcct`, Data Hub may default to `false` for broad list views, but must support `include_product_identity=true` for CO case flows that match by export declaration number instead of invoice number.
- `product_identity_candidate_limit`: optional integer, default `5`, max `20`.

Request body:

None.

Response body:

Add an item-level `product_identity` object to export rows and invoice-match rows. Existing fields must remain stable.

```json
{
  "items": [
    {
      "declaration_no": "307591379560",
      "line_no": "3",
      "declaration_type": "E42",
      "item_code": "BIENTAN.17",
      "customs_code": "BIENTAN.17",
      "internal_code": "BIENTAN.17",
      "description": "BIENTAN.17#&Thiết bị biến tần model MIN 4200TL-X2(Pro.E), dùng để chuyển đổi dòng điện dùng cho hệ thống điện mặt trời. Hàng mới 100% (PV01.0117500)#&VN",
      "product_identity": {
        "resolution_status": "resolved",
        "bom_product_code": "PV01.0117500",
        "selected_candidate_code": "PV01.0117500",
        "display_code": "BIENTAN.17",
        "declared_customs_code": "BIENTAN.17",
        "declared_internal_code": "BIENTAN.17",
        "line_key": {
          "client_id": "growatt-vn",
          "declaration_no": "307591379560",
          "line_no": "3",
          "transaction_key": "307591379560-3"
        },
        "resolution_source": "goods_name_embedded_code",
        "confidence": "high",
        "review_status": "system_resolved",
        "parser_adapter": "growatt_bcct",
        "parser_version": "2026-05-07",
        "evidence": {
          "source_field": "goods_name",
          "source_text": "BIENTAN.17#&Thiết bị biến tần model MIN 4200TL-X2(Pro.E), dùng để chuyển đổi dòng điện dùng cho hệ thống điện mặt trời. Hàng mới 100% (PV01.0117500)#&VN",
          "matched_text": "PV01.0117500",
          "match_rule": "parenthesized_product_code_exists_in_bom_products"
        },
        "candidates": [
          {
            "product_code": "PV01.0117500",
            "source": "goods_name_embedded_code",
            "confidence": "high",
            "reason": "Parsed from goods_name and matching BOM artifacts exist.",
            "bom_artifact_count": 3,
            "latest_flatten_status": "flattened",
            "latest_row_count": 274
          }
        ]
      }
    }
  ],
  "next_cursor": null,
  "total_estimate": 1
}
```

Allowed `resolution_status` values:

- `resolved`: exactly one high-confidence BOM product code is selected for this BCCT line. `bom_product_code` must be non-empty.
- `ambiguous`: multiple plausible candidates exist. `bom_product_code` must be empty/null; CO must require operator selection before calculation.
- `missing`: no plausible BOM product code can be found. `bom_product_code` must be empty/null.
- `unverified`: Data Hub found one or more candidates but not enough evidence for automatic calculation. `bom_product_code` must be empty/null; the best candidate may appear in `selected_candidate_code` only for UI preselection.

Allowed `resolution_source` values:

- `structured_field`: Data Hub has a trusted structured source field for BOM product code.
- `goods_name_embedded_code`: parser extracted a code from BCCT goods description.
- `reviewed_line_mapping`: a reviewed Data Hub line-level resolution exists.
- `code_mapping_candidate`: code mappings produced candidates but did not independently resolve the line.
- `manual_override`: a reviewed Data Hub operator override selected the product.
- `none`: no evidence found.

Allowed `review_status` values:

- `system_resolved`: resolver selected a candidate from deterministic or high-confidence evidence.
- `needs_review`: resolver found candidates but requires human confirmation.
- `reviewed`: Data Hub operator or approved import process confirmed the line-level identity.
- `rejected`: a previous candidate was explicitly rejected.

Error cases:

- Existing endpoint errors remain unchanged.
- `400 invalid_product_identity_candidate_limit` when the limit is not an integer or exceeds max.
- `404 unknown_client` when `client_id` is not a known DNCX/client.
- `422 invalid_declaration_types` when declaration type filter is malformed.
- `401/403` according to Data Hub auth rules.

This request does not require a new mutating endpoint. If Data Hub later wants CO/user selections to feed back into Data Hub, define a separate proposal endpoint with explicit mutating scope such as `hub:propose:product_identity`.

## Auth
Required scope:

- Read-only access: `hub:read`.

Client scoping rule:

- Returned rows and product identity candidates must be limited to the requested `client_id`.
- Candidate validation must only consider BOM artifacts/products visible to that same client.
- User JWTs must only access clients allowed by their Data Hub ACL.
- Service tokens must include read permission for the requested client or all clients by existing Data Hub policy.

Token type:

- User JWT or service token accepted by Data Hub read API policy.
- No mutating scope is needed for this contract.

## Data Semantics
Source of truth:

- Data Hub owns BCCT normalization, customer-specific parser adapters, product/BOM identity resolution, and candidate ranking.
- CO owns case workflow only: it consumes `product_identity.bom_product_code` when resolved, or asks the operator to choose when Data Hub returns `ambiguous`, `missing`, or `unverified`.
- `code-mappings` must be treated as candidate evidence only unless Data Hub has a reviewed line-level mapping. A many-to-many mapping table must not automatically resolve a BCCT line by itself.

Implementation guidance:

- Implement product identity resolution as a Data Hub normalization/resolver layer, not inside endpoint handlers.
- Persist or materialize the latest resolver output with BCCT/invoice-match indexes when practical; avoid scanning all product/BOM artifacts on every CO request.
- Use a stable line key such as `(client_id, declaration_no, line_no, transaction_key)` for reviewed line mappings and audit trails.
- Resolver stages should be ordered: trusted structured field, client parser adapter, reviewed line mapping, candidate ranking from weaker evidence, then missing.
- Customer-specific parsing belongs in Data Hub parser adapters. For example, Growatt may parse parenthesized product-like codes in `goods_name`; another client may use a structured source field or no parser at all.
- API response code should only serialize the resolver result; it should not contain Growatt-specific parsing logic.

Resolution rules:

- Prefer a trusted structured field if Data Hub has one.
- For Growatt, parse likely product codes embedded in `goods_name` and validate them against Data Hub BOM product/artifact indexes.
- A parsed embedded code should only become `resolved` when it is unique, belongs to the requested client, and has at least one usable BOM artifact or an explicit reviewed product record.
- If multiple embedded/product/mapping candidates remain plausible, return `ambiguous` with ranked candidates and do not set `bom_product_code`.
- If the candidate exists but has no usable BOM artifact, return `unverified` or `missing` with the candidate evidence; CO will show a BOM missing state.

Precision requirements:

- Preserve raw code text exactly in evidence.
- Preserve `source_text` enough for audit; Data Hub may truncate only if it also provides `source_text_hash`.
- Code matching should be case-sensitive unless Data Hub has a client-specific normalization rule.
- Candidate confidence must be one of `high`, `medium`, `low`.

Pagination:

- Preserve current `items` envelope and cursor pagination behavior.
- Candidate lists are bounded by `product_identity_candidate_limit`.
- Stable row ordering remains declaration date, declaration number, numeric line number when possible, transaction key.

Idempotency:

- Read-only endpoint. Same query against unchanged BCCT/product/BOM data and same parser version must return the same product identity result.
- If parser rules change, expose `parser_version` so CO snapshots can show which resolver produced the result.

Versioning or pinning:

- Additive fields do not require an endpoint version bump.
- Include `parser_adapter` and `parser_version` in `product_identity`.
- If Data Hub tracks BCCT artifact/source version IDs, include optional `bcct_artifact_id` or `source_version_id` per row in a follow-up contract. Not required for this request.

## Tests Required In Data Hub
Provider tests:

- Growatt BCCT export row with `goods_name` containing `(PV01.0117500)` returns `product_identity.resolution_status == "resolved"` and `bom_product_code == "PV01.0117500"`.
- The same product identity appears on `invoice-matches` rows after invoice filtering.
- Candidate validation checks same-client BOM artifacts/products, not global products.
- Existing consumers still receive all currently documented BCCT and invoice-match fields unchanged.
- `include_product_identity=false` omits `product_identity` entirely so broad list views keep the current lightweight response shape.
- Non-`resolved` statuses return `bom_product_code` empty/null even when candidates exist.

Negative tests:

- A customs/display code such as `BIENTAN.17` with only many-to-many `code-mappings` and no goods-name embedded code returns `ambiguous` or `unverified`, not `resolved`.
- A parsed embedded code with no same-client BOM artifact returns `unverified` or `missing`, not `resolved`.
- Rows for another client are never used as candidate evidence.
- Unknown `client_id` returns `404`.
- Invalid `product_identity_candidate_limit` returns `400`.

Edge cases:

- Goods description contains multiple parenthesized codes.
- Goods description contains a model number and a product code; parser must not confuse model with BOM product code.
- Goods description contains no embedded code.
- Multiple BOM variants/artifacts exist for the resolved product code.
- BOM product exists but only non-flattened artifacts are available.
- One invoice contains multiple export lines with different resolved BOM product codes.
- One customs/display code maps to several internal codes in `code-mappings`.

## CO Consumer Plan
Adapter method to add in `app/data_hub_client.py`:

- Extend `DataHubClient.invoice_matches()` and `DataHubClient.list_bcct()` normalization to preserve `product_identity`.
- Add a small adapter helper, for example `bom_product_code_from_product_identity(row)`, after approval.

Call sites that will consume the adapter:

- `DataHubPortfolioService.co_case_source_context()` to pass product identity through invoice matches.
- `co_case_bom_product_codes()` to request BOM workspaces by `row.product_identity.bom_product_code` when `resolution_status == "resolved"`.
- `prepare_case_origin_products()` to bind each origin sheet to the resolved BOM product code.
- `app/templates/co_case.html` to show `ambiguous`, `missing`, or `unverified` states and allow a case-level manual BOM TP selection.

Consumer tests:

- Data Hub mode uses `product_identity.bom_product_code` for `BIENTAN.17 -> PV01.0117500` and loads BOM rows without parsing `goods_name` in CO.
- Rows with `ambiguous` identity do not auto-calculate; CO shows the BOM picker and blocks export until the sheet is calculated with an explicit selection.
- Rows with `missing` identity show a BOM missing state rather than falling back to `code-mappings`.
- Existing local/non-Data-Hub mode remains unchanged.
- Raw `/v1/hub/*` literals remain confined to `app/data_hub_client.py`.

Migration note:

- Remove CO's temporary `code-mappings`-based BOM resolution once this contract is approved and Data Hub provider tests pass.
- CO may keep case-local manual BOM TP overrides for workflow needs, but those overrides must not become global Data Hub truth without a separate approved mutating proposal contract.

## Approval
Data Hub contract owner:

Pending.

Approval date:

Pending.

Data Hub commit:

Pending.
