# Session: 2026-05-05 — data-promotion feature ship

Single-feature session. Built the per-client export/import + reference
data mode flag, then went through 5 review rounds. Final round caught
2 production-blocker bugs that the first 4 rounds (all code review)
had missed. Shipped at commit `ea34c9d`.

## What Was Done

### Discovery + design

- `/discover` produced `.ai/features/2026-05-04-data-promotion/brief.md`.
- Resolved 4 open questions: bundle format = pg_dump-derived
  (Python-driven `COPY`-equivalent via `sql.Literal`); conflict
  policy = replace-only for v1; files inclusion = mandatory;
  `REFERENCE_DATA_MODE` defaults = dev/demo `upsert`, prod
  `migration_only`.

### Slice 1 — `DATA_HUB_REFERENCE_DATA_MODE` env flag

- Added 3 modes to `app/seed_master_data.py`:
  - `oneshot` (existing behavior preserved as default)
  - `upsert` (`INSERT ... ON CONFLICT DO UPDATE` from YAML each
    boot)
  - `migration_only` (no-op; reference data only via SQL migrations)
- Kept `seed_master_data_if_empty()` as compat shim so
  `app/main.py` and `tests/conftest.py` callers don't change.
- 5 unit tests in `tests/test_seed_master_data_modes.py`.

### Slice 2 — Export

- `app/data_promotion.export_client()` produces a tar.gz with:
  - `manifest.json` (format_version, client_id, schema_version,
    created_at, source)
  - `db/NNN_<table>.sql` per allow-listed table with INSERTs
    rendered via `sql.Literal` for type-safe quoting
  - `files/<module>/<client>/...` — appfiles mirror
- `scripts/export_client.py` thin CLI wrapper.
- 7 unit tests in `tests/test_data_promotion_export.py`.
- Smoke-tested on real `growatt-vn` (11 MB bundle, 12 SQL files,
  55 appfiles).

### Slice 3a — Import

