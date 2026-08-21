# Feature: Data promotion + onboarding CLI

Unify three workflows into one mechanism + one tool:

1. **Pre-prod fast iteration**: dev schema/reference/customer changes
   land on demo as part of the normal push-to-main flow.
2. **Customer onboarding**: maintainer (Tinsu) bulk-imports a new
   customer's existing Excel/CSV into Data Hub, bypassing the UI to
   avoid per-row error → reproduce → fix loops.
3. **Production discipline (later)**: same tool, stricter modes —
   migration-only reference seeding, no blanket overwrites.

## Scope

**In:**
- `DATA_HUB_REFERENCE_DATA_MODE` env flag, three values:
  `oneshot` (current default), `upsert`, `migration_only`. Wired
  into `app/seed_master_data.py`.
- `scripts/export_client.py --client <slug> -o bundle.tar.gz`
  produces a per-client bundle (DB rows + appfiles).
- `scripts/onboard_client.py --client <slug>
  --from-{excel,export} <path> [--commit] [--mode=replace|append]`
  reads either source, writes to DB + appfiles via reused parser
  / store layer.
- Bundle format: `pg_dump --data-only --schema=hub` filtered to
  client-scoped tables via `--table` + a per-client WHERE driver
  (Python wrapper using `COPY ... TO STDOUT WITH (FORMAT binary)`
  for client-scoped extraction; cleaner than pg_dump filters).
  Bundle includes `manifest.json` (schema version, source DB,
  client_id, created_at) + `db.sql` + `files/` tarball of
  `appfiles/<client_id>/*`.
- Manifest gate on import: refuse if bundle's schema version
  doesn't match target (no auto-migration of bundle data).
- Updated `docs/release-engineering.md` §4 (seed taxonomy) +
  new §8 (data promotion flow).

**Out:**
- Cross-client bundle (multi-tenant export). One client per
  bundle.
- Auto-generated test fixtures from bundles (could be useful
  later, not now).
- Backfilling appfiles backup as part of this feature (separate
  Tier-2 uplift work — but flagged here as a dependency).
- Web UI for upload/import. CLI only.
- Service-account-mediated import (HTTP API path). Direct DB
  write with provenance tagging.

## Decisions

- **One CLI handles both Excel and bundle import.** `--from-excel`
  and `--from-export` are sister flags. Reuses parser layer
  (`app/parsers/{bcct,materials,bom}.py`) and store layer
  (`app/stores/`) — no logic fork. Onboard CLI is the bulk
  equivalent of UI upload.
- **Per-client scope.** Bundle = one client_id. The schema's
  `on delete cascade` from per-client tables to `hub.clients`
  makes "replace mode" simple: `DELETE FROM hub.clients WHERE
  client_id=X` wipes the whole subgraph cleanly, then re-insert.
- **Reference data (C2) flows separately** via the env-flag
  mechanism, NOT through the per-client bundle. Bundle stays
  client-only; reference is a release artifact.
- **Provenance tagging.** Imports stamp
  `provenance.source = 'onboard_cli:excel'` or
  `'onboard_cli:export:<source_db>'`. Lets future auditors trace
  "where did this row come from" without parsing app logs.
- **Default mode per env (recommendation, needs sign-off):**
  - dev local: `REFERENCE_DATA_MODE=upsert` (fast iteration)
  - demo (tinsu): `upsert` (same — demo IS the fast-feedback env)
  - production: `migration_only` (audit-friendly)
- **Bundle conflict policy (recommendation, needs sign-off):**
  `--mode=replace` is the default and only mode for now —
  delete-then-insert within client scope. `append` mode deferred
  until a use case appears. Justification: bundle is ground
  truth for that client at export time; partial merges create
  ambiguous state.

## Risks

- **`appfiles` volume is not backed up** on tinsu (Tier 1 covers
  pg only). If demo's `appfiles` is lost, BCCT/material rows
  point at missing files. The bundle MUST include files for
  this feature to be correct, AND we should treat appfiles
  backup as the next Tier-1.5 uplift even outside this feature.
- **Schema version drift between dev and demo** during a deploy
  window. If maintainer exports from dev at SHA `A`, demo is at
  SHA `B`, and bundle schema version doesn't match, import
  refuses. Mitigation: deploy first, then promote data. Manifest
  check enforces this — better to fail loud than corrupt.
- **`hub.clients` cascade is wide.** Replace mode wipes ALL
  per-client data including chat threads, notifications,
  uploads audit. Acceptable for promotion (we want a clean
  slate), but the CLI must show a confirmation summary and
  require `--yes` outside `--commit` dry-run.
