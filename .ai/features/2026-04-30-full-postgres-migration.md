# Feature: Full Postgres Migration

## Scope

Migrate the current C/O FastAPI app from JSON/filesystem state stores to PostgreSQL-backed application state.

This migration covers:

- Client records and demo seed data currently held in `app/demo_data.py`.
- Client config currently stored under `data/local/client-config`.
- Source portfolio state currently stored under `data/local/source-modules`:
  - catalog/BCCT upload metadata,
  - parsed snapshots,
  - published versions,
  - current published rows,
  - diffs,
  - correction candidates,
  - audit events.
- Existing source read models already in Postgres:
  - catalog current rows,
  - BCCT rows,
  - BCCT invoice token index,
  - derived C/O stock rows.
- BOM builder state currently stored under `data/local/bom-builder`:
  - BOM config,
  - upload metadata,
  - parsed snapshots,
  - product versions,
  - aggregate versions and composition,
  - diffs,
  - audit events.
- C/O dossier workflow state currently stored under `data/local/co-cases`:
  - case records,
  - shipment metadata,
  - supporting-file metadata,
  - workflow timestamps/status fields that currently exist.

This migration does not cover:

- Storing raw uploaded files as Postgres blobs. Raw workbooks, PDFs, images, and docs should remain on filesystem/object storage, with Postgres storing path, hash, size, MIME/extension, and ownership metadata.
- Migrating archived agency source material under `data/` into Postgres.
- Migrating Playwright screenshots, manual-test files, logs, pid files, or temporary runtime directories.
- Migrating the separate Node legal lookup corpus unless it becomes part of the C/O app state later.
- Changing auth/deploy architecture in the same pass.

## Decisions

- PostgreSQL should become the source of truth for app state and parsed/source rows.
- Raw binary files stay outside Postgres. This keeps the DB focused on structured state and avoids turning backup/restore into a binary-file problem.
- Keep `PortfolioService` as the C/O-to-source boundary. `app/main.py` should continue consuming source/config through the portfolio adapter.
- Remove normal runtime JSON fallback after migration. JSON can remain only as an import/export/bootstrap format, not as an alternate live state path.
- Use staged implementation slices instead of one rewrite:
  1. Database foundation and migration discipline.
  2. Client records and client config.
  3. Source portfolio source-of-truth writes.
  4. SQL pagination/search for source tables.
  5. BOM state.
  6. C/O case workflow state.
  7. Remove file-backed runtime stores and keep import/export tools.
- Add schema-version tracking before adding more tables. The current `create table if not exists` style is fine for the first index layer, but full app state needs ordered migrations and rollback/reapply clarity.

## Risks

- A single large migration can break upload/version/audit behavior in multiple modules at once. Implementing in slices keeps the app usable after each step.
- Dual-write drift is likely if JSON and Postgres both remain live for too long. Each slice should pick one writer and one source of truth.
- Existing tests rely on lightweight file-backed fixtures and environment defaults. Tests need database fixtures or repository abstractions before removing JSON stores.
- Growatt BCCT data is large enough that materializing entire workspaces is already costly. Full Postgres migration should include SQL-level pagination/search for large table views before expanding API usage.
- BOM state has more complex version semantics than source catalogs because it tracks product versions and aggregate composition. Migrating BOM should happen after source portfolio patterns are stable.
- C/O dossier persistence currently stores shipment/supporting metadata more than full origin calculation state. Moving to Postgres should preserve current behavior first, then add richer durable workflow state only as a separate feature.

## Open Questions

- Should development/test mode require a local Postgres database, or keep a small in-memory/test repository for unit tests?
- Should uploaded files stay in the current local filesystem path layout for now, or should we introduce an object-storage-style abstraction immediately?
- Should the first implementation slice make Postgres mandatory whenever `BARRY_DATABASE_URL` is set, or should it fail fast if the env var is missing?
- Should existing uncommitted portfolio/Postgres boundary work be committed before starting this migration, so the migration has a clean base?

## Suggested Next Step

Use TDD and migrate in focused commits.

Recommended first implementation slice:

1. Commit the current portfolio/Postgres boundary work.
2. Add migration tracking and shared DB connection helpers.
3. Add `clients` and `client_configs` tables.
4. Import existing config JSON into Postgres.
5. Move `PortfolioService.get_client_config()` and `save_client_config()` to Postgres.
6. Keep raw file-backed source/BOM/C/O stores unchanged until this slice passes tests.
