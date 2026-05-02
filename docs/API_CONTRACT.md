# Data Hub API Contract

Status: current implementation contract for sister-app consumers.

Consumers:
- `BCQT-System`: read-only consumer for settlement workflows.
- `barry-CO-main`: read consumer for source records, plus BOM proposal submission.

External consumers must call HTTP APIs only. They must not connect directly to the `hub` Postgres schema.

## Base URLs

Local dev default:

```text
http://127.0.0.1:8754
```

API roots:

```text
/v1/auth
/v1/hub
```

Legacy route:

```text
/api/v1/hub/products/{product_code}/bom/proposals
```

The legacy route is session-cookie based and exists for compatibility with older internal flows. New external consumers must use `/v1/hub/...`.

## Auth

All `/v1/hub/*` routes require `Authorization: Bearer <token>`.

Read routes currently support two modes:
- Default dev mode, `api_auth_strict=false`: valid Data Hub JWT is preferred; non-empty legacy bearer strings are still accepted for read-only routes.
- Strict mode, `api_auth_strict=true`: valid Data Hub JWT only.

Write route exception:
- `POST /v1/hub/products/{product_code}/bom/proposals` always requires a valid Data Hub JWT, even when `api_auth_strict=false`.

This keeps dev reads convenient while preventing accidental or malicious BOM writes with `Bearer anything`.

## Getting A Dev JWT

Password flow:

```http
POST /v1/auth/token
Content-Type: application/json

{
  "email": "<dev-user-email>",
  "password": "<dev-user-password>"
}
```

Use a local dev account created by the seed/setup flow. Do not hardcode shared credentials in consumer code or docs.

Response:

```json
{
  "access_token": "<jwt>",
  "token_type": "Bearer",
  "expires_in": 600
}
```

Browser SSO flow:
- `GET /v1/auth/authorize?redirect_uri=<absolute-callback-url>&state=<consumer-state>`
- Data Hub redirects unauthenticated users through `/login`.
- Data Hub redirects back with `code` and `state`.
- Consumer exchanges the code:

```http
POST /v1/auth/exchange
Content-Type: application/json

{
  "code": "<one-time-code>",
  "redirect_uri": "http://consumer.test/auth/callback"
}
```

JWKS:

```http
GET /v1/auth/jwks
```

Consumers should verify JWT signatures locally via JWKS. `/v1/auth/validate` exists for debug and one-shot validation, not hot-path request auth.

## Authorization Model

JWT claims include:

```json
{
  "iss": "http://localhost:8754",
  "sub": "u_...",
  "iat": 1760000000,
  "exp": 1760000600,
  "email": "operator@example.test",
  "role": "dev|admin|manager|staff",
  "name": "Operator",
  "all_clients": true,
  "client_ids": ["growatt-vn"]
}
```

`all_clients` and `client_ids` are convenience claims for consumer-side UI filtering. Data Hub still re-checks current DB ACL on `/v1/hub/*` requests.

Roles:
- `dev`, `admin`: all clients, can submit BOM proposals.
- `manager`: scoped to managed clients, can submit BOM proposals for those clients.
- `staff`: scoped to assigned clients; `scope=edit` is required to submit BOM proposals.
- `staff` with read-only access can read, but cannot propose BOM changes.

## Response Rules

List response:

```json
{
  "items": [],
  "total_estimate": 123,
  "next_cursor": "opaque-or-null"
}
```

Current pagination cursor is an offset string. Consumers must treat it as opaque.

Numeric precision:
- Current JSON serialization returns Postgres decimals as JSON numbers.
- Consumers that need exact money/quantity precision should preserve original source rows or request string-decimal support before depending on exact binary-float behavior.

Errors:
- Current routes return FastAPI JSON errors, usually `{"detail": "..."}`.
- Consumers should branch on HTTP status first, then inspect `detail`.

## Endpoint Catalog

### Auth

#### `POST /v1/auth/token`

Exchange Data Hub username/password for a short-lived JWT.

#### `GET /v1/auth/authorize`

Browser SSO start.

Query params:
- `redirect_uri`: required absolute `http(s)` URL. Origin must be allowlisted by `DATA_HUB_SSO_ALLOWED_REDIRECT_ORIGINS`; localhost origins are allowed by default when no allowlist is set.
- `state`: optional consumer state.

#### `POST /v1/auth/exchange`

Exchange one-time browser SSO code for JWT.