- `import_client_bundle()` is 3-phase:
  1. Extract files to staging dir under `DATA_HUB_FILES_ROOT`
     (path-traversal check fails fast here)
  2. DB transaction (`session_replication_role` is NOT settable as
     `hub` role; can't disable triggers — see "What Didn't Work")
  3. After DB commit, atomic `os.replace` per file from staging
     into the real root
- `scripts/onboard_client.py --from-export` thin CLI wrapper;
  dry-run by default, `--commit` to write.
- 17 unit tests in `tests/test_data_promotion_import.py`.

### `--from-excel` STUBBED

- `scripts/onboard_client.py --from-excel` raises a clear
  `NotImplementedError` pointing at the brief's deferred section.
- Deferred because driving `app/parsers/{bcct,materials,bom}.py`
  through the upload-route flow needs its own TDD pass and
  real-data fixtures.

### 5 review rounds — bugs caught

Round-by-round (8 critical fixes in total — every round genuinely
found new bugs):

| Round | Critical findings | How caught |
|-------|-------------------|------------|
| 1 | tar path traversal; jsonb-vs-text[] | Code review |
| 1 | DB-commits-before-files atomicity | Code review |
| 2 | `os.replace` cross-fs EXDEV (Docker) | Deploy mental model |
| 3 | generated columns (`year`, `parent_norm`) | Schema review |
| 3 | manifest.client_id traversal → `rmtree` | Adversarial input |
| 3 | unrecognized db/*.sql executes as SQL | Defense in depth |
| 3 | stale per-client files persist on target | Idempotency review |
| 4 | cross-FK to non-bundled tables (`file_uploads`, user-FKs) | FK schema audit |
| 5 | **`file_uploads.client_id` is SET-NULL not CASCADE** | **Real --commit on Growatt** |
| 5 | **`trg_bcct_row_history` accumulates 23k rows / import** | **Real --commit on Growatt** |

Real-data round-trip on `growatt-vn`:
- 23,080 bcct_rows preserved with all aggregates matching
- 467 materials, 329 bom_versions, 23,868 bom_version_rows
- 9 file_uploads, 2 parser_mappings (with `confirmed_by` NULLed)
- 55 appfiles restored
- BCCT aggregates (max date, min date, sum quantity) match exactly

### Smoke script preserved

- `scripts/smoke_roundtrip_client.py` (CLI takes `[client_id]`) is
  the release ritual for any data_promotion change.

## Decisions Made

- **Bundle format**: pg_dump-derived SQL via Python `sql.Literal`
  rather than JSON/YAML serialized rows. Simpler, faster, reuses
  psycopg's adapter coverage. Schema-version manifest gate handles
  the portability concern (target must match exactly).
- **Conflict policy**: `--mode=replace` is the only mode for v1.
  Append/upsert deferred — no use case yet. Cascade-wipe via
  `hub.clients` is the simplest correct shape.
- **Files in bundle**: mandatory. Without files, BCCT/material
  rows reference dangling upload records; broken UX on the target.
- **Reference-data mode defaults**: dev=`upsert`, demo=`upsert`,
  prod=`migration_only`. Prod's strictness is auditable.
- **Allow-list scope**: customer-truth tables only. **Excluded**
  per-deployment data: chat threads, llm_usage, notifications,
  upload_pending, sessions, service_accounts, user_managed_clients,
  user_client_access. **Excluded** audit tables: bcct_row_history,
  material_audit_events, bom_audit_events (cross-deployment audit
  is meaningless; trigger interactions cause re-import bloat).
- **User-FK columns NULLed at export**: `confirmed_by`,
  `updated_by`, `bom_flatten_decisions.confirmed_by`. Source's
  user_ids are meaningless on the target. Defensive at export
  time so the bundle never carries them.
- **Path-traversal defenses in 2 places**: tar member names AND
  manifest.client_id. Both validated before any FS or DB write.
- **Schema-evolution self-check**: `_audit_allow_list` queries
  information_schema and warns when a new client_id-FK table
  appears outside both TABLES and EXCLUDED_CLIENT_SCOPED_TABLES.
- **`pre_delete=True`** for tables with non-CASCADE FK to clients
  (`file_uploads` only currently). Generic mechanism for future
  same-shape additions.
- **Audit-table purge on import**: explicit DELETE before bundle
  INSERTs, since cascade-trigger inserts to audit tables are
  spurious and accumulate per import. Non-superuser can't disable
  triggers; explicit purge is the workaround.

## What Didn't Work

- **`set session_replication_role = replica`** — would have been
  the cleanest way to disable cascade triggers during import.
  Permission denied to the `hub` role (requires superuser). Fell
  back to explicit DELETE on audit tables.
- **First 4 review rounds underestimated complexity.** Each
  pronounced "ready to commit"; round 5 (real --commit on Growatt)
  caught 2 production-blocker bugs (SET-NULL FK + trigger
  accumulation). Lesson: code review can't catch schema/trigger
  interactions. **Always run real-data smoke before declaring
  done.** Captured in handoff.
- **`cur.mogrify()`** — psycopg3 removed it. Switched to
  `sql.Literal` + `Composable.as_string(cur)`.
- **`cur.execute(body)` with placeholders** — psycopg3's
  multi-statement execute only works via `PQexec` (no params).
  My SQL files have `sql.Literal`-rendered values inline (no
  placeholders) so it works, but a comment was added to prevent
  future refactors from breaking it.
- **`os.replace(/tmp → /var/lib/data-hub/files)`** raised EXDEV on
  Docker (`/tmp` tmpfs vs named volume). Fixed by staging under
  files_root.
- **Unit-test fixtures with minimal data** missed: file_uploads FK,
  user-FK leak, generated columns, audit-trigger accumulation.
  Five rounds of review chasing increasingly subtle issues couldn't
  match one real round-trip.

## Open Items

- **`--from-excel` onboarding** (slice 3b). Stub raises clear
  NotImplementedError. Real impl needs to drive
  `app/parsers/{bcct,materials,bom}.py` through the same flow as
  the UI upload route (likely via `app/routes/upload.py` re-use).
  Highest-risk slice. TDD it carefully with real-data fixtures
  from `.ai/features/2026-05-03-source-data-inventory/`.
- **Docs**: `docs/release-engineering.md` §4 (mode-aware C2 row)
  and new §8 (promotion runbook for tinsu). Brief commits to this;
  not done.
- **Set `DATA_HUB_REFERENCE_DATA_MODE=upsert` on tinsu compose**
  env (currently unset → defaults to `oneshot`). Add to
  `docker-compose.yml` with default + document in `.env.example`.
- **Deprecate `scripts/feed_demo_company.py`** docstring (UI
  Playwright driver superseded by future `--from-excel`).
- **`appfiles` volume backup gap on tinsu** — flagged in brief.
  Tier-1.5 uplift candidate. Without it, file restore from a
  bundle is the only path back.
- **Concurrency under live writes**: export uses default
  READ COMMITTED isolation. If app writes during export, bundle
  could be inconsistent across tables. For dev→demo (operator-
  driven), low risk. Future improvement: REPEATABLE READ.
- **Sister-repo standards adoption** (CO + BCQT) carries over from
  prior handoff. Still not done.
- **Loose end**: `deploy/runbook.md` references memory
  `feedback_use_python_heredoc.md` that doesn't exist. Either
  create or remove the reference.

## Cross-references

- Brief: `.ai/features/2026-05-04-data-promotion/brief.md` (full
  decisions + per-round review findings)
- Smoke script: `scripts/smoke_roundtrip_client.py`
- Prior handoff: `.ai/sessions/2026-05-04-demo-deploy-cicd-and-standards.md`
- Memories captured this session: none new (carry-over only)
