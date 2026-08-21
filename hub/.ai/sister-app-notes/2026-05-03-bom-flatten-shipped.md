# Notes for CO + BCQT — BOM flattening shipped

**Provider:** Data Hub  ·  **Consumers:** CO, BCQT  ·  **Date:** 2026-05-03

Posted from Data Hub side. **Required reading before CO migrates to consume Data Hub BOM.** BCQT settlement consumers also affected (any code that reads `/v1/hub/products/{p}/bom/*`).

## What changed in Data Hub

The `technical_flatten` upload profile now lands in Data Hub, behind a staff-confirm gate. New BOM versions carry **structured identity + flatten metadata** that consumers MUST honor.

### Schema additions (migration `021_bom_flatten_and_uom.sql`)

`hub.bom_versions` gains:
- `source_bom_kind` — `manual_flat | technical_raw | technical_flattened | technical_non_flattened | co_modified | staff_edit`
- `flatten_status` — `flattened | non_flattened | not_applicable`
- `flatten_strategy` — `manual_flat_as_provided | technical_exploded | purchased_btp_as_leaf | self_produced_btp_exploded | mixed_confirmed | no_strategy`
- `source_channel`, `bom_code`, `bom_variant_id`, `lineage` (jsonb), `display_label`, `flatten_method`, `flatten_method_version`

All values are **stable English machine codes**. Vietnamese stays in the UI/i18n layer. **Never store, query, or pattern-match on `display_label`** — it is a denormalized cache.

Three new tables:
- `hub.bom_unresolved_nodes` — per-row evidence for `non_flattened` versions.
- `hub.bom_flatten_decisions` — staff-confirmation audit (dual-source picks, non_flattened publishes, UOM choices, etc.).
- `hub.uom_canonical` + `hub.uom_aliases` + `hub.client_uom_overrides` — UOM model.

Existing `manual_flat` versions backfilled with `flatten_status='not_applicable'` so legacy callers see no change.

## API contract changes

### `GET /v1/hub/products/{p}/bom/latest` is now flatten-aware

- **Excludes `non_flattened`.** Calculation consumers must never silently consume a non-flattened BOM. If you fetch a specific `version_id`, check `flatten_status` yourself.
- **Returns `409 Conflict` when dual-source variants are published** for the same product (both `purchased_btp_as_leaf` and `self_produced_btp_exploded` live). The 409 body includes `variants[]` with `version_id` + `flatten_strategy` + `display_label` for each candidate. The consumer MUST pick a variant and rebind via `?version_id=…`.

`200` response gains the new fields plus `unresolved` and `decisions` arrays. See `docs/API_CONTRACT.md` for the full shape.

### `GET /v1/hub/products/{p}/bom/versions` and `?version_id=…`

Same response extension (new fields included). `version_no` is now scoped to `(client_id, product_code, bom_variant_id)`, so two variants of the same product can both legitimately be at `version_no=1`. Compare on `version_id` or the structured tuple — never `version_no` alone.

## What consumers MUST do

1. **Reject `non_flattened`.** If your code reaches a version with `flatten_status='non_flattened'` (e.g. via a pinned `version_id` someone passed in), refuse it with a clear error. Do not multiply quantities, do not sum costs, do not feed it into RVC calculations.

2. **Handle 409 from `/bom/latest`.** Don't silently pick the first variant — surface the choice to the operator (CO case worker, BCQT settlement runner). Once picked, persist the `version_id` against the consuming entity (case_id / settlement run) so re-runs are reproducible.

3. **Don't compare `display_label`.** It contains business-meaningful structured data (`product · variant · v# · kind · status · strategy`), but it's a cache. Compare `version_id` or the structured tuple.

4. **Treat `lineage.btp_versions_used[].version_id` as authoritative.** When a TP says it was flattened against BTP version `bv_X`, that's the binding. Don't try to "re-resolve" the BTP yourself.

## What consumers MAY do later (out of scope this drop)

- Adopt `service_account JWTs` (separate sister-app note from 2026-05-02). Currently coexists with user JWTs; no urgency.
- Consume `unresolved[]` and `decisions[]` arrays for richer UX (e.g. show CO case operators which staff-confirm gates were waved through).

## Out of scope for this drop

- CO migration itself — this drop **only** lands the Data Hub side. CO continues to operate against its current local BOM until the consumer-migration sprint runs.
- New `POST` endpoints for CO. Existing `/bom/proposals` is unchanged.
- BCQT consumer-mode migration.

## Verification

Data Hub-side test count: **295 passed, 15 skipped** (was 239 baseline). New tests cover all 28 spec items from `~/workspace/client/barry-CO-main/.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md` § "Tests First". See `.ai/features/2026-05-03-bom-flattening.md` and the local plan file.