#### `GET /v1/auth/jwks`

Return public JWKS for local JWT verification.

#### `GET /v1/auth/validate`

Validate a bearer token and return basic claims.

### DNCX Directory

#### `GET /v1/hub/dncxs`

List DNCXs visible to caller.

Response item fields include:
- `id` / `client_id`
- `name`
- `tax_code`
- `code_resolution_mode`
- `bom_proposal_mode`
- `bom_proposal_qty_tolerance_pct`
- `status`

#### `GET /v1/hub/dncxs/{client_id}`

Fetch one DNCX. Caller must have view access.

### CO Consumer Config

#### `GET /v1/hub/dncxs/{client_id}/co-config`

Returns a CO-compatible config envelope.

Important semantics:
- `bcct.eligible_import_declaration_types` is currently empty because Data Hub does not yet store per-client CO declaration-type filters.
- `bcct.relevant_export_declaration_types` is currently empty for the same reason.
- `bcct.declaration_type_filter_status = "unconfigured"` means consumers must not interpret the empty arrays as a confirmed business rule.

Example:

```json
{
  "schema_version": 1,
  "client_id": "growatt-vn",
  "config_version": 1,
  "config_hash": "data-hub:growatt-vn:...",
  "source": "data-hub",
  "bcct": {
    "declaration_type_preset": "data_hub",
    "declaration_type_filter_status": "unconfigured",
    "eligible_import_declaration_types": [],
    "relevant_export_declaration_types": []
  },
  "co_stock": {
    "lot_policy": "line_level"
  },
  "allocation_code": {
    "strategy": "same_as_customs_code",
    "description_regex": "",
    "fallback": "same_as_customs_code",
    "data_hub_code_resolution_mode": "simple_mapping"
  }
}
```

### Source Summary

#### `GET /v1/hub/dncxs/{client_id}/source-summary`

Returns row-count summaries for Data Hub source records.

Important semantics:
- `co_stock_row_count` is currently raw import BCCT row count.
- `co_stock_row_count_semantics = "raw_import_rows_unfiltered"` means this is not yet a CO stock calculation after declaration-type filtering, allocation, or lot policy.
- Consumers should display it as raw source coverage, not as usable CO stock.

Example:

```json
{
  "client_config": { "...": "same shape as /co-config" },
  "material_catalog": {
    "module": "material_catalog",
    "published_row_count": 100,
    "latest_version": {},
    "version_count": 0,
    "upload_count": 0,
    "correction_candidate_count": 0
  },
  "product_catalog": {
    "module": "product_catalog",
    "published_row_count": 20
  },
  "bcct": {
    "module": "bcct",
    "published_row_count": 1000,
    "reviewed_row_count": 1000,
    "export_row_count": 300
  },
  "co_stock_row_count": 700,
  "co_stock_row_count_semantics": "raw_import_rows_unfiltered"
}
```

### Materials

#### `GET /v1/hub/materials`

List materials.

Query params:
- `client_id`: required.
- `category`: optional.
- `status`: optional.
- `cursor`: optional.
- `limit`: optional, default 200, max 1000.

Response item fields:
- `client_id`
- `customs_code`
- `internal_code`
- `name`
- `category`
- `category_override`
- `status`
- `unit`
- `hs_code`
- `updated_at`

#### `GET /v1/hub/materials/{customs_code}`

Fetch one material.

Query params:
- `client_id`: required.

### BCCT

#### `GET /v1/hub/bcct`

List BCCT rows.

Query params:
- `client_id`: required.
- `year`: optional.
- `direction`: optional, usually `import` or `export`.
- `declaration_no`: optional.
- `cursor`: optional.
- `limit`: optional, default 200, max 1000.

Response item fields include:
- `client_id`
- `year`
- `transaction_key`
- `line_no`
- `declaration_no`
- `declaration_type`
- `direction`
- `registration_date`
- `customs_code`
- `internal_code`
- `goods_name`
- `hs_code`
- `quantity`
- `unit`
- `total_value`
- `currency`
- `origin`
- `invoice_ref`
- `exporter_name`
- `exporter_tax_code`
- `consignee_name`
- `incoterms`
- `weight`
- `weight_unit`
- `package_count`
- `package_unit`
- `invoice_date`
- `departure_date`
- `destination_code`
- `destination_name`
- `transport_mode`
- `exchange_rate`
- `bom_version_id`
- `indexed_at`

