# DH-side prompt — add `depth=full` filter to `/bom/artifacts` (exclude shallow flattens)

Hand this prompt to the Data Hub AI agent. It is self-contained (does not require the CO
repo). This is a small, backward-compatible **contract extension** to an already-shipped
endpoint: one new query param + one echo field + provider tests.

Companion CO request artifact (for the full rationale):
`.ai/api-requests/2026-06-05-bom-picker-shallow-profile-filter.md`.

---

```
You are working in the Data Hub codebase. Extend an existing BOM endpoint with a new,
backward-compatible filter requested by the CO (certificate-of-origin) service.

## Endpoint
GET /v1/hub/products/{product_code}/bom/artifacts
Existing picker-oriented query params (already shipped): client_id, lifecycle=active|all,
shape=flat|any, intents=<csv>, latest_per_variant=true|false, case_id, cursor, limit.
Response is an envelope: { items: [...], next_cursor, filter_applied: {...} }.

## Problem
`shape=flat` keeps artifacts with `flatten_status IN ('flattened','not_applicable')`.
But `flatten_status` only says "the shape is a flat list" — it does NOT encode how DEEP the
flatten went. A SHALLOW flatten (strategy `purchased_btp_as_leaf`) is still
`flatten_status='flattened'`, so it passes `shape=flat` and leaks into CO's BOM picker
alongside the fully-exploded version.

Concrete case (client johnson-vn, product VGM0121-05) — two published flat artifacts:
- artifact #2: 2 rows,   flatten_status=flattened, context.profile='shallow',
               flatten_strategy='purchased_btp_as_leaf'
               (its 2 rows are `1000535232` and `VGM0121-P0`, where VGM0121-P0 is an
                in-house BTP that should have been exploded, not kept as a leaf)
- artifact #5: 223 rows, flatten_status=flattened, context.profile='technical_exploded',
               flatten_strategy='technical_exploded'
Both pass shape=flat. An operator who picks #2 gets a 2-material BOM instead of 223 →
a structurally wrong certificate of origin. The picker has no way to exclude the shallow one.

## Fix: add a `depth` query param

Add one query parameter to GET /v1/hub/products/{product_code}/bom/artifacts:

  depth = full | any        (default: any)

- depth=any (default, and when omitted): NO behavior change. Shallow artifacts still returned.
  This keeps every existing caller working unchanged.
- depth=full: exclude SHALLOW artifacts — those whose flatten_strategy = 'purchased_btp_as_leaf'
  (equivalently context.profile = 'shallow'). Keep everything else:
  technical_exploded, manual_flat_as_provided, and flatten_status='not_applicable'.

Important classification rules:
- Manual / asserted / customs-declared flats (flatten_strategy='manual_flat_as_provided',
  including the customs-filed "Mẫu 16" BOMs with intent='customs_declared') are
  leaf-complete by construction and must NEVER be classed shallow.
- flatten_status='not_applicable' artifacts are not shallow.
- If `purchased_btp_as_leaf` is NOT the only partial-explosion strategy in your data,
  classify ALL partial-explosion strategies as shallow and document which ones. You own the
  flatten semantics — the authoritative shallow/full classification should live here.

`depth` composes with the existing lifecycle / shape / intents / latest_per_variant /
case_id filters (apply depth as an additional AND predicate over the already-filtered set).
Note for latest_per_variant: partitions are keyed by (bom_variant_id, flatten_strategy), so
shallow and full are SEPARATE partitions — depth=full must DROP the shallow partition
entirely, not let a shallow artifact "win" a partition.

## Response
- Item schema unchanged.
- Echo the applied value in the existing filter_applied block:
    "filter_applied": { ..., "depth": "full" }
- NICE-TO-HAVE (optional but preferred): add a server-computed boolean field to each item:
    "is_shallow": true|false      // true iff the artifact is a shallow/partial flatten
  so consumers don't have to re-encode the strategy→depth mapping. If you add it, also cover
  it in a provider test.

## Errors
- depth not in {full, any}  -> 400 invalid_depth
- All existing 400/401/403/404 unchanged.

## Auth
Unchanged: hub:read scope; service-token client_ids whitelist or user JWT claim must allow
client_id. Read-only.

## Provider tests to add
1. depth=full excludes flatten_strategy='purchased_btp_as_leaf'; keeps technical_exploded,
   manual_flat_as_provided, not_applicable.
2. depth=any and depth omitted -> identical to current shape=flat behavior (shallow returned).
3. Product with ONLY a shallow flat + depth=full -> items: [] (empty is correct; consumer
   surfaces "no full-flat BOM available").
4. depth=full composes with lifecycle=active & shape=flat & intents=... & latest_per_variant=true
   & case_id -> returns the full-depth subset of the already-filtered set.
5. latest_per_variant=true + depth=full on a product that has both a shallow and a full
   artifact of the same bom_variant_id -> only the full artifact is returned.
6. filter_applied.depth echoes the supplied value on every response.
7. depth=foo -> 400 invalid_depth.
8. (if is_shallow added) is_shallow=true iff flatten_strategy='purchased_btp_as_leaf'.

## Deliverable
Backward-compatible: with depth defaulting to `any`, no existing caller changes behavior.
CO will pass depth=full from its picker. Reply with the merged Data Hub commit hash and the
final shallow/full classification you adopted (confirm whether purchased_btp_as_leaf is the
only shallow strategy).
```
