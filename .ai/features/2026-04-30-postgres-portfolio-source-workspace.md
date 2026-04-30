# Feature: Postgres Portfolio Source Workspace

## Scope

Move the C/O app's shared source workspace toward PostgreSQL-backed portfolio storage.

This implementation slice covers:

- Persisting indexed catalog rows for material and product catalogs in Postgres.
- Persisting indexed BCCT correction candidates in Postgres.
- Rebuilding all source workspace indexes from the current JSON audit store.
- Serving Catalog, BCCT, and C/O stock table pages from Postgres when `BARRY_DATABASE_URL` is configured and the client has indexes.
- Keeping JSON files as audit/fallback while the app transitions.

This slice does not cover:

- Moving C/O dossiers to Postgres.
- Moving raw uploaded binaries into Postgres.
- Moving BCQT-System settlement/project DBs.
- Final standalone service boundaries or auth between services.

## Decisions

- Keep the existing upload/parser/versioning code paths for now, but make their Postgres refresh path complete enough that UI reads no longer need JSON for indexed clients.
- Add `source_catalog_rows` instead of mixing catalog payloads into `source_index_metadata`.
- Add `source_correction_candidates` so BCCT review warnings remain visible when pages use the Postgres workspace.
- Keep read-model methods returning the same workspace shape currently expected by Jinja templates.
- Fall back to JSON if Postgres is unavailable or a client has no indexed metadata.

## Risks

- This is still not a full source-of-truth migration; JSON remains authoritative during this slice.
- Full production migration needs write paths that commit directly to Postgres and emit JSON audit exports, rather than rebuilding from JSON after each upload.
- Loading all indexed rows for table pages is acceptable for this step but SQL pagination should replace it for large BCCT views.

## Open Questions

- Should raw upload storage stay filesystem-backed permanently with DB metadata, or move to object storage when deployed?
- Should catalog and BOM writes become direct Postgres writes in the same migration as BCCT writes, or in separate slices?

## Suggested Next Step

Use TDD:

1. Add failing tests for catalog row materialization and Postgres-backed table pages.
2. Add Postgres schema and record builders.
3. Add workspace read methods.
4. Route source table contexts through the Postgres workspace when available.
5. Run pytest and browser/UI smoke tests.
