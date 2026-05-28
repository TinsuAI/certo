# BOM picker filter audit — 2026-05-28

Scope: tighten the per-TP BOM artifact dropdown (`co_case.html` line 956) so operators only see currently-active *flat* BOMs from Data Hub, with enough version metadata to disambiguate.

Read scope:
- CO: `app/data_hub_client.py`, `app/bom_service.py`, `app/main.py` (BOM-related calls), `app/templates/co_case.html`
- DH: `app/routes/api.py` (`/v1/hub/products/{p}/bom*`), `app/stores/bom.py` (`list_artifacts_for_product`, `latest_flattened_versions`), `app/flatten/types.py`, `db/migrations/006_bom.sql`, `021_bom_flatten_and_uom.sql`, `066_bom_artifacts_regulatory_actor_intent.sql`, `068_bom_artifacts_state.sql`
- Prior CO→DH requests under `.ai/api-requests/` — none related to BOM listing/filtering. Existing BOM contracts predate this audit.

---

## 1. Current BOM query contract (CO ↔ DH)

CO calls three DH endpoints via `DataHubClient`:

| Method                  | Endpoint                                                | Returns                                                                                       |
|-------------------------|---------------------------------------------------------|-----------------------------------------------------------------------------------------------|
| `list_bom_artifacts`    | `GET /v1/hub/products/{product_code}/bom/artifacts`     | Full list of artifacts for `(client_id, product_code)`. Optional `actor` / `intent` filters. |
| `get_bom_latest`        | `GET /v1/hub/products/{product_code}/bom/latest`        | Latest flattened (or `not_applicable`) artifact. 409 on dual-source variants.                |
| `get_bom_artifact`      | `GET /v1/hub/products/{product_code}/bom?artifact_id=…` | One artifact by id.                                                                          |

The picker is fed by `list_bom_artifacts` only when multiple artifacts exist (`bom_service.product_artifact_payloads`, lines 182–213); single-artifact products fall back to `/bom/latest`.

DH `/artifacts` returns no server-side filtering for status/tombstone/intent beyond what `list_artifacts_for_product` selects — it returns **all** non-deleted rows for `(client_id, product_code)` (`stores/bom.py:581`), including tombstoned, draft, superseded, and non-flattened ones. Filtering is left to the caller.

Response fields per artifact (`stores/bom.py:586-594`):
`artifact_id, artifact_no, actor, intent, parent_artifact_id, row_count, normalized_hash, status, tombstoned_at, created_at, published_at, context, bom_variant_id, source_bom_kind, source_channel, flatten_status, flatten_strategy, is_stale, stale_reasons, has_uom_drift, state, human_label, display_label`, plus `bom_shape` derived field.

## 2. Current usage in CO (the picker)

- `bom_service.DataHubBomService._build_workspace` calls `product_artifact_payloads` per TP; the picker dropdown is populated from `bom_workspace.product_version_options_by_code` (`co_case.html:950`).
- `product_version_options_by_code` (`bom_service.py:382`) excludes only `variant_conflict` rows and `flatten_status == "non_flattened"`. **Nothing else is filtered out.** Tombstoned/superseded/draft/dual-source-leg artifacts can appear.
- Each option shows literally only `#{artifact_no} · {row_count} dòng · {status}` (`co_case.html:958`). `status` here is CO's derived label — `"current"` or `"non_flattened"` (`bom_service.py:287`) — not DH's `status` (`draft|published|superseded`).
- Selection persists as `bom_product_artifact_overrides` on the case (`main.py:286-294`).

## 3. BOM type enumeration (DH `source_bom_kind`, `flatten/types.py:15-18`)

| `source_bom_kind`           | Meaning                                                                                   |
|-----------------------------|-------------------------------------------------------------------------------------------|
| `manual_flat`               | Agency provided already-flat BOM (no walker; rows are leaves).                            |
| `technical_raw`             | Raw multi-level BOM as imported; not calculation-ready. Stored as edges, no flat rows.    |
| `technical_flattened`       | Engine-derived flat version of a `technical_raw`.                                         |
| `technical_non_flattened`   | Walker ran but produced a non-flat result (mixed/unresolved); not calculation-ready.      |
| `co_modified`               | CO-system proposed delta; derived from a parent artifact for a specific case.             |
| `staff_edit`                | Staff edited a flat BOM in DH UI.                                                         |

Orthogonal flags:
- `flatten_status ∈ {flattened, non_flattened, not_applicable}` — `not_applicable` is the resting state for `manual_flat`.
- `flatten_strategy ∈ {manual_flat_as_provided, technical_exploded, purchased_btp_as_leaf, self_produced_btp_exploded, mixed_confirmed, no_strategy}`.
- `actor ∈ {agency_staff, co_system, erp_pipeline, system, customs_filing}` (mig 066).
- `intent ∈ {asserted_technical, derived, modified_for_case, staff_edit, customs_declared}` (mig 066).

"Flat" per the user's wording = `flatten_status in ('flattened','not_applicable')` AND NOT `source_bom_kind = 'technical_raw' | 'technical_non_flattened'`.

## 4. Active / superseded model in DH — already tracked

DH already has the concepts. From `db/migrations/006_bom.sql:9-25`:

- `status text not null default 'published'` with `chk_status check (status in ('draft','published','superseded'))`.
- `tombstoned_at timestamptz` — soft delete. Index `idx_bom_versions_alive` filters `where tombstoned_at is null`.
- `parent_artifact_id` — lineage pointer (NOT a "replaced_by" pointer; chain runs child→parent).
- `lineage_root_id` (mig 052) — groups variants of the same logical version.
- `is_stale` / `stale_reasons` / `state ∈ {clean, needs_refresh, needs_input, broken}` (mig 068) — UI-facing 4-state summary.

