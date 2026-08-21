# Feature: BOM vocab rename pass — version → artifact, profile → preset

**Captured:** 2026-05-07
**Estimate:** 11-15h end-to-end
**Ships before:** Phase 3a (`.ai/features/2026-05-06-phase-3-resolver-profiles/`)
**Vocab source of truth:** `.ai/GLOSSARY.md` § "BOM model — canonical
vocabulary" (locked 2026-05-07 in `27a7889`).

## Goal

Bring DB schema + code identifiers in line with the canonical 4-tier
ontology (phiên bản / bản lưu / preset / shape × strategy) before
Phase 3 lands. Eliminate the cognitive tax of mapping
"version" (vague, overloaded) onto the precise artifact concept, and
"profile" onto the saved-interpretation concept. Surfaces every Phase 3
API/UI/code touchpoint in correct terms from day 1 — cheaper than
post-MVP rename when sister apps + customer integrations are wired.

## Scope

### In

1. **Migration 031** — `db/migrations/031_rename_bom_to_artifact_and_preset.sql`.
   Atomic rename of all DB objects in one transaction:

   | Object kind | Before | After |
   |---|---|---|
   | Table | `hub.bom_versions` | `hub.bom_artifacts` |
   | Table | `hub.bom_version_rows` | `hub.bom_artifact_rows` |
   | Table | `hub.bom_resolution_profiles` | `hub.bom_presets` |
   | Column (cross-table) | `version_id` | `artifact_id` |
   | Column | `bom_versions.version_no` | `bom_artifacts.artifact_no` |
   | Column | `parent_version_id` | `parent_artifact_id` |
   | Column | `bom_change_requests.materialized_version_id` | `materialized_artifact_id` |
   | Column | `bom_resolution_profiles.bom_version_id` | `bom_presets.artifact_id` |
   | Column | `bcct_rows.bom_version_id` (if exists) | `artifact_id` |
   | Index | `idx_bom_versions_*` | `idx_bom_artifacts_*` |
   | Index | `idx_bom_resolution_profiles_*` | `idx_bom_presets_*` |
   | Constraint | named with old prefix | renamed |
   | History table | `bom_versions_history` (if exists) | `bom_artifacts_history` |
   | Trigger | `*_bom_versions_*` | `*_bom_artifacts_*` |

   Postgres `ALTER TABLE RENAME` is metadata-only — fast even at scale.
   FK constraints auto-update referenced names. No data movement.

2. **Code grep-replace** — scoped passes per file kind. Approx blast
   radius (verified 2026-05-07):
   - 37 `.py` files (~370 refs) — stores, routes, parsers, scripts, tests
   - 5 `.html` templates (~30 refs) — Jinja vars
   - 10 `.sql` migrations (~30 refs) — past migrations 005, 006, 021,
     022, 027, 029, 030 mention old names; **DO NOT EDIT past
     migrations** — they're already-run history. Add comment in 031
     header explaining future readers must mentally translate.

   Replacement table (apply in order; later patterns subsume earlier):

   ```
   bom_resolution_profiles  →  bom_presets
   resolution_profiles      →  presets        (residual after above)
   bom_version_rows         →  bom_artifact_rows
   bom_versions             →  bom_artifacts
   parent_version_id        →  parent_artifact_id
   materialized_version_id  →  materialized_artifact_id
   bom_version_id           →  artifact_id
   version_no               →  artifact_no    (BOM context only — not generic)
   profile_id               →  preset_id
   profile_name             →  preset_name
   BomVersion (class)       →  BomArtifact
   BomResolutionProfile     →  BomPreset
   list_versions_for_*      →  list_artifacts_for_*
   get_version_*            →  get_artifact_* (BOM context only)
   ```

   **Manual review required for ambiguous matches:**
   - `version_id` appears in non-BOM contexts (e.g., `bom_proposal.proposal_version_id`,
     audit trail). Use word-boundary regex + per-file review.
   - `version_no` may collide with non-BOM versioning. Scope match to
     BOM-table contexts only.
   - `profile` collides with `python_profile`, `cProfile`, etc. Always
     pair with `bom_` or `preset_` context in regex.

