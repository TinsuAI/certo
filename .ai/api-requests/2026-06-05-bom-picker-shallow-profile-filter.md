# Data Hub API Request: `/bom/artifacts` exclude shallow-flatten from picker (`depth=full`)

Follow-up to `2026-05-28-bom-artifacts-active-flat-filter.md`. That request shipped
`shape=flat` (keep `flatten_status IN ('flattened','not_applicable')`). In production
this is **not enough**: a *shallow* flatten is still `flatten_status='flattened'`, so it
leaks into the picker. We need a depth dimension.

## Use Case
CO's per-TP BOM picker (`co_case.html`, populated by
`bom_service.product_version_options_by_code`) must only offer **fully-resolved flat**
BOMs — the leaf-level material list that drives origin/LVC and the bảng kê. Today the
picker also shows **shallow** flattens, which stop at purchased sub-assemblies (BTP) and
do NOT explode them to raw materials.

Real example, johnson-vn product `VGM0121-05`, two published flat artifacts:

| Artifact | rows | flatten_status | context.profile | flatten_strategy |
|---|---|---|---|---|
| #2 | **2** | flattened | **shallow** | **purchased_btp_as_leaf** |
| #5 | **223** | flattened | technical_exploded | technical_exploded |

Artifact #2's two rows are `1000535232` and `VGM0121-P0` — where `VGM0121-P0` is an
in-house BTP that should be exploded, not treated as a leaf. If an operator picks #2, the
bảng kê has 2 NVL instead of 223 → a structurally wrong C/O. Both artifacts pass
`shape=flat` because both are `flatten_status='flattened'`. The picker can't tell them
apart on the existing filter dimensions.

This is a correctness footgun, not cosmetics: the shallow artifact is a valid pick today.

## Existing Endpoint Gap
- `GET /v1/hub/products/{product_code}/bom/artifacts?...&shape=flat` (the
  `2026-05-28-...active-flat-filter` contract) filters on `flatten_status` only.
  `flatten_status` answers "is the shape a flat list?" — **true for both shallow and
  fully-exploded**. It does not encode flatten *depth*.
- The depth IS already represented per-artifact, via `flatten_strategy` and
  `context.profile`:
  - shallow ⇒ `flatten_strategy='purchased_btp_as_leaf'` / `context.profile='shallow'`
  - full ⇒ `flatten_strategy='technical_exploded'` (exploded) or
    `flatten_strategy='manual_flat_as_provided'` (manual/customs-filed flat, already
    leaf-complete)
- But there's no query param to filter on depth, and `shape=flat` semantics are already
  shipped and must not change meaning (breaking).

## Proposed Contract
Method and path: `GET /v1/hub/products/{product_code}/bom/artifacts` (extend existing).

Query parameters (add one):

| Param | Type / values | Default | Behavior |
|---|---|---|---|
| `depth` | enum: `full`, `any` | `any` | `any` ⇒ no change (back-compat). `full` ⇒ exclude shallow artifacts: those whose `flatten_strategy = 'purchased_btp_as_leaf'` (equivalently `context.profile = 'shallow'`). Manual/asserted/customs-declared flats are **never** treated as shallow (they are leaf-complete by construction). |

The picker call becomes:
`GET /v1/hub/products/{p}/bom/artifacts?client_id=X&case_id=Y&lifecycle=active&shape=flat&depth=full&intents=...`

Admin/debug keeps `depth=any` (default) to see everything.

Request body: none.

Response body: unchanged item schema. Add the applied value to the echo block:
```json
"filter_applied": {
  "lifecycle": "active",
  "shape": "flat",
  "depth": "full",
  "intents": ["asserted_technical","staff_edit","derived","customs_declared","modified_for_case"],
  "latest_per_variant": true,
  "case_id": "co-case-e015fad11e4a"
}
```

Per-artifact metadata: no new field strictly required (CO can read
`flatten_strategy`/`context.profile`). **Nice-to-have:** add a flat boolean
`is_shallow: true|false` (server-computed) so CO doesn't have to encode the
strategy→depth mapping in two places. If added, CO will display a "BOM nông — chưa nổ
hết NVL" warning on any shallow option that slips through (e.g. when only a shallow flat
exists for a product).

