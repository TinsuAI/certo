# Data Hub API Request: `/bom/artifacts` active+flat filter for picker

## Use Case
CO's per-TP BOM picker (`co_case.html:956`, populated by
`bom_service.product_version_options_by_code`) is the operator's
selection surface for which BOM artifact will drive origin
calculations on a sheet. Operators must only ever be able to pick
artifacts that are:

1. **Currently active** — `status='published'` and not tombstoned (not
   replaced by a newer version, not soft-deleted).
2. **Flat** — calculation-ready: `flatten_status IN
   ('flattened','not_applicable')`. Raw multi-level
   (`technical_raw`, `technical_non_flattened`) hidden entirely.
3. **In scope for the case** — `modified_for_case` proposals scoped to
   *this* case visible (operator may re-pick a draft they just
   submitted); proposals scoped to other cases hidden.

Today the picker leaks tombstoned, draft, superseded, foreign-case
`modified_for_case`, and `technical_non_flattened` rows (audit:
`.ai/audits/2026-05-28-bom-picker-filter-audit.md`). The operator can
silently pick a stale or wrong-case BOM, which then drives the
calculation engine. This is a correctness issue, not cosmetics.

CO also wants to surface richer per-artifact metadata in the picker
(source kind, strategy, variant id, freshness state, published_at) so
operators can disambiguate between multiple active artifacts. All
fields are already in the `/artifacts` response payload — no schema
addition needed for display.

## Existing Endpoint Gap

- `GET /v1/hub/products/{product_code}/bom/artifacts?client_id=X`
  returns the **raw history** for `(client_id, product_code)` (see
  `stores/bom.py:list_artifacts_for_product`, ~line 581). Optional
  `actor` / `intent` filters exist but no `status`, `tombstoned_at`,
  `shape`, or per-variant deduplication.
- `GET /v1/hub/products/{product_code}/bom/latest` already computes
  the correct "active flat" set via `latest_flattened_versions`
  (`stores/bom.py:1554`) with predicate:

  ```sql
  WHERE tombstoned_at IS NULL
    AND status = 'published'
    AND intent IN ('asserted_technical','staff_edit','derived','customs_declared')
    AND flatten_status IN ('flattened','not_applicable')
  ```

  Partitioned by `(bom_variant_id, flatten_strategy)`, newest
  `published_at` wins. But `/latest` returns at most one row per
  partition and **409s on dual-source variants** (multiple legs alive).
  The picker needs to **show all winners** for operator selection, not
  collapse to one.
- No existing endpoint accepts a `case_id` scope for `modified_for_case`
  artifacts, so CO has no way to ask "show me drafts I made for case
  X but hide drafts for case Y".

## Proposed Contract

Method and path:
`GET /v1/hub/products/{product_code}/bom/artifacts`

Query parameters (existing + new):

| Param                  | Type / values                                                                  | Default                                                       | Behavior                                                                                                                          |
|------------------------|--------------------------------------------------------------------------------|---------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------|
| `client_id`            | string                                                                         | required (existing)                                           | Scope.                                                                                                                            |
| `actor`                | string (existing)                                                              | omit                                                          | Existing filter, unchanged.                                                                                                       |
| `intent`               | string (existing, single value)                                                | omit                                                          | Existing filter — kept for back-compat. New `intents` plural takes precedence when provided.                                      |
| `intents`              | comma-separated subset of `asserted_technical,staff_edit,derived,customs_declared,modified_for_case` | `asserted_technical,staff_edit,derived,customs_declared`      | When `modified_for_case` is included, `case_id` MUST be supplied (otherwise 400).                                                 |
| `lifecycle`            | enum: `active`, `all`                                                          | `active`                                                      | `active` ⇒ `status='published' AND tombstoned_at IS NULL`. `all` ⇒ no filter (current default behavior, opt-in for admin tools). |
| `shape`                | enum: `flat`, `any`                                                            | `flat`                                                        | `flat` ⇒ `flatten_status IN ('flattened','not_applicable')`. `any` ⇒ no filter.                                                  |
| `latest_per_variant`   | boolean                                                                        | `true`                                                        | When `true`, partition by `(bom_variant_id, flatten_strategy)` and keep newest `published_at` per partition.                     |
| `case_id`              | string                                                                         | omit                                                          | Required when `intents` includes `modified_for_case`. Restricts `modified_for_case` rows to those whose `context.case_id == case_id`. Other intents not filtered by `case_id`. |
| `cursor`, `limit`      | existing pagination                                                            | existing                                                      | Pagination over the filtered set.                                                                                                 |