3. **Template renames** — file names match new vocab:
   - `app/templates/clients/bom_versions.html` → `bom_artifacts.html`
   - `app/templates/clients/bom_version_detail.html` → `bom_artifact_detail.html`
   - `app/templates/clients/_bom_macros.html` — keep filename; update
     macro names internally (`shape_badge` stays; new helpers use
     artifact terminology).
   - Update `render_template(...)` calls + `url_for(...)` refs.
   - URL paths: `/clients/{c}/products/{p}/bom/versions` →
     `/clients/{c}/products/{p}/bom/artifacts`. Keep old path as 301
     redirect for one release (sister-app + bookmark grace period).

4. **API contract** — `docs/API_CONTRACT.md` rewrite for BOM section.
   Use new vocab in all examples. Add a "Migration note" section
   listing the rename mapping for sister-app readers.

5. **ID prefix policy** — **keep `bv_` for existing rows; new
   inserts use `ba_`**. Decision rationale:
   - Existing artifact IDs persisted in `bom_change_requests`,
     `bom_artifact_rows`, audit logs, sister-app bookmarks.
     Re-prefixing breaks those refs.
   - `bv_` and `ba_` coexist transparently — ID prefix is opaque to
     API consumers; only relational lookups by full ID matter.
   - Migration 031 updates the `default ... gen_random_*` expression
     for the table to mint `ba_*` going forward; existing rows
     untouched.
   - Same logic for `bp_*` (new preset rows) vs unchanged old IDs in
     mig 030 schema (no rows existed pre-rename — clean cut).