The `latest_flattened_versions` query (`stores/bom.py:1554`) already filters exactly the "active flat" set:
```sql
where ... and tombstoned_at is null
  and status = 'published'
  and intent in ('asserted_technical','staff_edit','derived','customs_declared')
  and flatten_status in ('flattened','not_applicable')
```
…and partitions by `(bom_variant_id, flatten_strategy)` taking the newest `published_at` per partition.

`/bom/latest` already returns this filtered set (length 1 ⇒ pinned; length > 1 ⇒ 409 dual-source variants).

The gap is **on `/bom/artifacts`**: it returns the raw history. The picker either needs server-side filtering or CO must reapply the same predicate.

## 5. Version metadata available for the picker

Already in the `/bom/artifacts` response:
- `artifact_no` — monotonic version number per `(client, product)`.
- `published_at`, `created_at` — for "effective date" display.
- `human_label`, `display_label` — DH-curated label string (e.g. "v3 · manual_flat · flattened").
- `source_bom_kind`, `source_channel`, `actor`, `intent` — provenance.
- `flatten_status`, `flatten_strategy`, `bom_shape` — calculation-readiness.
- `is_stale`, `stale_reasons`, `state` — freshness/health.
- `bom_variant_id`, `bom_code` — dual-source variant differentiation.
- `row_count` — already shown.

CO currently throws away every field except `artifact_no`, `row_count`, and the derived CO `status`.

## 6. Proposed filter

Two paths; the right one depends on whether DH is open to a contract change.

### Option A (preferred) — server-side filter on `/bom/artifacts`

File a DH API request to extend `GET /v1/hub/products/{product_code}/bom/artifacts` with:

| Param           | Default                                  | Meaning                                                          |
|-----------------|------------------------------------------|------------------------------------------------------------------|
| `lifecycle`     | `active`                                 | `active` ⇒ `status='published' AND tombstoned_at IS NULL`        |
| `shape`         | `flat`                                   | `flat` ⇒ `flatten_status IN ('flattened','not_applicable')`      |
| `intents`       | `asserted_technical,staff_edit,derived,customs_declared` | exclude `modified_for_case` (case-scoped CO proposals) |
| `latest_per_variant` | `true`                              | only newest `published_at` per `(bom_variant_id, flatten_strategy)` |

This is exactly what `latest_flattened_versions` already computes; the new endpoint just returns the multi-row form rather than 409'ing on len>1.

Concrete: `GET /v1/hub/products/{p}/bom/artifacts?client_id=X&lifecycle=active&shape=flat&latest_per_variant=true`.

### Option B (no DH change needed) — CO-side filtering

`bom_service.product_version_options_by_code` already drops `non_flattened` and `variant_conflict`. Extend it (and `_build_workspace`) to also drop:
- `artifact.tombstoned_at` not null
- `artifact.status != 'published'`
- `artifact.intent == 'modified_for_case'` (case-scoped proposals leak otherwise)
- artifacts not winning the `(bom_variant_id, flatten_strategy)` `published_at` race

This works today against the existing contract but ships duplicated filter logic that must stay in sync with DH's `latest_flattened_versions`. The whole list is also paginated/cached by CO so the over-fetch cost is bounded.

Recommendation: **Option B as a 1-2 hour fix now**, with a parallel Option A request for the right long-term contract.

## 7. UI display recommendation

Replace `#{n} · {rows} dòng · {status}` with a richer row. Suggested columns / badges per option:

- `#{artifact_no}` — kept (monotonic, what operators already know).
- `{published_at|date}` — effective date.
- `{row_count} dòng` — kept.
- Badge: `source_bom_kind` short label (`manual-flat`, `technical-flat`, `co-edit`, `staff-edit`, `customs-filed`).
- Badge: `flatten_strategy` (`as-provided`, `exploded`, `btp-leaf`, `btp-exploded`, `mixed`) — only when not `manual_flat_as_provided`.
- Badge: variant tag if `bom_variant_id != 'default'` (e.g. `m16_2025`).
- Badge: `state` when not `clean` (yellow `needs_refresh`, orange `needs_input`, red `broken`, with tooltip from `stale_reasons`).
- Tooltip / details row: `human_label` from DH (already a curated string).

Default selection: the artifact returned by `/bom/latest` (single) or the first by `published_at` desc.

## 8. Open questions for the user

1. Do you want **case-scoped `modified_for_case` proposals** visible in the picker for the same case (so an operator can re-pick a draft they just submitted), or never?
2. Should **`customs_declared` (Mẫu 16) variants** be selectable from the picker, or only readable via the dossier viewer? They are technically "flat and active" but represent a regulatory snapshot, not the calculation-truth BOM.
3. When a TP has **dual-source variants** (`purchased_btp_as_leaf` AND `self_produced_btp_exploded` both live), should the picker show both rows (operator picks) or refuse and surface a "needs decision" callout? Current `/bom/latest` 409s.
4. Confirm whether the fix should land via DH contract change (Option A — cleaner, ~1 sprint cycle including DH provider tests) or CO-side filter only (Option B — same-day, duplicated logic).
5. Should the picker also surface BOMs that are *almost* flat — `technical_non_flattened` — with a disabled state and explainer, or hide them entirely?
