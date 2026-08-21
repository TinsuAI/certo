# Session 2026-05-07 — BOM vocab rename + Phase 3 resolver / presets / classifier

Long, dense session. Started at "what next" check, ended with 7
commits pushed to origin and the entire Phase 3 brief shipped (3a +
3b + 3c core + /rev fix bundle), preceded by a full schema/code
rename pass.

## What Was Done

### 1. Vocab rename pass (mig 031, commits `edfa224` + `a2840cb`)

Brief at `.ai/features/2026-05-07-bom-vocab-rename/brief.md`. 10
locked decisions.

- **Migration 031** atomic transaction renames 3 tables
  (`bom_versions` → `bom_artifacts`, `bom_version_rows` →
  `bom_artifact_rows`, `bom_resolution_profiles` → `bom_presets`),
  10 columns spanning 7 tables (including `bcct_rows.bom_version_id`
  caught during test-suite fix-up). 9 indexes + 3 PK constraints
  renamed. Generated column `parent_norm` auto-updated by Postgres.
- **Code grep-replace** on 44 .py + .html files via perl bulk pass +
  targeted edits. Function renames (`list_versions_for_product` →
  `list_artifacts_for_product`, etc.). URL paths
  (`/bom/version/{id}` → `/bom/artifact/{id}`). Template renames
  (`bom_versions.html` → `bom_artifacts.html`). ID prefix `"bv_"` →
  `"ba_"` in two sites in `app/stores/bom.py`.
- **API response key rename** (option (a) breaking): `{"version":
  …}` → `{"artifact": …}`. Sister-app note for CO updated.
- **308 alias routes** for old URLs — one-release grace period
  tracked in BACKLOG "Drop BOM vocab v1 aliases".
- **Sister-app notes** posted to CO + BCQT clones (committed there
  in separate commits).
- **Test count**: 471 → 479 (+8 vocab-rename tests).

### 2. Phase 3a — btp_sourcing classifier + UI override + materializer (`5fb814a`)

- `scripts/detect_dual_source_btps.py` — classifier from BCCT
  `direction='import'` ∪ `bom_edges.parent_code` presence. Maps to
  `purchased_only` / `self_produced_only` / `dual_source` /
  `unknown`. Idempotent. Applied to Growatt-vn live: 148
  self_produced + 5 dual_source + 0 purchased + 0 unknown / 153
  BTPs total. Five dual_source codes match known rework set
  (B700.0192500, .0192600, .0200900, .0307300, ST06.0018700).
- **Catalog UI** adds `btp_sourcing` dropdown for `btp_sx` rows;
  staff override via POST
  `/clients/{c}/catalog/{customs_code}/btp_sourcing`.
- **Materializer SQL** (`SHALLOW_WALK_SQL`) extends stop_set logic:
  btp_sx with `btp_sourcing='self_produced_only'` is now exploded;
  every other btp_sx still stops the walk. NULL/unknown defaults
  to stop (safer than auto-explode).
- **Tests**: 14 new (7 classifier + 4 override + 3 materializer).

### 3. Phase 3b — resolver core + preset CRUD + endpoint wire + UI (`f5af5d2`)

- **`resolve_bom_artifact()`** in `app/stores/bom.py`. Precedence
  preset_id > case_id > shape > default. Returns
  `(artifact_id, shape, resolution_trail)`. Tombstoned presets
  remain queryable (D5).
- **`ResolverError`** exception class with stable `code` + `extra`
  fields; HTTP layer maps `code` → 4xx via `_raise_resolver_http`.
- **Preset CRUD endpoints** under `/v1/hub/`:
  POST `/presets`, GET `/clients/{c}/products/{p}/presets`, PATCH
  `/presets/{id}`, POST `/presets/{id}/tombstone`. ID prefix
  `bp_*`. No DELETE per immutability.
- **`GET /v1/hub/products/{p}/bom`** wired: accepts ?preset_id,
  ?case_id, ?shape; returns `resolution_trail`.
- **UI page** `/clients/{c}/bom/{p:path}/presets` — list alive +
  create + tombstone. Sourcing-choices jsonb editor deferred to
  Phase 3+ (BACKLOG note in template).
- **Sister-app note** for CO posted at
  `~/workspace/client/barry-CO-main/.ai/sister-app-notes/2026-05-07-bom-presets-3b.md`.
- **Tests**: 27 new (12 resolver + 10 CRUD + 5 endpoint wiring).

### 4. Phase 3c core — derive_btp_shallows + adapter hooks + multi-role badge (`dadbd0f`)