- **`scripts/feed_demo_company.py` is the wrong shape.** It's
  Playwright UI driver, generates demo data via UI clicks. After
  this feature, deprecate it in favor of `onboard_client.py
  --from-excel`. Don't delete yet — the existing artifacts under
  `.ai/features/2026-05-04-demo-company-feed/` reference it.
- **`upsert` reference mode on demo could clobber UI-edited
  reference rows.** Currently declaration_types and
  client_type_presets are admin-curated only — low risk. But
  worth a pre-flight check: are there ANY tables in
  `data/seeds/*.yaml` that customers/staff edit via UI? If yes,
  upsert mode will overwrite. Adding a `protected_columns` list
  to the YAML format mitigates if needed.
- **Service accounts table (migration 020) is per-DB.** If
  bundle includes service-account rows (it shouldn't — they're
  per-deployment infrastructure), import would corrupt demo
  auth. Bundle's table allow-list must be explicit, not
  "everything with client_id."
- **Cross-FK from allow-list tables to per-deployment tables**
  (caught in round-4 review). Some allow-listed tables have FK
  columns that point at per-deployment tables (`hub.users`):
  `client_config.updated_by`, `parser_mappings.confirmed_by`,
  `bom_flatten_decisions.confirmed_by`. Source's user_ids are
  meaningless on the target. Mitigated by `null_columns` on
  TableSpec — those columns are emitted as NULL at export time.
  Also caught: `bcct_rows.upload_id` and `bom_versions.source_upload_id`
  reference `hub.file_uploads` which was missing from the original
  allow-list — added in round 4 (without it, real Growatt's 23k
  bcct_rows would FK-fail on fresh-target import).
- **Replace cascade wipes excluded tables for the target client_id**
  (caught in round-2 review). Bundle deliberately excludes
  `chat_threads`, `chat_messages`, `llm_usage`, `notifications`,
  `upload_pending`, `bcct_row_history`, `material_audit_events`
  for some deployment-only tables — but `DELETE FROM hub.clients
  WHERE client_id = X` cascades, so those tables get wiped on
  the target for that client_id even though the bundle doesn't
  re-supply them. For dev → demo this is fine (no real chat
  history yet). For any future Tier-P replace mode, this would
  lose audit history and notifications. Mitigations when prod
  needs it: (a) refuse replace mode on prod via env flag, or
  (b) selectively re-insert audit/chat tables from a target-side
  snapshot before wiping. Not coded for v1; flag in the CLI's
  dry-run output as a follow-up.

## Resolved decisions (signed off 2026-05-04)

1. **Bundle format**: pg_dump-derived (Python-driven `COPY` per
   allowed table). Schema-version manifest gate handles
   portability.
2. **Conflict policy**: `--mode=replace` only for v1. Append
   deferred.
3. **Files inclusion**: bundle includes `appfiles/<client_id>/`
   tarball, mandatory.
4. **`REFERENCE_DATA_MODE` defaults**: dev=`upsert`,
   demo=`upsert`, prod=`migration_only`. Pre-flight: confirm
   no UI-editable rows in `data/seeds/*.yaml` (so far:
   declaration_types + client_type_presets both admin-only —
   safe).

## Manual test plan

- **Test 1 — reference upsert.** Edit
  `data/seeds/declaration_types.yaml` (add a row, change a
  display name). Set `REFERENCE_DATA_MODE=upsert`. Restart app.
  DB row reflects YAML. Set back to `oneshot`, edit YAML again,
  restart. DB row unchanged.
- **Test 2 — onboard from Excel.** Pick a real customer Excel
  set under `.ai/features/2026-05-03-source-data-inventory/`.
  Run `onboard_client.py --from-excel ./<dir> --client testco`
  dry-run, inspect plan, then `--commit`. Verify rows in DB +
  files in `appfiles`.
- **Test 3 — export → import roundtrip.** On dev:
  `export_client.py --client testco -o /tmp/testco.tar.gz`.
  Drop client on dev: `psql -c "DELETE FROM hub.clients WHERE
  client_id='testco'"`. Re-import:
  `onboard_client.py --client testco --from-export
  /tmp/testco.tar.gz --commit`. Diff before/after — should be
  identical except for timestamps + provenance tags.
- **Test 4 — dev → demo promotion.** Real flow. Export a real
  client from local dev, scp to tinsu, import via
  `docker compose exec`. Verify the demo's existing other
  clients are untouched.