#### `GET /v1/hub/bcct/invoice-matches`

Return export BCCT rows whose `invoice_ref` contains all tokens from `invoice_no`.

Query params:
- `client_id`: required.
- `invoice_no`: required.
- `declaration_types`: optional comma-separated list.

Matching rules:
- Invoice matching is token-based and case-insensitive.
- All tokens from `invoice_no` must appear in `invoice_ref`.
- Filtering happens in SQL before the 500-row cap.

#### `GET /v1/hub/bcct/{transaction_key}`

Fetch BCCT rows for a transaction key.

Query params:
- `client_id`: required.

If one row matches, response is the row object. If multiple lines share the transaction key, response is:

```json
{
  "transaction_key": "...",
  "lines": []
}
```

### Code Mappings

#### `GET /v1/hub/code-mappings`

List code mappings.

Query params:
- `client_id`: required.

Response item fields:
- `client_id`
- `internal_code`
- `customs_code`
- `category`
- `notes`

### Products And BOM

#### `GET /v1/hub/products`

List products with BOM metadata.

Query params:
- `client_id`: required.

#### `GET /v1/hub/products/{product_code}/bom/latest`

Fetch latest published BOM version for product.

Query params:
- `client_id`: required.

Current latest logic includes published versions with intent:
- `asserted_technical`
- `staff_edit`
- `derived`

It excludes `modified_for_case`.

#### `GET /v1/hub/products/{product_code}/bom/versions`

List BOM versions for a product.

Query params:
- `client_id`: required.
- `actor`: optional.
- `intent`: optional.

#### `GET /v1/hub/products/{product_code}/bom`

Fetch pinned or latest BOM.

Query params:
- `client_id`: required.
- `version_id`: optional. If absent, route returns latest.

### BOM Proposals

#### `POST /v1/hub/products/{product_code}/bom/proposals`

Submit a CO BOM change proposal. Requires valid JWT and edit access for the client.

Request:

```json
{
  "client_id": "growatt-vn",
  "actor": "co_system",
  "intent": "modified_for_case",
  "parent_version_id": "bv_...",
  "context": {
    "case_id": "CO-2026-0001",
    "trigger": "origin_review"
  },
  "rows": [
    {
      "material_code": "PE-001",
      "qty_per_unit": "0.46",
      "uom": "kg",
      "bom_code": null,
      "bom_variant_id": null
    }
  ]
}
```

Contract rules:
- `rows` is required and must be non-empty.
- `actor=co_system` or `intent=modified_for_case` requires `parent_version_id`.
- `parent_version_id` must belong to the same `(client_id, product_code)`.
- All `material_code` values must exist in active materials for the client.
- Quantity delta checks apply against the parent version.
- Idempotency key is `(client_id, product_code, actor, intent, parent_version_id, normalized_hash)`.

Approved response:

```json
{
  "proposal_id": "prop_...",
  "status": "approved",
  "version_id": "bv_...",
  "decision_reason": "auto-rule approved",
  "failed_conditions": []
}
```

Rejected response:

```json
{
  "proposal_id": "prop_...",
  "status": "rejected",
  "version_id": null,
  "decision_reason": "auto-rule rejected",
  "failed_conditions": ["parent_version_id_invalid"]
}
```

#### `GET /v1/hub/proposals/{proposal_id}`

Fetch a proposal record. Caller must have view access to the proposal's client.

### Health

#### `GET /v1/hub/healthz`

Returns:

```json
{ "status": "ok" }
```

## Consumer Rules

BCQT:
- Treat Data Hub as read-only source of shared HQ records.
- Use `/bcct`, `/materials`, and pinned BOM endpoints.
- Do not use CO-specific `co-config` fields for settlement rules.

CO:
- Read shared source data through Data Hub endpoints.
- Do not infer missing endpoint contracts from raw row payloads.
- Submit BOM changes only through `/bom/proposals`.
- Always include `parent_version_id` for `modified_for_case`.
- Treat `co-config` declaration type arrays as unconfigured until Data Hub exposes real per-client CO config.

## Change Management

Any new endpoint request from CO or BCQT must be proposed first as an API contract change. The request should specify:
- use case
- request JSON/query params
- response JSON
- auth and client scoping
- pagination
- precision requirements
- idempotency rules for writes
- Data Hub provider tests

Do not add ad-hoc `/v1/hub` calls in consumers before the provider contract and tests exist.