6. **Sister-app coordination notes:**
   - **CO** (`~/workspace/client/barry-CO-main`) — 28 Python refs to
     `bom_version_id` / `bom_versions`. Write
     `~/workspace/client/barry-CO-main/.ai/sister-app-notes/2026-05-07-bom-rename.md`
     listing the API/DB rename. CO consumes Hub via API; doesn't write
     to `hub.bom_artifacts` directly. API alias period (see #7) gives
     CO migration headroom.
   - **BCQT** (`~/workspace/client/BCQT-System`) — 0 refs (verified
     `grep` 2026-05-07). Pure read-only consumer; not yet wired to
     consume hub presets. Note still posted for awareness.
   - Both sister-app notes link back to this brief + `.ai/GLOSSARY.md`
     vocab section.

7. **API alias / dual-name release window** — for one release after
   31 ships:
   - `?profile_id=` accepted as alias for `?preset_id=` with
     `Deprecation` header.
   - `?version_id=` accepted as alias for `?artifact_id=` with
     `Deprecation` header.
   - `/bom/versions/{id}` 301 → `/bom/artifacts/{id}`.
   - Removal scheduled when CO + BCQT both confirm migration; tracked
     in BACKLOG.md "Drop BOM vocab v1 aliases".

8. **Memory / docs sweep:**
   - `.ai/STATUS.md` — update terminology in Current State + Next
     Steps after rename lands.
   - `.ai/DECISIONS.md` — record rename pass as a decision entry.
   - `.ai/BACKLOG.md` — entries that mention "version" / "profile"
     get rewritten.
   - Memory files (private to AI session, not committed) — `MEMORY.md`
     index entries reviewed; create new memory `feedback_bom_vocab.md`
     pinning the canonical terms so future AI sessions stop drifting.

### Out

- **Renaming `bom_variant_id`** — kept legacy per GLOSSARY decision.
  UI hides when `default`; column stays.
- **Touching past migrations** (005, 006, 021, 022, 027, 029, 030) —
  immutable history. Mig 031 header explains.
- **CO/BCQT code edits** — only sister-app notes. Their migration is
  tracked separately and gated on the alias-removal milestone.
- **Re-issuing existing artifact IDs** with new prefix — no rewrite
  of `bv_*` to `ba_*`. ID space is opaque.
- **External-facing renames** (e.g., customer-visible report column
  names) — defer until customer-facing UI is locked. None at MVP.

## Decisions

### D1. One migration file, atomic transaction.

Single mig 031 wraps all DDL in `BEGIN ... COMMIT`. If any rename
fails, the whole pass rolls back and we debug without partial state.
Postgres ALTER TABLE RENAME is fast even on the largest table here
(~600 rows in dev, < 50 rows on demo). No online-migration tooling
needed.

### D2. Two commits, not one.

- **Commit 1**: mig 031 + Python + templates + API contract + tests.
  Atomic from a "code matches schema" standpoint. Large diff
  (~52 files) — review burden, but splitting code from schema risks
  half-state on any partial-merge.
- **Commit 2**: docs/memory/sister-app notes. Smaller, low-risk.

### D3. ID-prefix change is forward-only (Option A).

`bv_*` rows survive untouched. `ba_*` minted for new artifacts.
Mixed prefix coexistence is the cheapest correct answer; full
backfill would break persisted external refs (CO has stored `bv_*`
in its case linkage). Same for `bp_*` (new presets — no historical
rows to worry about).

### D4. URL `/bom/versions` 301 redirect, not hard cut.

Bookmarks + sister-app dashboards may have hardcoded URLs. One
release of grace; redirect logged via `WARN` so we can confirm zero
hits before removing.

### D5. `version_no` → `artifact_no`, but keep `version_no` in non-BOM
tables (e.g., audit `*_history` row sequence numbers if any).

Scope grep-replace strictly to BOM-context columns. Generic
"version_no" patterns elsewhere (proposal versioning, future audit
sequences) keep their semantics.

### D6. Don't rename feature folder
`.ai/features/2026-05-06-phase-3-resolver-profiles/`.

Folder names are date-stamped historical artifacts. Folder rename
churns git history without value. Brief content already updated to
new vocab (in companion commit).

### D7. Don't squash migs 005–030 (locked 2026-05-07).

Keep history. One-time mental-translation cost when reading old migs
is mitigated by mig 031 header explaining the rename.

### D8. ID prefix `ba_` for new artifact rows, `bp_` for new presets
(locked 2026-05-07).

Two-letter convention matches `bv_` / `bc_` legacy. `art_` rejected
as inconsistent. See D3 for forward-only policy.

### D9. Hardcoded one-release alias grace; no feature flag
(locked 2026-05-07).

Removal tracked in BACKLOG.md "Drop BOM vocab v1 aliases". Feature
flag adds infra for a removal already planned and dated.

### D10. URL alias uses **308 Permanent Redirect**, not 301
(locked 2026-05-07).

308 preserves HTTP method (preset form POSTs would silently downgrade
to GET on 301). Cacheable like 301 in modern clients.

## Risks

### R1. Hidden `bom_version` references in dynamic SQL strings.

Some queries are built via f-string concatenation. Grep-replace
catches the literal substring; manual audit needed for any
`SELECT ... FROM {bom_table_var}`-style construction. Mitigation:
audit `app/stores/bom.py` line by line; same for any `app/parsers/bom/`
module that uses dynamic SQL.

### R2. Test fixtures may pin DDL or column names.

Some integration tests CREATE TABLE in a sandbox. Grep
`tests/conftest.py` + `tests/fixtures/` for `bom_versions` / DDL.
Mitigation: dedicated test pass after code grep-replace; full
`uv run pytest -q` must hit ≥219 pass / 15 skip baseline (current
HEAD numbers).

### R3. Audit-log replay breakage.

If `*_history` triggers reference column names by string literal,
they break post-rename. Postgres triggers usually use NEW.col / OLD.col
lvalue access (auto-updated by RENAME) but jsonb construction may
hardcode key names. Audit `db/migrations/030*.sql` triggers + any
`bom_*_history` views.

### R4. Sister-app live deploy timing.

If CO is mid-deploy when 031 lands, CO's running pod issues
`SELECT FROM bom_versions` and 500s. Mitigation: tinsu demo runs
single-node; coordinate restart window. CO 28-ref grep done on local
clone; check live tinsu CO repo HEAD before deploy.

### R5. Postgres role permissions on renamed objects.

Mig 031 must `GRANT` access to roles `data_hub_app`, `bcqt_app`,
`co_app` (or whatever's in `db/migrations/000_roles.sql`) on the
new names. Postgres carries grants over RENAME; verify with `\dp`
after migration. Add belt-and-suspenders explicit `GRANT ... ON
bom_artifacts TO ...` at end of mig 031.

### R6. Historical migration replay for new dev environments.

`uv run alembic upgrade head` (or whatever migrate tool) replays
mig 005 → 006 → ... → 030 (creating `bom_versions`) → 031 (renaming
to `bom_artifacts`). New devs spin up with renamed final state. OK,
no action needed — but **document** in `README.md` that names
diverge between historical migration files and current schema.

## Open Questions

All resolved 2026-05-07 — see D7-D10 above. No outstanding blockers.

## Manual test plan

After mig 031 + code rename:

1. **Schema sanity**: `psql -c "\d hub.bom_artifacts"` — confirms
   columns. `\d hub.bom_presets` — confirms preset table. Old names
   rejected with `relation "bom_versions" does not exist`.
2. **Test suite**: `uv run pytest -q` — must hit ≥219 pass / 15 skip
   (current baseline). `uv run pytest -k bom -q` — must hit current
   57 pass.
3. **UI smoke**: dev server up on 8754; visit
   `/clients/growatt-vn/products/SD00.0010600/bom/artifacts` —
   should render correctly. Old URL `/bom/versions` should 308 to
   new URL.
4. **API smoke**: `curl /v1/hub/products/SD00.0010600/bom?artifact_id=…`
   works; `?version_id=…` returns same payload + Deprecation header.
5. **Real-data smoke**: `DATA_HUB_REAL_DATA_DIR=… uv run pytest -q`
   — must not regress.
6. **CO sister-app smoke** (manual on tinsu staging): boot CO with
   pre-rename code against post-rename Data Hub; verify alias works.

After commit 1 lands: confirm zero `WARN` hits on alias endpoints
over a 24h window; if green, schedule alias removal in BACKLOG.md.

## Done criteria

- Migration 031 in `db/migrations/`, applied to local + tinsu demo.
- All Python + template + tests use new vocab; `grep -rn "bom_versions\|profile_id"`
  in source returns 0 (excluding past migrations + alias code paths).
- `docs/API_CONTRACT.md` rewritten with new vocab.
- Sister-app notes posted in CO + BCQT.
- `.ai/STATUS.md`, `.ai/DECISIONS.md`, `.ai/BACKLOG.md` use new
  vocab.
- Memory `feedback_bom_vocab.md` written for AI session pinning.
- Test count ≥ baseline (219/15 full, 57 BOM).
- `/rev` clean.
- Alias period documented in BACKLOG.md with removal milestone.

## Suggested next step

All open questions resolved (D7-D10 locked 2026-05-07). Ready for one
bundled `/tdd` pass:

1. Write mig 031.
2. Run mig on local; confirm schema.
3. Code grep-replace pass (Python first, then templates).
4. Tests green.
5. Docs + API contract.
6. Sister-app notes.
7. Commit 1 + Commit 2.
8. Push; CI green; deploy demo.

Estimated 11-15h single sprint. After it ships clean and CI is green,
return to Phase 3 brief and start `/tdd` for sub-phase 3a.
