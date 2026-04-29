# Feature: Postgres Source Indexes

## Scope

Add a PostgreSQL-backed index layer for the source data that currently makes Growatt C/O pages slow.

This change does:
- create a Postgres schema for indexed BCCT rows, invoice tokens, derived C/O stock rows, and source metadata
- add a CLI to migrate/apply the schema and import existing file-backed source state into Postgres
- let C/O dossier pages use lightweight source summary and indexed invoice matching when Postgres is configured
- keep the current JSON file stores as the source of truth and fallback during the transition
- reduce C/O page work by avoiding duplicate full `get_source_workspace()` calls

This change does not:
- move every source module write path fully into Postgres yet
- remove JSON state files
- change auth/deploy decisions
- add final HS/PSR legal rule evaluation
- implement SQL pagination for the BCCT table view yet

## Decisions

- Use `BARRY_DATABASE_URL` as the app-specific Postgres connection string.
- Keep file stores authoritative for uploads and versioning in this phase; Postgres is an indexed read model.
- Use plain SQL migrations under `db/migrations/` instead of introducing Alembic before the schema stabilizes.
- Store full BCCT and stock row payloads as `jsonb` while promoting hot lookup/filter columns into typed text columns.
- Use a separate invoice-token table so invoice matching can use indexed equality instead of scanning all BCCT rows.
- Keep fallback behavior if Postgres is not configured, so local tests and current manual demo remain usable.

## Risks

- Dual-write/read-model drift is possible if source uploads update JSON but indexes are not refreshed. Mitigation: importer can rebuild per-client indexes; later upload hooks should refresh affected client indexes automatically when DB is enabled.
- A DB outage with fallback enabled can hide configuration issues. Mitigation: document strict mode later if production needs fail-fast behavior.
- `jsonb` payloads preserve flexibility but should not become a dumping ground for all query patterns. Promote columns only when a real query needs them.
- BCCT table pages still load JSON until a separate SQL pagination pass is done.

## Open Questions

- Should production treat Postgres as the source of truth for uploads/versions, or keep JSON artifacts as immutable audit exports?
- Should C/O cases move into Postgres in the same migration wave, or after source indexes prove stable?
- Which deployment shape will own the Postgres lifecycle: local Docker Compose, managed Postgres, or client infrastructure?

## Recommended Next Step

Implement in test-backed slices:
1. Source summary and duplicate-load regression.
2. Postgres schema/import/read-model helpers.
3. C/O context integration with fallback.
4. CLI/docs and performance verification.
