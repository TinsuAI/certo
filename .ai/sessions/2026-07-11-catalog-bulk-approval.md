# Session 2026-07-11 — Catalog phase 5: bulk approval (#35)

The final catalog phase. Shipped, reviewed, merged (PR #45, merge
`297f775`), and prod-deployed + verified in one session. This completes
the catalog discovery/approval rework (phases 0–5, issues #30/#32/#33/
#34/#35).

## What shipped

`/clients/{id}/catalog/candidates` becomes **discovery → rule → bulk
approve**. See PR #45 and the commit for specifics; highlights:

- **Filter-as-rule.** New signal filters on the discovery page:
  `leaf_in_flattened_bom` (checkbox), source chips (BCCT/BOM/BQD),
  `observed_count ≥`, machinery toggle. One button «Duyệt N mã đang
  lọc» approves every code matching the current filter, re-derived
  server-side (never a client-sent code list). Shows count + a code
  sample + confirm dialog.
- **Leaf signal keys on `bom_artifact_rows`, not `bom_role`** — the two
  coincide for Growatt only because its raw graphs are fully expanded.
  Verified: `flatten_status='flattened'` + `excluded_at is null` →
  exactly 2,157 codes; 2,156 after the one machinery code drops by the
  default filter.
- **Batched staleness (brief Risk 2).** mig 093 guards the D9 insert
  trigger with a `hub.bulk_load` session GUC (no-ops when `'on'`) and
  adds `hub.materials_propagate_bulk(client, codes)` — the set-based
  equivalent of both trigger arms, run once. Parity-tested against the
  per-row path.
- **One `catalog_bulk_accept` audit event** per action: predicate +
  count + code list, `decided_by`=operator, `product_code`=NULL.
- `excluded_non_material` filtered out by default; uncategorizable rows
  skipped (disclosed in toast).

## Files (see diff for detail — commit `20e7f83`)

- `db/migrations/093_catalog_bulk_accept.sql` (new)
- `app/stores/catalog_discovery.py` — `leaf_codes_in_flattened_bom`,
  `_is_leaf_in_flattened_bom`, `bulk_accept_codes`, `_bulk_automap`,
  `_derive_bulk_attrs`
- `app/routes/catalog_discovery.py` — `_filter_pending` (shared
  predicate), `_filter_kwargs`, `candidates_page` (+ source_counts,
  bulk_sample), `bulk_accept` POST
- `app/templates/clients/catalog_candidates.html` — filter/rule bar,
  bulk button + sample, source chips, `✓ lá phẳng` badge
- Tests: `tests/test_catalog_bulk_accept.py` (new),
  `tests/test_catalog_candidates_routes.py` (+bulk route tests, +audit
  cleanup in fixture)
- UI proof: `.ai/features/2026-07-10-catalog-candidates-merge/`
  `ui_smoke_phase5.py` + `screenshots/14,15,16*.png`
- `CHANGELOG.md` `[Unreleased]` (VN)

## Decisions made (beyond the issue text)

1. **Bulk-accepted materials get `status='active'`** (matches the
   existing script-accepted precedent), source-by-stream (`_source_for`),
   `category = suggested_category or 'nvl'` when the row is a flattened
   leaf (a leaf IS an nvl). Rows with no derivable category are skipped.
2. **Batching mechanism = namespaced GUC, not `DISABLE TRIGGER`.**
   `SET LOCAL hub.bulk_load='on'` works for a non-superuser and is
   pool-safe (txn-scoped, auto-resets on commit). `session_replication_
   role` was rejected — it needs superuser (denied on the app role).
   `DISABLE TRIGGER` would need ownership + an ACCESS EXCLUSIVE lock.
3. **Source filter is single-select chips, NOT multi-select `sources[]`.**
   The issue's `sources[]` shorthand implies multi; shipped single-select
   (the common "only BOM-observed" need). Multi-select deferred —
   **flagged in PR #45 for reviewer, not certified by the user.**

## What didn't work / gotchas (load-bearing for next agent)

- **The D9 trigger's live body is mig 071, not mig 058.** mig 069 and
  071 redefined `materials_propagate_on_insert` (adding the
  `has_drift_remaining` UoM-alignment narrowing + the `NEW.uom` empty
  early-return). My first mig 093 rebuilt the trigger from mig 058 and
  silently reverted 069/071 → broke `test_d9_aligned_catalog_insert_
  skips_flag`. **Any `create or replace` of a function must start from
  the LATEST prior definition.** mig 093's trigger body is now mig 071
  verbatim + the guard; `materials_propagate_bulk` mirrors the same
  `has_drift_remaining` logic.
- The parity test needs **cross-family UoMs** (leaf rows `EA`, material
  `KILO-GRAMMES`) to be non-vacuous — with aligned UoMs the mig-071
  trigger correctly skips, so aligned-UoM assertions prove nothing.
- The route-test fixture didn't clean `bom_audit_events`; exact-count
  assertions accumulated across runs. Added cleanup to the fixture.

## Verification

- Full suite **1610 passed / 16 skipped** (was 1591; +19).
- UI smoke on `:8754`: leaf-filtered button reads exactly `Duyệt 2156
  mã đang lọc`; real bulk-accept ran end-to-end on a disposable client
  (3 materials + 1 audit event), cleaned up. **growatt-vn left pristine**
  (pending still 3,306 — no bulk executed against it).
- Prod verified: `ttdatahub.tinsu.ai/version` → `git_sha=297f775`,
  healthz 200. mig 093 applied (boot `apply_migrations()` gate — a
  healthy boot on the new sha proves it ran).

## Open items

1. **#37 (user decision, ready-for-human):** dead materials in CO's
   BCCT identity payload (`bcct_material_identity.py:120-133`) — hide
   (apply #31 predicate) vs document-and-keep.
2. **Release cut 0.21.0:** CHANGELOG `[Unreleased]` now holds **5**
   entries (added bulk approval). Bump `pyproject.toml` + `uv.lock`.
3. **#35 follow-up:** source filter multi-select (`sources[]`) deferred
   — decide if wanted (PR #45 note).
4. Housekeeping (carried, unchanged): `docs/agency-staff-guide` branch
   PR-or-drop; `v0.19.0` tag absent; prod Postgres collation-version
   mismatch (maintenance window).
5. Remaining ready-for-agent backlog (unrelated to catalog): #23 B.5,
   #22 B.4, #21 B.2, #19 B.0b, #14–18 A.x, #26 C.2, #29 E.4.