- `scripts/derive_btp_shallows.py` — for each raw_graph artifact,
  walks `bom_edges` and mints a new raw_graph artifact rooted at
  every `btp_sx` parent_code where `btp_sourcing != 'purchased_only'`
  (R3 mitigation). Recursive CTE for subtree extraction. Lineage
  links back. Idempotent via existing `create_raw_artifact`
  normalized_hash dedup.
- **`BomAdapter` Protocol** gains `post_ingest_hooks: list[str]`.
  Module-level `HOOKS` map identifier → callable. New
  `run_post_ingest_hooks()` invoker. Deep-tree adapters
  (sap_indented_walk, multi_sheet_per_root) declare
  `["derive_btp_shallows"]`; shallow adapters declare `[]`.
  Wire-up into upload-confirm flow deferred (BACKLOG).
- **Multi-role catalog badge** flags `btp_sx` materials that ALSO
  appear in `bcct_rows direction='export'` for the client. Surfaces
  rework/multi-role per `project_bom_code_multirole` memory. Live
  on Growatt: flags `PV01.0104300` exactly as expected.
- **Tests**: 14 new (8 derive + 6 hooks).

### 5. /rev fix bundle (`0de7292`)

Three Important findings caught by /rev of Phase 3 commits, plus
four Minor deferred to BACKLOG.

- **Auth gate mismatch on 6 write endpoints** — view-level instead
  of edit. Swapped to `*_can_edit_client` for: `api_create_preset`,
  `api_patch_preset`, `api_tombstone_preset`, `presets_create`,
  `presets_tombstone`, `set_btp_sourcing`. Real security finding;
  view-only users could mutate state.
- **UniqueViolation translation** — `api_create_preset` had a
  TOCTOU race; `api_patch_preset` skipped name uniqueness check
  entirely; both raised 500 on collision instead of 409. Both wrap
  the INSERT/UPDATE in `try/except psycopg_errors.UniqueViolation
  → 409`. Pre-check in create dropped (redundant).
- **Resolver `shape` filter tie-break** — docstring promised
  "tie-break on variant order (latest published first)" but step 3
  fell through to step 4 dual_source_variants 409. Now picks
  `items[0]` directly (already ordered by `published_at desc`),
  trail notes `(tie-break: 1 of N variants)`. Step 4 default-only.
- **Test added**: `test_shape_filter_tie_breaks_when_multiple_variants`.

### 6. Push + sister-app commits

- 4 commits pushed to origin (`a2840cb..0de7292`). Earlier rename
  pass (`edfa224..a2840cb`) was already pushed. CI/CD picks up.
- Sister-app notes committed in CO (`ddb9c46`) + BCQT (`7732f2b`),
  unpushed (user said "let CO/BCQT projects handle later").

## Decisions Made

### Vocab rename brief (D1-D10, all locked 2026-05-07)
- **D1** atomic mig 031 in single transaction — RENAME is metadata-only.
- **D2** two commits per pass — code-matches-schema commit + docs.
- **D3** forward-only ID prefix `ba_*` — `bv_*` rows survive.
- **D6** don't rename feature folder — date-stamped historical artifact.
- **D7** don't squash old migs — preserves provenance.
- **D8** `ba_` / `bp_` prefixes for new artifact / preset rows.
- **D9** hardcoded one-release alias grace, no feature flag.
- **D10** **308** Permanent Redirect (preserves POST method) for
  URL aliases, not 301.

### Phase 3 brief D1-D7 (locked earlier session, executed today)
- **D1** Resolver lives in `stores/bom.py` extending — not new module.
- **D2** Resolver returns provenance trail, not just artifact_id.
- **D3** `derive_btp_shallows` runs at ingest, not query time.
- **D5** Tombstoned presets remain queryable (audit reproduction).
- **D7** Don't add `bom_shape` column — `bom_shape()` helper derives.

### New decisions this session
- **API response outer key option (a)**: rename `{"version": …}`
  to `{"artifact": …}` as a breaking change shipped in same release
  as URL alias period. CO migration note updated. Considered (b)
  keep-permanently and (c) dual-key alias; user chose (a) for
  cleaner long-term contract.
- **Phase 3c scoping**: brief estimated ~25h; 3c core delivered in
  ~4h because adapter registry already existed (5 adapters
  registered pre-3c). Deferred items captured in BACKLOG "Phase 3c
  follow-ups" — auto-trigger from upload, bom_variant_id form
  field, auto-materialize, auto-bootstrap, shape badge,
  multi-role-at-upload, Playwright E2E.
- **Wipe + ingest fresh** (clarified across three rounds): the
  planned post-Phase-3 reset is a one-shot pre-MVP wipe of all
  per-client data, not a re-ingest. BOM-immutable principle stays
  in place for steady-state ops; this is a precedent-free reset.

## What Didn't Work

- **First mig-031 draft missed `bcct_rows.bom_version_id`** —
  caught when test_read_api_auth.py started failing with
  `column "artifact_id" does not exist`. Added §9b to mig +
  ALTER inline locally. Lesson: scope-search every column with
  `version_id` substring before writing the migration, not just
  obvious BOM tables.
- **Resolver test fixtures didn't commit before invoking resolver**
  — `with connect()` opens a transaction; `resolve_bom_artifact`
  opens a separate connection that can't see uncommitted writes.
  Added explicit `conn.commit()` between fixture inserts and
  resolver calls. Pattern documented for future tests that mix
  fixture writes with separate-connection queries.
- **`BomAdapter` Protocol couldn't grow `post_ingest_hooks` field
  cleanly** — Protocol with attribute fields means each adapter
  class must declare. Workaround: declare in Protocol +
  `_set_hooks(name, hooks)` setattr at registry init time.
  Avoided 5 boilerplate adapter edits. Functional but slightly
  hacky; revisit if hooks contract grows.
- **Resolver shape filter behavior contradicted docstring** —
  caught in /rev. Initial implementation fell through to step 4
  default branch which raised 409. Docstring intent (tie-break to
  latest) only realized after rev. Lesson: when /rev finds a
  docstring↔code mismatch, fix the *code* to match documented
  intent unless the documented intent is actually wrong.
- **Generic `exception when others then null` in mig 031 GRANT
  block** — flagged in /rev, tightened. The `pg_roles` filter
  already handles missing roles (loop iterates empty); catch-all
  was over-defensive and would silence real bugs.

## Open Items

### Hard pending
1. **Wipe + ingest fresh — Growatt and Johnson** *(user signal
   when ready)*. Procedure documented in memory
   `project_reingest_pending.md` and STATUS Next Steps #1.
2. **Demo data parity** — apply mig 031 + Phase 3 code to tinsu;
   run wipe + ingest fresh there too OR pg_dump local → restore
   tinsu.

### Soft / deferred
3. **Phase 3c follow-ups** (BACKLOG) — auto-trigger hooks from
   upload, `bom_variant_id` form, auto-materialize, auto-bootstrap
   roster, shape badge in preview, multi-role-at-upload,
   Playwright E2E. ~10h.
4. **Phase 3 review-deferred minors** (BACKLOG) — catalog↔classifier
   matching column inconsistency, preset name validation, PATCH
   `updated_at`, `derive_btp_shallows` `created` flag.
5. **Restore `bom_proposal_mode='auto'`** for both clients after
   wipe + ingest fresh.

### Sister-app coordination
6. CO `barry-CO-main` has 2 unpushed commits (`ddb9c46` rename
   note + the newer 3b note). User said "let projects handle
   later".
7. BCQT `BCQT-System` `dev` has 1 unpushed commit (`7732f2b`).
   Same.

## Files Changed (cumulative across 7 commits)

Counts approximate per `git diff --stat`:
- 23 files Phase 3 (a + b + c + fix), +2552 / -53.
- 50+ files rename pass, +915 / -547.
- 7 files docs/AI artifacts, +809 / -104.

Highlights:
- `db/migrations/031_rename_bom_to_artifact_and_preset.sql` (new)
- `app/stores/bom.py` — `bom_shape()`, `resolve_bom_artifact()`,
  `ResolverError`, function renames, ID prefix.
- `app/routes/api.py` — resolver wiring + preset CRUD endpoints +
  `_raise_resolver_http` helper.
- `app/routes/bom.py` — UI presets routes, alias 308 routes,
  `_alias_artifact_detail`, `_alias_artifacts_list`.
- `app/routes/catalog.py` — `set_btp_sourcing` endpoint,
  `btp_sourcing` SELECT col, `is_multi_role` flag.
- `app/templates/clients/bom_artifact_detail.html` (renamed),
  `bom_artifacts.html` (renamed), `bom_presets.html` (new).
- `scripts/detect_dual_source_btps.py` (new),
  `scripts/derive_btp_shallows.py` (new),
  `scripts/materialize_shallow_and_full_flat.py` (SQL update).
- `app/parsers/bom_adapters/__init__.py` — `post_ingest_hooks`
  Protocol field + HOOKS map + `run_post_ingest_hooks` runner.
- 7 new test files (vocab rename + classifier + override +
  materializer + resolver + CRUD + endpoint + derive + hooks +
  tie-break).
