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

### Client Config (master data)

#### `GET /v1/hub/dncxs/{client_id}/client-config`

Returns consumer-agnostic master config for a DNCX. **Replaces the deprecated `/co-config` endpoint.**

Owns only true agency master data:
- `eligible_import_declaration_types` — HQ declaration types this DNCX is registered to import (E11, E15, E31, ...).
- `relevant_export_declaration_types` — Export declaration types relevant for C/O and settlement (E42, E62, ...).
- `fiscal_year_start_month` — 1..12. Default 1 (calendar year). Some Japanese DNCX use 4.
- `preset_key` — Optional reference to `hub.client_type_presets` (`dncx`, `sxxk`, `gia_cong`, `manual`, or user-created). Snapshot only — preset edits do NOT cascade.
- `config_version` — Monotonic, bumped on each save. `0` means "not yet configured" (virtual default response).
- `config_hash` — sha256(canonical JSON)[:16]. Consumers should compare this on each fetch to invalidate caches.

CO-specific fields (`co_stock.lot_policy`, `allocation_code.*`) and BCQT-specific fields (Mẫu 15/15a column mappings) are NOT in this payload — those live in CO and BCQT respectively.

Example:

```json
{
  "schema_version": 1,
  "client_id": "growatt-vn",
  "preset_key": "dncx",
  "eligible_import_declaration_types": ["E11", "E15"],
  "relevant_export_declaration_types": ["E42"],
  "fiscal_year_start_month": 1,
  "config_version": 3,
  "config_hash": "601d43362456eee3"
}
```

#### `GET /v1/hub/dncxs/{client_id}/co-config` *(deprecated)*

**Deprecated 2026-05-02. Sunset 2026-05-16.** Use `/client-config` for master data; CO-runtime fields belong in CO local config.

Response carries:
- `Deprecation: true`
- `Sunset: Sat, 16 May 2026 00:00:00 GMT`
- `Link: </v1/hub/dncxs/{id}/client-config>; rel="successor-version"`

During grace window: master fields (`bcct.eligible_import_declaration_types`, `bcct.relevant_export_declaration_types`) are sourced from `hub.client_config`. CO-runtime placeholders (`co_stock.lot_policy`, `allocation_code.*`) keep returning legacy values for back-compat. After 2026-05-16 this endpoint returns 410 Gone.

### Source Summary

#### `GET /v1/hub/dncxs/{client_id}/source-summary`

Returns row-count summaries for Data Hub source records plus the master `client_config`.

Note: `co_stock_row_count` and `co_stock_row_count_semantics` were removed 2026-05-02. CO must compute its own stock from filtered BCCT reads (use `eligible_import_declaration_types` from `/client-config` to filter `/bcct?direction=import&...`).

Example:

```json
{
  "client_config": {
    "schema_version": 1,
    "client_id": "growatt-vn",
    "preset_key": "dncx",
    "eligible_import_declaration_types": ["E11", "E15"],
    "relevant_export_declaration_types": ["E42"],
    "fiscal_year_start_month": 1,
    "config_version": 3,
    "config_hash": "601d43362456eee3"
  },
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
  }
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
- `uom` — canonical unit of measure (post-mig-063, replaces `unit`)
- `unit` — **deprecated alias of `uom`**, grace window through **2026-05-25**, then removed. New consumers must read `uom`.
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
- `since`: optional ISO-8601 UTC timestamp. When provided, returns only rows whose `indexed_at > since`. Caller MUST supply an explicit timezone (timezone-naive strings return 400 `invalid_since`).
- `include_tombstones`: optional `true` / `false`, default `false`. When `true` (requires `since`), the response includes a `tombstones` array of `{transaction_key, removed_at, reason}` entries from `hub.bcct_row_history` where `action='delete' AND changed_at > since`. Returned in full on the first page only; subsequent pages have `tombstones=[]`.

Response always includes `server_time` (ISO-8601 UTC, current server time). Callers running incremental refresh should persist `server_time` from the previous response and pass it as the next call's `since` — that closes the gap from multiple rows sharing one `indexed_at` clock tick.

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
- `artifact_id`
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

#### `GET /v1/hub/clients/{client_id}/bcct/by-codes`

BCCT slice filtered by `customs_code IN (codes)`. Sister-app entry for CO's
substitute-stock derivation: avoids paginating the full client BCCT when only
~20 candidate codes' worth of rows are needed.

Query params:
- `codes`: required, comma-separated customs codes (max 100). Case-insensitive
  exact match against `customs_code`. Whitespace + duplicates trimmed.
- `direction`: optional, usually `import`.
- `include_material_identity`: optional, default `false`. Same semantics as
  `/v1/hub/bcct`.
- `material_identity_candidate_limit`: optional, integer 1-20 (default 5).
- `cursor`, `limit`: optional, same pagination contract as `/v1/hub/bcct`.

Row shape: identical to `/v1/hub/bcct`. Pagination shape: identical
(`items`, `next_cursor`, `total_estimate`).

Errors:
- `400 missing codes` — empty / whitespace-only `codes` param.
- `400 too many codes` — more than 100 codes in one request.
- `400 invalid_material_identity_candidate_limit` — same as `/v1/hub/bcct`.
- `404 Client not found` — unknown `client_id`.

Unknown codes → `200` with empty `items`, not `404`.

Contract spec: `barry-CO-main/.ai/api-requests/2026-05-13-bcct-by-codes-lookup.md`.

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

Latest logic — hardened 2026-05-03 with BOM flattening shipping:
- Includes intent ∈ {`asserted_technical`, `staff_edit`, `derived`}, excludes `modified_for_case`.
- Includes `flatten_status` ∈ {`flattened`, `not_applicable`}. **Excludes `non_flattened`** — calculation consumers must never silently consume a non-flattened BOM as if it were calculation-ready.
- When dual-source variants are published for the same product (e.g. both `purchased_btp_as_leaf` and `self_produced_btp_exploded` are live), responds **`409 Conflict`** with the variant list. Caller must rebind to a specific `artifact_id` via `GET /v1/hub/products/{product_code}/bom?artifact_id=…`.

`409` response shape:

```json
{
  "error": "dual_source_variants",
  "message": "Multiple flattened variants exist for this product; …",
  "variants": [
    {
      "artifact_id": "ba_…",
      "artifact_no": 4,
      "flatten_strategy": "purchased_btp_as_leaf",
      "source_bom_kind": "technical_flattened",
      "flatten_status": "flattened",
      "display_label": "TP-A · default · v4 · technical_flattened · flattened · purchased_btp_as_leaf",
      "bom_variant_id": "default",
      "bom_code": null
    },
    {
      "artifact_id": "ba_…",
      "flatten_strategy": "self_produced_btp_exploded",
      "...": "…"
    }
  ]
}
```

`200` response shape (extended with flatten metadata):

```json
{
  "artifact": {
    "artifact_id": "ba_…",
    "client_id": "growatt-vn",
    "product_code": "TP-A",
    "artifact_no": 3,
    "actor": "agency_staff",
    "intent": "asserted_technical",
    "source_bom_kind": "technical_flattened",
    "flatten_status": "flattened",
    "flatten_strategy": "technical_exploded",
    "source_channel": "agency_upload",
    "bom_code": null,
    "bom_variant_id": "default",
    "lineage": { "btp_versions_used": [{"material_code":"BTP-B","artifact_id":"ba_…"}] },
    "display_label": "TP-A · default · v3 · technical_flattened · flattened · technical_exploded",
    "flatten_method": "dh_flatten_v1",
    "flatten_method_version": "0.1.0",
    "...": "…"
  },
  "rows": [...],
  "unresolved": [],
  "decisions": [
    {"decision_id": "dec_…", "decision_type": "...", "chosen_action": "...",
     "evidence": {...}, "status": "confirmed", "confirmed_by": "u_…"}
  ]
}
```

`unresolved` carries `{node_path, material_code, reason, evidence}` rows for non_flattened versions (always empty when `flatten_status='flattened'`). `reason` is one of `uom_conversion_missing | uom_conversion_ambiguous | missing_child_bom | cycle_detected | ambiguous_dual_source | classification_unknown | canonical_uom_missing` — all stable English machine codes.

##### `state` field (mig 068, shipped 2026-05-27)

`artifact.state` is one of:

- `clean` — aligned with current catalog. Most artifacts.
- `needs_refresh` — a catalog dependency moved; Refresh re-derives.
- `needs_input` — staff decision required (factor missing, catalog uom missing, unconfirmed 1:1 default, raw_graph drift).
- `broken` — reserved; unrecoverable. Not yet emitted.

`state` is a stored generated column derived from `is_stale` +
`has_uom_drift` + the reasons JSONB. Sister apps SHOULD bind UI badges
to this field; the legacy `is_stale`/`has_uom_drift` booleans remain
for backward compatibility and are not deprecated.

Calculation consumers SHOULD treat `state="needs_input"` similarly to
`flatten_status="non_flattened"` — refuse silent consumption,
surface a warning. Such artifacts may carry rows with
`applied_uom_factor IS NULL` (raw uom unconverted).

#### `GET /v1/hub/products/{product_code}/bom/artifacts`

List BOM artifacts for a product. Operator picker uses this with filter params to surface only currently-pickable artifacts; admin / debug tools call with default params to get the raw history.

Query params (defaults preserve raw-history back-compat — opt in to filtering):

| Param | Values | Default | Notes |
|---|---|---|---|
| `client_id` | string | required | Scope. |
| `actor` | string | omit | Existing filter. |
| `intent` | single intent | omit | Existing filter (kept for back-compat). |
| `intents` | comma-separated subset of `asserted_technical,staff_edit,derived,customs_declared,modified_for_case` | omit | When `modified_for_case` is in the list, `case_id` MUST be supplied. |
| `lifecycle` | `active` \| `all` | `all` | `active` ⇒ `status='published' AND tombstoned_at IS NULL`. |
| `shape` | `flat` \| `any` | `any` | `flat` ⇒ `flatten_status IN ('flattened','not_applicable')`. |
| `latest_per_variant` | `true` \| `false` | `false` | Partition by `(bom_variant_id, flatten_strategy)`; keep newest `published_at` (then `artifact_no DESC`, then `artifact_id DESC`). |
| `case_id` | string | omit | Required when `intents` includes `modified_for_case`. Restricts `modified_for_case` rows to `context.case_id == case_id`; other intents pass through. |

Response always echoes `filter_applied` so consumers can detect server-side support; when absent (older deployment), fall back to client-side filtering.

```json
{
  "items": [
    { "artifact_id": "ba_…", "artifact_no": 7, "intent": "staff_edit",
      "status": "published", "tombstoned_at": null,
      "flatten_status": "not_applicable",
      "flatten_strategy": "manual_flat_as_provided",
      "bom_variant_id": "default", "row_count": 42,
      "is_stale": false, "stale_reasons": [], "state": "clean",
      "published_at": "2026-05-24T03:11:00Z",
      "context": { "case_id": null, "...": "..." } }
  ],
  "total_estimate": 1,
  "filter_applied": {
    "lifecycle": "active", "shape": "flat",
    "intents": ["asserted_technical","staff_edit","derived","customs_declared","modified_for_case"],
    "latest_per_variant": true,
    "case_id": "co-case-4e9f5a3b1e9c"
  }
}
```

Errors:
- `400 invalid_lifecycle` / `invalid_shape` / `invalid_intents` / `invalid_boolean` — bad enum or non-`true`/`false` for `latest_per_variant`.
- `400 case_id_required` — `intents` includes `modified_for_case` and `case_id` omitted.
- `400 conflicting_intent_params` — both `intent` (singular) and `intents` (plural) supplied with disagreeing values.
- Existing `401` / `403` / `404` unchanged.

`modified_for_case` rows with missing `context.case_id` are excluded — case-scoped intent without a case is malformed; safer to hide.

Contract spec: `barry-CO-main/.ai/api-requests/2026-05-28-bom-artifacts-active-flat-filter.md`.

#### `GET /v1/hub/products/{product_code}/bom`

Fetch pinned or latest BOM. Phase 3b adds resolver hints (preset / case / shape).

Query params:
- `client_id`: required.
- `artifact_id`: optional raw pin. Highest precedence. No resolver
  invoked; response omits `resolution_trail`.
- `preset_id`: optional. Resolves via `hub.bom_presets`. Tombstoned
  presets remain queryable (audit-reproduction); `resolution_trail`
  carries warnings.
- `case_id`: optional. Resolves to `bom_artifacts` row whose
  `context->>'case_id'` matches, scoped to (client, product).
- `shape`: optional. One of `raw_graph` / `shallow` / `full_flat`.
  Restricts the latest set to artifacts of that shape; tie-break on
  variant order.

Precedence (highest first): artifact_id > preset_id > case_id > shape > default.

Response (200): `{artifact, rows, edges, unresolved, decisions,
resolution_trail?, shape?}`. `resolution_trail` is a list of strings
explaining each pick step (D2). Absent when no resolver hint used.

Errors:
- 404 `preset_not_found` — preset_id does not exist.
- 404 `case_not_found` — no alive artifact for that case_id.
- 404 `no_artifact_for_shape` — no published artifact has that shape.
- 404 `no_alive_artifacts` — product has no published artifacts.
- 409 `preset_scope_mismatch` — preset belongs to a different (client, product).
- 409 `dual_source_variants` — multiple published variants exist; caller must pin.

### Presets

Phase 3b. A preset = `(artifact_id, sourcing_choices, name)` binding for
(client, product). CO/BCQT call BOM endpoints with `?preset_id=` instead
of pinning raw `artifact_id`.

#### `POST /v1/hub/presets`

Body: `{client_id, product_code, artifact_id, name, sourcing_choices?, notes?}`.
Returns 201 with the created row. ID prefix `bp_*`.

#### `GET /v1/hub/clients/{client_id}/products/{product_code}/presets`

List alive presets for the (client, product) pair. Tombstoned hidden.

#### `PATCH /v1/hub/presets/{preset_id}`

Partial update. Editable fields: `name`, `sourcing_choices`, `notes`.

#### `POST /v1/hub/presets/{preset_id}/tombstone`

Retract. Body: `{reason?}`. No DELETE per BOM-immutability principle.
Tombstoned presets remain reachable when called via `?preset_id=` (audit
reproduction); the response carries a warning in `resolution_trail`.

### BOM Proposals

#### `POST /v1/hub/products/{product_code}/bom/proposals`

Submit a CO BOM change proposal. Requires valid JWT and edit access for the client.

Request:

```json
{
  "client_id": "growatt-vn",
  "actor": "co_system",
  "intent": "modified_for_case",
  "parent_artifact_id": "ba_...",
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
- `actor=co_system` or `intent=modified_for_case` requires `parent_artifact_id`.
- `parent_artifact_id` must belong to the same `(client_id, product_code)`.
- All `material_code` values must exist in active materials for the client.
- Quantity delta checks apply against the parent version.
- Idempotency key is `(client_id, product_code, actor, intent, parent_artifact_id, normalized_hash)`.

Approved response:

```json
{
  "proposal_id": "prop_...",
  "status": "approved",
  "artifact_id": "ba_...",
  "decision_reason": "auto-rule approved",
  "failed_conditions": []
}
```

Rejected response:

```json
{
  "proposal_id": "prop_...",
  "status": "rejected",
  "artifact_id": null,
  "decision_reason": "auto-rule rejected",
  "failed_conditions": ["parent_artifact_id_invalid"]
}
```

#### `GET /v1/hub/proposals/{proposal_id}`

Fetch a proposal record. Caller must have view access to the proposal's client.

### Substitutes

#### `GET /v1/hub/clients/{client_id}/materials/{material_code}/substitutes`

Ranked substitute candidates for a material (Feature 4 hybrid: same-HS,
trigram, embedding, manual confirmations). Sister-app entry; cookie-auth
mirror at `/api/v1/clients/{c}/materials/{m}/substitutes` exists for the
in-app UI.

Query params:
- `min_score` (float, default `0.5`): drop pairs below this combined score.
- `include_rejected` (bool, default `false`).
- `limit` (int, default `20`, capped at `100`).

Response:

```json
{
  "client_id": "johnson-vn",
  "material_a_code": "MFW0502-39",
  "count": 15,
  "items": [
    {
      "material_b_code": "MFW0502-02",
      "name": "...",
      "category": "tp",
      "hs_code": "95069100",
      "sources": ["embedding", "trigram"],
      "raw_scores": {"embedding": 0.96, "trigram": 0.62},
      "combined_score": 0.97,
      "confirmed": false,
      "confirmed_at": null
    }
  ]
}
```

Service token requires `hub:read` scope. Whitelisted `client_ids`
honored normally.

### Declarations

#### `GET /v1/hub/clients/{client_id}/declarations`

Per-declaration summary with `file_count` from
`hub.customs_declaration_files`. Sister-app entry for CO's TKX/TKN
"có tờ khai / thiếu tờ khai" status. BCCT row presence alone does
not equate to declaration-file presence — this endpoint surfaces
both signals so consumers can answer the file-presence question
without scanning BCCT.

Identity is `(client_id, declaration_no, direction)`. The same
`declaration_no` can exist in both `import` and `export` and ships
as two distinct rows.

Query params:
- `direction`: optional, `import` or `export`.
- `declaration_nos`: optional, comma-separated declaration numbers
  (max 500). Exact-match — no normalization is applied; preserves
  Data Hub's canonical declaration_no string.
- `has_files`: optional, `yes` or `no`. Filters by whether
  `file_count > 0`.
- `cursor`, `limit`: optional pagination (default `limit=200`,
  capped at `500`). When `declaration_nos` is provided, the response
  is single-page with `next_cursor=null`.

Response:

```json
{
  "items": [
    {
      "declaration_no": "308449399330",
      "direction": "export",
      "bcct_line_count": 2,
      "file_count": 1,
      "earliest_bcct_date": "2026-04-21"
    }
  ],
  "next_cursor": null
}
```

Errors:
- `400 invalid_direction` — `direction` not in `{import, export}`.
- `400 invalid_has_files` — `has_files` not in `{yes, no}`.
- `400 too many declaration_nos` — more than 500 in a single request.
- `401 bearer token required` — missing or invalid bearer in strict
  mode.
- `403 forbidden` — service token without `hub:read` scope or
  outside the client whitelist.
- `404 Client not found` — unknown `client_id`.

Contract spec:
`barry-CO-main/.ai/api-requests/2026-05-15-declaration-file-status.md`.

#### `GET /v1/hub/clients/{client_id}/declarations/download.zip`

Bearer-auth mirror of the operator cookie route at
`/clients/{cid}/declarations/download.zip`. Returns the same ZIP bytes
for server-to-server callers (CO's dossier builder consolidating TKX
+ TKN into a single deliverable). The cookie route stays in place for
operator browser flow.

Query params:
- `direction`: required, `import` or `export`.
- `declaration_nos`: required, comma-separated declaration numbers
  (max 500). Exact-match against the canonical Data Hub
  `declaration_no` string.
- `filename`: optional preferred archive filename in
  `Content-Disposition`. When omitted, defaults to
  `declarations_{client_id}_{direction}.zip`. Sanitized: only
  alphanumerics + `._- ()[]` kept, max 120 chars, `.zip` suffix
  enforced.

Response:
- `200` — `Content-Type: application/zip`,
  `Content-Disposition: attachment; filename="..."`. Body is identical
  to the cookie route: files at archive root (deduped by `_1`/`_2`
  suffix on collision), `DANH_SACH_TO_KHAI.txt` manifest, and a
  `NO_FILES_FOUND.txt` marker when zero files matched.

Errors:
- `400 invalid_direction` — `direction` missing or not in
  `{import, export}`.
- `400 declaration_nos_required` — empty / missing.
- `400 too_many_declaration_nos` — more than 500.
- `401 bearer token required` — missing/invalid bearer in strict mode.
- `403 forbidden` — service token without `hub:read` scope or outside
  the client whitelist.
- `404 Client not found` — unknown `client_id`.

Contract spec:
`barry-CO-main/.ai/api-requests/2026-05-28-bcct-declarations-download-bearer.md`.

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
- Always include `parent_artifact_id` for `modified_for_case`.
- Treat `co-config` declaration type arrays as unconfigured until Data Hub exposes real per-client CO config.

BOM consumers (CO and BCQT) — flatten contract:
- Calculation flows MUST NOT consume versions where `flatten_status='non_flattened'`. The `/bom/latest` endpoint already filters these out; if you fetch a specific `artifact_id`, check the field yourself.
- When `/bom/latest` returns `409 dual_source_variants`, the consumer MUST pick a specific variant and rebind via `?artifact_id=…`. Picking a variant is a business decision that lives outside Data Hub — do not silently default to the first.
- Persist the picked `artifact_id` against the consuming entity (BCQT settlement record / CO case) so re-runs are reproducible.
- Never use `display_label` as a key — it is a denormalized cache. Compare on `(artifact_id)` or on the structured tuple `(product_code, bom_variant_id, flatten_strategy, artifact_no)`.

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