Error cases:
- `400 invalid_depth` — value not in `full|any`.
- Existing 400/401/403/404 unchanged.

## Auth
Required scope: `hub:read` (same as existing `/bom/artifacts`).
Client scoping rule: unchanged — service-token `client_ids` whitelist / user JWT claim must allow `client_id`.
Token type: user JWT or service token (unchanged).

## Data Semantics
Source of truth: `bom_artifacts` table — `flatten_strategy` (and `context.profile`) already
populated by the materializer (`materialize_shallow_and_full_flat.py` writes both a shallow
and a full artifact per product).
Precision requirements: none new — boolean/enum classification only.
Pagination: `cursor`/`limit` over the post-`depth`-filter set (unchanged mechanics).
Idempotency: read-only; same params → same set.
Versioning or pinning: `depth` defaults to `any` ⇒ **no behavior change** for existing
callers. CO opts in with `depth=full`. Non-breaking.

Decision to confirm with DH: is `purchased_btp_as_leaf` the ONLY shallow strategy, or are
there other partial-explosion strategies that should also be classed shallow? CO assumes
exactly `purchased_btp_as_leaf` ⇒ shallow; everything else ⇒ full. Please confirm or give
the authoritative depth classification, since DH owns flatten semantics.

## Tests Required In Data Hub
Provider tests:
- `depth=full` excludes artifacts with `flatten_strategy='purchased_btp_as_leaf'`; keeps
  `technical_exploded`, `manual_flat_as_provided`, `not_applicable`.
- `depth=any` (and omitted) → identical to current `shape=flat` behavior (shallow still returned).
- Product with ONLY a shallow flat + `depth=full` → `items: []` (CO surfaces "no full flat
  BOM available" — separate UI concern; the operator must not be handed a 2-row stub).
- `depth=full` composes with `lifecycle=active`, `shape=flat`, `intents`,
  `latest_per_variant`, `case_id` — result = the full-depth subset of the already-filtered set.
- `filter_applied.depth` echoes the applied value on every response.
- (if `is_shallow` added) `is_shallow=true` iff `flatten_strategy='purchased_btp_as_leaf'`.

Negative tests:
- `depth=foo` → 400 `invalid_depth`.
- Token without scope / wrong client_id → 403 (unchanged).

Edge cases:
- A product with a shallow `purchased_btp_as_leaf` AND a full `technical_exploded` of the
  same `(bom_variant_id)`: `depth=full` returns only the full one. With
  `latest_per_variant=true`, partitioning is by `(bom_variant_id, flatten_strategy)`, so
  shallow and full are different partitions — `depth=full` removes the shallow partition
  entirely rather than letting it win a partition.
- Manual/customs-declared flat (`manual_flat_as_provided`, intent `customs_declared`, the
  Mẫu-16 BOMs) must NEVER be classed shallow — they are the preferred picks.

## CO Consumer Plan
Adapter method in `app/data_hub_client.py`: extend `list_bom_artifacts_filtered` /
`list_bom_artifacts_batch` to pass `depth` (default `"full"` for the picker path).
Call sites:
- `app/bom_service.py:product_version_options_by_code` — when DH echoes
  `filter_applied.depth`, trust it; else apply the CO-side fallback below.
- `_picker_predicate_keeps` — add the mirror predicate:
  `if str((version.get("context") or {}).get("profile") or "") == "shallow": return False`
  (equivalently `flatten_strategy == 'purchased_btp_as_leaf'`). This is the interim
  hot-patch CO can ship immediately, before DH lands `depth`, since the fields are already
  in the response.
Consumer tests:
- Shallow `purchased_btp_as_leaf` artifact never appears in
  `product_version_options_by_code` output (fallback path).
- When DH `filter_applied.depth='full'` present, CO trusts server and skips local filter.
- A product with only a shallow flat → picker shows empty + the "BOM nông" notice.

## Approval
Data Hub contract owner: TBD — needs sign-off. CO will pre-stage the client-side mirror
predicate (graceful fallback) so the picker tightens immediately and auto-upgrades when DH
ships `depth`.
Approval date:
Data Hub commit:
