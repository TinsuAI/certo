# Feature: CO BOM Data Hub Migration

## Scope
- Move CO BOM source-of-truth from CO-local state to Data Hub when `DATA_HUB_ENABLED=1`.
- CO should read canonical BOM products, versions, and rows from Data Hub.
- CO should submit case-specific BOM changes through Data Hub's BOM proposal endpoint, not publish local BOM versions.
- CO should keep only workflow bindings/snapshots needed for a C/O case: selected Data Hub BOM version IDs, per-product selected versions, proposal IDs, and immutable export/calculation snapshots.
- Local/Postgres CO BOM store remains as offline/demo fallback when Data Hub source mode is disabled.

Out of scope:
- Direct writes from CO into the `hub` Postgres schema.
- Moving CO case state to Data Hub.
- Letting CO upload canonical agency BOM files directly; canonical BOM upload stays in Data Hub UI.

## Decisions
- Data Hub is ready enough to be the BOM owner:
  - Data Hub schema has `hub.bom_versions`, `hub.bom_version_rows`, `hub.bom_audit_events`, and `hub.bom_change_requests`.
  - Data Hub API contract exposes product/BOM reads and `POST /v1/hub/products/{product_code}/bom/proposals`.
  - Local Data Hub DB currently has BOM data: `growatt-vn` has 293 BOM versions for 212 product codes with 23,902 BOM rows; `johnson-vn` has 2 versions.
- CO should stop treating BOM as CO-owned shared data in Data Hub mode.
- CO still needs to persist case-level BOM selections because Data Hub's latest BOM is not the legal case snapshot. The case must bind to explicit version IDs.
- CO should consume only documented Data Hub API endpoints through `app/data_hub_client.py`.
- The current CO `bom_workspace` shape should be preserved behind an adapter first to avoid rewriting templates and C/O case forms in the same migration.

## Risks
- CO's current BOM model has aggregate BOM versions plus per-product versions. Data Hub has per-product versions and no CO-style aggregate version concept. The adapter must synthesize a compatible view or the UI must be simplified.
- CO's case form currently binds `bom_version_id` and `bom_product_version_overrides`, but full BOM selection persistence is weak; this should be fixed before relying on Data Hub pinned versions.
- CO's `DataHubClient` currently lacks BOM methods. Adding raw `/v1/hub/.../bom` strings outside `app/data_hub_client.py` would violate the Data Hub policy guardrail.
- Data Hub proposal writes require a real user JWT and edit access. Service-account JWT/scopes are still backlog, so CO automation should use current user context for MVP.
- Data Hub auto-rule only validates parent version, material existence, tolerance, and anti-bloat. It does not validate an active CO case yet.
- Browser-editable Data Hub token config is local/demo only; production should use env/secret config before enabling BOM proposal writes.

## Migration Plan
1. Add CO contract coverage for Data Hub BOM.
   - Extend `app/data_hub_client.py` with `list_products`, `list_bom_versions`, `get_bom_latest`, `get_bom_version`, and `submit_bom_proposal`.
   - Keep all `/v1/hub/*` literals inside `app/data_hub_client.py`.
   - Add CO tests with an `httpx.MockTransport` provider fake.

2. Introduce a BOM service boundary in CO.
   - Create `app/bom_service.py` or extend the portfolio boundary with `bom_workspace(client)`.
   - Local mode delegates to existing `app/bom_store.py`.
   - Data Hub mode adapts Data Hub product/version/row responses into the existing `bom_workspace` template shape.

3. Make CO BOM UI read-only in Data Hub mode.
   - Hide or redirect canonical BOM upload/config controls to Data Hub.
   - Keep local upload/config only when `DATA_HUB_ENABLED=0`.
   - Show Data Hub backend/source metadata on the BOM page.

4. Bind C/O cases to Data Hub BOM version IDs.
   - Persist selected aggregate/synthetic version and per-product Data Hub version IDs in CO case state.
   - Store a compact immutable snapshot of rows used for calculation/export, not the whole canonical BOM store.

5. Add proposal flow for case-specific BOM changes.
   - From the C/O origin step, submit `modified_for_case` proposals with `parent_version_id`, `case_id`, and rows.
   - On approval, bind the returned `version_id` to the case/product.
   - On rejection, show `decision_reason` and `failed_conditions`; do not mutate local BOM state.

6. Migrate existing CO BOM state into Data Hub or archive it.
   - For clients where Data Hub already has canonical BOM, map CO client IDs to Data Hub client IDs and compare product/version coverage.
   - For CO-only BOM versions that are still needed, import them through Data Hub's internal upload/import path or a dedicated provider-side migration script, preserving provenance.
   - After cutover, keep CO tables/files read-only for rollback until user signs off.

## Open Questions
- Should CO keep the existing full BOM management page as a read-only Data Hub viewer, or should canonical BOM management fully move users to Data Hub?
- Does CO need aggregate BOM version semantics after Data Hub cutover, or can C/O cases bind directly to per-product Data Hub versions?
- Which CO-local BOM versions are legally relevant and must be migrated, versus demo/dev artifacts that can be dropped?
- Should BOM proposal submission use current user JWT for MVP, or wait for Data Hub service-account JWT scopes?
