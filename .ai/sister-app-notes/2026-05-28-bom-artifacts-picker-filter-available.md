# BOM artifacts picker filter — available on `/v1/hub/products/{p}/bom/artifacts`

**To:** CO repo (`barry-CO-main`)
**From:** Data Hub
**Date:** 2026-05-28
**Request:** `barry-CO-main/.ai/api-requests/2026-05-28-bom-artifacts-active-flat-filter.md`

## Status

Shipped. Endpoint live on demo + dev after CI deploy.

## What's available

`GET /v1/hub/products/{product_code}/bom/artifacts` accepts these new
params on top of the existing `client_id`/`actor`/`intent`:

| Param | Values | Default |
|---|---|---|
| `intents` | comma-separated subset of `asserted_technical,staff_edit,derived,customs_declared,modified_for_case` | omit |
| `lifecycle` | `active` \| `all` | `all` |
| `shape` | `flat` \| `any` | `any` |
| `latest_per_variant` | `true` \| `false` | `false` |
| `case_id` | string | omit (required when `intents` includes `modified_for_case`) |

The full picker call CO requested:

```
GET /v1/hub/products/{p}/bom/artifacts
    ?client_id=<cid>
    &case_id=<case>
    &intents=asserted_technical,staff_edit,derived,customs_declared,modified_for_case
    &lifecycle=active
    &shape=flat
    &latest_per_variant=true
```

Response (back-compat shape + new echo block):

```json
{
  "items": [ /* unchanged per-artifact fields */ ],
  "total_estimate": 1,
  "filter_applied": {
    "lifecycle": "active", "shape": "flat",
    "intents": ["asserted_technical","staff_edit","derived","customs_declared","modified_for_case"],
    "latest_per_variant": true,
    "case_id": "co-case-…"
  }
}
```

## Defaults preserve back-compat

Per CO's "Recommended" path in the request, defaults are
`lifecycle=all, shape=any, latest_per_variant=false`. Existing
admin/debug callers that don't pass filter params see the raw
history unchanged. CO picker opts in to filtering by passing
explicit values.

## Behavior gate

CO's pre-staged adapter inspects `filter_applied` on first call.
Field present → use server-side filtering. Field absent → fall back
to the client-side filter in `bom_service.product_version_options_by_code`.

`filter_applied` is **always** present on the new shipment, so
detection flips on automatically after CO restart (or auto-reload
in dev).

## Modified_for_case scoping rules

- `intents` must include `modified_for_case` AND `case_id` must be
  supplied — otherwise 400 `case_id_required`.
- Within a multi-intent query, only `modified_for_case` rows are
  filtered by `case_id`. `staff_edit`, `derived`, etc. pass through
  unchanged.
- `modified_for_case` rows with missing `context.case_id` are
  excluded — case-scoped intent without a case is malformed, safer to
  hide.

## latest_per_variant partition rules

- Partition key: `(coalesce(bom_variant_id,'default'), flatten_strategy)`.
- Winner: newest `published_at` (then `artifact_no DESC`, then
  `artifact_id DESC` for full determinism).
- Tombstoned + draft rows excluded BEFORE partitioning when
  `lifecycle=active` (so the partition's winner is the newest
  non-tombstoned published row).
- Dual-source case (different strategies, same variant) ⇒ both
  partitions return their winner. Picker shows both for operator
  selection (which is exactly what `/bom/latest` couldn't do —
  that endpoint 409s instead).

## Auth

Unchanged. `hub:read` scope; user JWT or service token with
`client_ids` whitelist for the requested `client_id`. `case_id` is
not authorized server-side beyond client scoping — CO is the case
authority and only asks for cases the operator can see.

## Errors

- `400 invalid_lifecycle` — value not in `{active, all}`.
- `400 invalid_shape` — value not in `{flat, any}`.
- `400 invalid_intents` — any token not in the allowed set.
- `400 invalid_boolean` — `latest_per_variant` not `true`/`false`.
- `400 case_id_required` — `intents` includes `modified_for_case`
  without `case_id`.
- `400 conflicting_intent_params` — both `intent` (singular) and
  `intents` (plural) supplied and they disagree (intent not in
  intents set).
- Existing `401` / `403` / `404` unchanged.

## Open follow-ups

- The filter logic is Python-side over the raw history fetched by
  `list_artifacts_for_product`. For products with <50 artifacts
  (typical) this is fast. If a hot product ever has thousands of
  artifacts, surface it and we'll push the predicate into SQL.
- `latest_per_variant=true` does not paginate well — it picks the
  winner across the full filtered set before any cursor logic. If
  CO ever needs pagination on the picker (it shouldn't — <50 rows),
  the contract needs a small extension.