- **Test 5 — schema version mismatch.** Export from dev. Apply
  a new migration on dev (don't deploy to demo). Try importing
  on demo. Should refuse with a clear "schema version mismatch"
  error.

## Done criteria

- All 5 manual tests pass on the dev box (3, 4 also on tinsu).
- `docs/release-engineering.md` §4 updated to describe modes.
- `docs/release-engineering.md` §8 (new) describes the
  promotion flow with the runbook for tinsu.
- `scripts/feed_demo_company.py` marked deprecated in its
  docstring (don't delete).
- Memory `reference_demo_server.md` updated with the
  promotion runbook command.

## Suggested next step

After user signs off on the 4 open questions: `/tdd` for
`onboard_client.py` (parser path is risky — wrong column
mappings could silently corrupt a customer's BOM). `export` and
the env-flag are mechanical; test-after acceptable.

## Validation: real-data round-trip (round-5 review)

`scripts/smoke_roundtrip_client.py` runs export → DELETE → import →
verify on a real client. Validated end-to-end on growatt-vn:

- 23,080 bcct_rows preserved with all aggregates matching
- 467 materials, 329 bom_versions, 23,868 bom_version_rows preserved
- 9 file_uploads, 2 parser_mappings (with confirmed_by NULLed)
- 55 appfiles restored
- bcct_row_history / bom_audit_events purged on import (no
  trigger-driven accumulation across re-imports)

Two production-blocker bugs were caught ONLY by running the real
round-trip after rounds 1–4 had all pronounced "ready to commit":

- **C#7** — file_uploads.client_id is `ON DELETE SET NULL` (not
  CASCADE). DELETE hub.clients leaves orphan rows, bundle re-INSERT
  PK-conflicts. Fixed via `pre_delete=True` on TableSpec; explicit
  DELETE before the cascade.
- **C#8** — `trg_bcct_row_history` trigger fires on cascade DELETE
  and inserts ~23k spurious "delete" history rows; on re-import the
  bundle's history rows PK-conflict and unbounded accumulation.
  Audit tables removed from allow-list and explicitly purged at
  import via `AUDIT_TABLES_TO_PURGE_ON_IMPORT`.

Lesson: dry-run + minimal-fixture unit tests can't surface schema
interactions. The smoke script is now part of the release ritual
for data_promotion changes.

## Implementation status (2026-05-04 TDD session)

**Done & green:**

- Slice 1 — `DATA_HUB_REFERENCE_DATA_MODE` env flag wired into
  `app/seed_master_data.py`. Modes: `oneshot` (default,
  unchanged behavior), `upsert` (re-seed every call, ON CONFLICT
  DO UPDATE from YAML), `migration_only` (no-op).
  5 tests: `tests/test_seed_master_data_modes.py`.
- Slice 2 — `app/data_promotion.export_client()` + thin CLI
  `scripts/export_client.py`. Bundle is `tar.gz` containing
  `manifest.json`, `db/NNN_<table>.sql` (allow-listed tables
  only, FK-safe order), `files/<module>/<client>/...` mirror.
  7 tests: `tests/test_data_promotion_export.py`. Smoke-tested
  on real `growatt-vn` (11 MB bundle, 12 SQL files, files
  bundled correctly).
- Slice 3a — `import_client_bundle()` + `scripts/onboard_client.py
  --from-export`. Replace mode (cascade-wipe via hub.clients).
  Refuses on `schema_version` or `format_version` mismatch.
  Dry-run by default; `--commit` writes. 6 tests:
  `tests/test_data_promotion_import.py`, including a full
  export → wipe → import roundtrip.
- 461 tests pass (15 skipped) — full suite green, no regression.

**Deferred to next session:**

- Slice 3b — `--from-excel` path on `onboard_client.py`. Stub
  raises a clear NotImplementedError pointing here. Real impl
  needs to drive `app/parsers/{bcct,materials,bom}.py` through
  the same flow the UI upload uses (likely via
  `app/routes/upload.py` re-use). Highest-risk slice — TDD it
  carefully with real-data fixtures from
  `.ai/features/2026-05-03-source-data-inventory/`.
- `docs/release-engineering.md` §4 update (mode-aware C2 row)
  and a new §8 documenting the promotion runbook (export on
  dev → scp to tinsu → `docker compose exec` import).
- Set `DATA_HUB_REFERENCE_DATA_MODE=upsert` on the tinsu
  Compose env (currently unset → defaults to `oneshot`). Add
  to `docker-compose.yml` with a default + document in
  `.env.example`.
- Loose end carried from prior handoff: memory
  `feedback_use_python_heredoc.md` (referenced from
  `deploy/runbook.md` but doesn't exist).

**Files added:**

- `app/data_promotion.py` (~250 lines)
- `scripts/export_client.py` (~50 lines)
- `scripts/onboard_client.py` (~95 lines)
- `tests/test_seed_master_data_modes.py` (~120 lines)
- `tests/test_data_promotion_export.py` (~145 lines)
- `tests/test_data_promotion_import.py` (~190 lines)

**Files modified:**

- `app/seed_master_data.py` — mode-aware seeders + back-compat
  shim.