Defaults are deliberately set to the **picker's desired behavior** so
the picker call is `GET /v1/hub/products/{p}/bom/artifacts?client_id=X&case_id=Y&intents=asserted_technical,staff_edit,derived,customs_declared,modified_for_case`.
Admin / debug tools opt out with `lifecycle=all&shape=any&latest_per_variant=false`.

Request body: none.

Response body (back-compat: same shape, with metadata):

```json
{
  "items": [
    {
      "artifact_id": "ba_01HX...",
      "artifact_no": 7,
      "product_code": "MAS1230-39",
      "client_id": "johnson-vn",
      "status": "published",
      "tombstoned_at": null,
      "actor": "agency_staff",
      "intent": "staff_edit",
      "source_bom_kind": "manual_flat",
      "source_channel": "dh_ui",
      "flatten_status": "not_applicable",
      "flatten_strategy": "manual_flat_as_provided",
      "bom_variant_id": "default",
      "bom_code": "MAS1230-39",
      "lineage_root_id": "ba_01HW...",
      "parent_artifact_id": "ba_01HW...",
      "row_count": 42,
      "is_stale": false,
      "stale_reasons": [],
      "state": "clean",
      "human_label": "v7 · manual_flat · clean",
      "display_label": "v7",
      "context": {
        "case_id": null,
        "...": "existing context fields"
      },
      "published_at": "2026-05-24T03:11:00Z",
      "created_at": "2026-05-24T03:09:55Z"
    }
  ],
  "next_cursor": null,
  "filter_applied": {
    "lifecycle": "active",
    "shape": "flat",
    "intents": ["asserted_technical","staff_edit","derived","customs_declared","modified_for_case"],
    "latest_per_variant": true,
    "case_id": "co-case-4e9f5a3b1e9c"
  }
}
```

Notes on the shape:
- Existing per-artifact fields unchanged. CO already consumes
  `artifact_no, status, tombstoned_at, source_bom_kind, flatten_status,
  flatten_strategy, bom_variant_id, row_count, published_at,
  is_stale, stale_reasons, state, human_label, display_label,
  context`. No new fields requested.
- `filter_applied` is a new echo block so CO can detect server-side
  support. If absent in the response, CO falls back to client-side
  filtering and logs once that DH hasn't shipped the filter yet.
- `items` may contain multiple rows per `bom_variant_id` (the
  dual-source case) when `latest_per_variant=true` — different
  `flatten_strategy` per leg makes them distinct partitions.

Error cases:
- `400 invalid_lifecycle` — value not in `active|all`.
- `400 invalid_shape` — value not in `flat|any`.
- `400 invalid_intents` — any token not in the allowed set.
- `400 case_id_required` — `intents` includes `modified_for_case` and
  `case_id` omitted.
- `400 conflicting_intent_params` — both `intent` (singular) and
  `intents` (plural) supplied and they disagree.
- Existing 401 / 403 / 404 unchanged.

## Auth
Required scope:
`hub:read` (same as existing `/bom/artifacts`).

Client scoping rule:
Service-token `client_ids` whitelist must include `client_id`. User
JWT must carry a claim allowing `client_id`. `case_id` is not
authorized server-side beyond client scoping — CO is the case
authority and only asks for cases the operator is allowed to see.

Token type:
User JWT or service token (matches current `/bom/artifacts`).

## Data Semantics

Source of truth:
`bom_artifacts` table — fields already present per migrations
`006_bom.sql`, `021_bom_flatten_and_uom.sql`,
`066_bom_artifacts_regulatory_actor_intent.sql`, `068_bom_artifacts_state.sql`.

Precision requirements:
`published_at` is the partition tiebreaker. Ties (same `published_at`
within a partition) — break by `artifact_no DESC` then `artifact_id
DESC` so the result is deterministic across calls.

Pagination:
`cursor` / `limit` over the filtered set. Cursor encodes the post-filter
ordering (newest `published_at` first, then `artifact_no DESC`). One
page should be sized to hold all artifacts for a typical product
(< 50 in practice); pagination is defensive.

Idempotency:
Read-only. Same `(client_id, product_code, all filter params)` returns
the same set across calls modulo new artifact creation.

Versioning or pinning:
Adding params with backward-compatible defaults (`lifecycle=active,
shape=flat, latest_per_variant=true`) is a **breaking default change**
for existing `/bom/artifacts` callers that expected raw history.

Two ways to handle:
- **Recommended**: keep existing default as `lifecycle=all,
  shape=any, latest_per_variant=false` (current behavior). Picker
  passes filters explicitly. Existing CO admin / debug call sites
  unchanged.
- Alternative: change defaults to filtered; existing callers that
  need raw history pass `lifecycle=all&shape=any&latest_per_variant=false`.
  Requires audit of all current consumers (CO + any DH-internal use).

CO prefers the recommended path — opt-in to filter, defaults
unchanged. Less coordination risk.

## Tests Required In Data Hub

Provider tests:
- Default params (no filter) — response shape identical to current
  contract; `filter_applied` reflects `lifecycle=all, shape=any,
  latest_per_variant=false`.
- `lifecycle=active` — excludes `status='draft'`, `status='superseded'`,
  and `tombstoned_at IS NOT NULL` rows.
- `shape=flat` — excludes `flatten_status='non_flattened'` rows.
- `intents=staff_edit` — only `intent='staff_edit'` returned.
- `intents=asserted_technical,staff_edit,derived,customs_declared,modified_for_case`
  with `case_id` — `modified_for_case` rows only for matching
  `context.case_id`; other intents not filtered by `case_id`.
- `intents=modified_for_case` without `case_id` → 400.
- `latest_per_variant=true` — for a product with 3 published
  artifacts (`v5`, `v6`, `v7`) of the same `(variant_id, strategy)`,
  only `v7` is returned. For a product with two different
  `flatten_strategy` (dual-source), both winners returned.
- `latest_per_variant=true` tiebreaker — two artifacts with identical
  `published_at` → newer `artifact_no` wins, deterministically.
- Combination: `lifecycle=active&shape=flat&intents=...&latest_per_variant=true`
  matches the exact set computed by `latest_flattened_versions` for
  the `latest` endpoint (modulo the dual-source 409 collapse).
- `filter_applied` block present and reflects supplied params on
  every response.

Negative tests:
- `lifecycle=foo` → 400 `invalid_lifecycle`.
- `shape=foo` → 400 `invalid_shape`.
- `intents=bogus_intent` → 400 `invalid_intents`.
- `intent=staff_edit&intents=derived` (conflicting) → 400
  `conflicting_intent_params`.
- Token without scope → 403.
- Wrong `client_id` for token → 403.

Edge cases:
- Product with zero artifacts → `items: []`, `next_cursor: null`,
  `filter_applied` populated.
- Product with only `technical_non_flattened` artifacts + default
  `shape=flat` → `items: []` (operator sees empty picker — CO must
  surface "no flat BOMs available" UI, separate concern).
- Product with one `customs_declared` and one `staff_edit` of the
  same `(variant_id, strategy)` — `latest_per_variant=true` returns
  the newer one (per the `latest_flattened_versions` rule), even if
  it's `customs_declared`. CO operators have confirmed this is
  desired (pickable, no special treatment).
- `modified_for_case` row with `context.case_id` missing → excluded
  (case-scoped intent without a case is malformed; safer to hide).
- Tombstoned artifact whose `published_at` is the newest in its
  partition → `lifecycle=active` excludes it; the next-newest
  non-tombstoned artifact in the partition wins the
  `latest_per_variant` partition.

## CO Consumer Plan

Adapter method to add (extend existing) in `app/data_hub_client.py`:

```python
def list_bom_artifacts(
    self,
    product_code: str,
    *,
    client_id: str,
    actor: str = "",
    intent: str = "",
    intents: Sequence[str] = (),
    lifecycle: str = "active",
    shape: str = "flat",
    latest_per_variant: bool = True,
    case_id: str = "",
    **query,
) -> dict:
    """Returns the raw envelope {items, next_cursor, filter_applied}.

    Default values match the picker's desired filter. Admin/debug
    callers pass lifecycle='all', shape='any',
    latest_per_variant=False to recover legacy behavior.
    """
    params = {
        "client_id": client_id,
        "lifecycle": lifecycle,
        "shape": shape,
        "latest_per_variant": "true" if latest_per_variant else "false",
        **query,
    }
    if actor:
        params["actor"] = actor
    if intent:
        params["intent"] = intent
    if intents:
        params["intents"] = ",".join(intents)
    if case_id:
        params["case_id"] = case_id
    return self._get_all_envelope(
        f"/v1/hub/products/{product_code}/bom/artifacts",
        params,
    )
```

Behavior gate: on first call, CO inspects `filter_applied` in the
response. If absent → mark `bom_artifacts_filter_supported = False` in
a process-local cache and fall back to the existing CO-side filter in
`bom_service.product_version_options_by_code` (extended to mirror
this contract). When DH ships, CO auto-upgrades — no redeploy.

Call sites that will consume the adapter:
- `app/bom_service.py:DataHubBomService._build_workspace` — pass
  `client_id` + the case's `case_id` so `modified_for_case` proposals
  for *this* case are visible. Currently the workspace builder
  doesn't know the case_id; needs a small refactor to thread it
  through from the caller (`product_version_options_by_code` is
  called from case routes, where `case_id` is available).
- `app/bom_service.py:product_artifact_payloads` — uses the same
  filtered list as the picker so single-artifact products and
  multi-artifact products take the same path.
- Admin / debug call sites (if any — to be audited; grep
  `list_bom_artifacts`) — pass explicit `lifecycle='all',
  shape='any', latest_per_variant=False` to preserve current
  behavior.

Consumer tests:
- Adapter constructs query params correctly with/without each filter.
- Envelope passthrough preserves all DH fields including the new
  `filter_applied` block.
- Picker workspace: with DH filter on, `product_version_options_by_code`
  trusts the response and skips CO-side filtering (logs
  `dh_filter_active=true`).
- Picker workspace: when `filter_applied` missing (fallback path), CO
  applies the same predicate locally; result set identical to a
  filter-on response.
- Picker workspace: `modified_for_case` from case X visible on case X
  page, hidden on case Y page.
- Picker workspace: tombstoned artifact never reaches the picker
  options.
- Picker workspace: dual-source variants — both legs render as
  separate selectable options with distinct `bom_variant_id` and
  `flatten_strategy` badges.

UI display additions (separate ticket — landed once contract is
live):
- Picker option label: `#{artifact_no} · {published_at|short_date} ·
  {row_count} dòng`
- Badges: source kind (`manual-flat` / `technical-flat` / `co-edit`
  / `staff-edit` / `customs-filed`), variant tag (when not
  `default`), state badge (when not `clean` — yellow/orange/red with
  `stale_reasons` tooltip)
- Tooltip / details: `human_label` from DH

## Approval
Data Hub contract owner:
TBD — needs sign-off before CO lands the new picker behavior. CO
will pre-stage the consumer with graceful fallback to client-side
filtering so the moment DH ships, the picker tightens automatically.

Approval date:

Data Hub commit:
