# Session 2026-05-05 — BOM v3 redesign, wipe+re-ingest local DB

## What was done

### Investigation phase
- Audited why `SD00.0010600` and `SA00.0004000` had v1=130 rows vs
  v2=484/433 edges. Conclusion: v1 (`manual_flat` agency_upload) =
  v2 (`technical_raw`) rolled up to BTP boundary. 32/41 Growatt
  product pairs match 100% under that rollup.
- Memory updated: `project_growatt_bom_v1_v2_equivalence.md`,
  `reference_dev_db_topology.md` (two independent DBs on dev box —
  native local socket vs docker compose).
- Locked principle in memory: `project_bom_immutable_principle.md`
  — never DELETE BOM rows; edit = new version; tombstone allowed.
- Added backlog item: aggregate-data git-history (audit trails for
  materials, code_mappings, client_config, parser_mappings, etc.).

### Design v3 (3 critic rounds)
Adopted **A1 + A3 from critic round 1**:
- **A3 (3 BOM shapes)**: `raw_graph` / `shallow` / `full_flat` —
  encapsulate sub-BTPs in their own per-BTP BOMs, recursive resolve
  per-BTP (k stays small per BOM, no exponential blowup).
- **A1 (resolution profiles)**: `bom_resolution_profiles` table.
  CO/BCQT certs reference `(version_id, profile_id)` not per-cert
  cloned versions. Cardinality grows with strategy reuse, not
  shipment count.

Decision (per critic round 2): **don't drop `flatten_status` +
`flatten_strategy`** (170 refs across 19 files = too risky). 3-shape
concept lives as Python helper deriving from existing columns.

Decision (per critic round 3): **wipe + re-ingest** instead of
backfill. Pre-production, no customer data, source XLSX files all
present.

### Schema
- `db/migrations/030_btp_sourcing_and_resolution_profiles.sql`:
  - `materials.btp_sourcing` enum (nullable)
  - `clients.auto_derive_shallow_from_raw` enum (default `draft_only`)
  - `bom_resolution_profiles` table (Phase 4 use)
- `app/stores/bom.py:bom_shape(flatten_status, flatten_strategy)`
  helper returning `Literal['raw_graph','shallow','full_flat']`.
- `app/data_promotion.py`: add `bom_resolution_profiles` to TABLES.

### Scripts (new)
- `scripts/dry_parse_supplier_xlsx.py` — pre-flight hash compare
  (139/139 parsed, 119 hash-match, 2 mismatch due to parser
  improvements between trial 2026-05-04 and HEAD, 18 no_db_match
  for never-ingested batches).
- `scripts/setup_clients_for_reingest.py` — creates 5 client rows
  with `bom_proposal_mode='manual'` (per critic R3 finding 2:
  auto-rule rejects re-ingests).
- `scripts/ingest_technical_raw_batch.py` (~280 LoC) — bulk-ingest
  raw XLSX with `--dry-run`, `--resume-from`, JSON log per file,
  summary, distinct `bom_variant_id` per batch.
- `scripts/ingest_curated_xlsx_direct.py` — direct catalog/BQD/BCCT/
  manual_flat ingest (bypasses unified-mapping-flow UI gate that
  smoke_real_uploads cannot drive).
- `scripts/bootstrap_btp_roster.py` (refined from earlier session).
- `scripts/bootstrap_catalog_from_bcct.py` — fills NVL/TP gaps in
  `materials` from `bcct_rows`, classifies based on direction +
  has-own-bom signal.
- `scripts/verify_btp_rollup.py` (from earlier session).

### Phase A cutover (executed, ~5 min downtime)
1. `pg_dump` local + docker DBs to `/tmp/data_hub_pre_v3/`
2. `dropdb data_hub` (sudo via postgres user — `vp` lacks CREATEDB)
3. `createdb -O vp data_hub`
4. `apply_migrations()` — 29 migrations applied including 030
5. Master data seed + admin user
6. `setup_clients_for_reingest.py` — 5 clients ready

### Phase B re-ingest (executed)
1. **4 raw batches** via `ingest_technical_raw_batch.py`:
   - Growatt root: 14 versions → `agency_2026-01-root`
   - Growatt supplemental: 39 versions → `agency_2026-01-supplemental`
   - Growatt 20260423: 4 versions → `agency_2026-04-23`
   - Johnson 20260423: 82 versions → `agency_2026-04-23`
   - Total 139 versions, 47,098 edges
2. **Curated XLSX direct** via `ingest_curated_xlsx_direct.py`:
   - Growatt: 4 catalog rows + 2,892 BQD + 3,182 BCCT + 285
     manual_flat versions (across 207 product codes)
   - DKE: 242 BQD
3. **Bootstrap scripts**:
   - `bootstrap_btp_roster.py --client growatt-vn --commit`:
     148 BTPs added
   - `bootstrap_catalog_from_bcct.py --client growatt-vn --commit`:
     294 inserts (276 nvl + 18 tp from BCCT) + 4 provenance merges

### Final state (local DB)
- 5 production clients + 2 test fixtures
- 446 materials: 278 nvl + 148 btp_sx + 20 tp
- 285 manual_flat + 139 technical_raw BOMs
- 47,098 edges, 3,182 BCCT rows, 3,134 code_mappings
- `bom_resolution_profiles` table exists, empty (awaits Phase 3+4)

## Decisions made

- **Don't drop existing flatten_status / flatten_strategy columns.**
  170 refs across 19 files; risk > value for pre-MVP. 3-shape concept
  is Python helper.
- **Wipe + re-ingest instead of backfill.** Pre-production, all
  source XLSX files available, fewer subtle migration bugs.
- **`bom_variant_id` per batch.** Each Growatt sub-batch (root,
  supplemental, 20260423) gets distinct variant — ordering trap
  avoided per critic R3 #11.
- **`bom_proposal_mode='manual'` for re-ingest window.** Auto-rule
  would reject re-ingest with qty drift > 5%; manual mode bypasses.
  Flip back to `auto` post-Phase-B per agency preference.
- **`auto_derive_shallow_from_raw='draft_only'` default.** Phase 2
  auto-derive (deferred) will not silently publish system-authored
  BOMs as canonical.
- **Direct-ingest, not Playwright UI.** smoke_real_uploads.py
  blocked by unified-mapping-flow that needs UI confirm steps;
  direct calls to parser + store-level inserters bypass it.
- **`migration 030` adds 3 things only** (`btp_sourcing`,
  `auto_derive_shallow_from_raw`, `bom_resolution_profiles`).
  Doesn't touch `bom_shape`, `flatten_status`, `flatten_strategy`.

## What didn't work

- **smoke_real_uploads.py** uploaded files but they all sat in
  `parse_status='mapping_pending'` — the unified-mapping-flow
  introduced in commit `b278ff5` requires UI confirm steps that
  Playwright in smoke does NOT drive. Pivoted to direct ingest.
- **Local user `vp` lacks `CREATEDB`** privilege — had to `sudo -u
  postgres createdb`. Documented in re-ingest recipe.
- **2 BOMs failed manual_flat ingest** with `qty_per_unit <= 0`
  validation: `B700.0087101-1`, `B700.0236502-1`. Source workbook
  has rows with qty=0; pre-existing data quality issue, not
  introduced by re-ingest.
- **1 test failure** post-re-ingest:
  `tests/test_co_columns.py::test_backfill_populates_typed_co_columns_from_payload`
  — depends on `dke-vietnam-d0e3` BCCT data we didn't re-ingest
  (only re-ingested DKE BQD). Real-data-dependent; should be
  marked accordingly. NOT introduced by code changes.
- **SD00.0010600 verify_btp_rollup goes to MISMATCH** (was OK
  before re-ingest) — newer 20260423 batch's SD differs from
  agency manual_flat by 6 codes. This is the right behavior:
  flag for staff reconcile when newer factory data deviates from
  agency-attested BOM.
- **Demo at ttdatahub.tinsu.ai NOT redeployed.** Still on old
  schema. Local re-ingest verified; remote redeploy is task 18
  deferred to next session (60-90 min downtime; needs announcement).

## Open items

1. **Demo redeploy to tinsu** — task 18. Steps in task description.
2. **Phase 3** — resolver + profiles + `intent='sourcing_choice'`
   + new auto-rule. Estimated 25-35h per critic R3, separate
   sprint.
3. **`detect_dual_source_btps.py` script** — set
   `materials.btp_sourcing='dual_source'` for codes that are both
   BTPs AND appear in BCCT imports. Was deferred during Phase B.
4. **Restore `bom_proposal_mode='auto'` for Growatt** if desired
   — currently `manual` from re-ingest setup.
5. **`feed_demo_company.py`** — deprecated per STATUS.md but the
   demo-precision-manufactu-480e client is empty. Either re-run
   that script to populate, or drop the client.
6. **9-product mismatch reconciliation** — even after re-ingest
   with newer batches, some products show divergence between
   agency manual_flat and factory technical_raw rollup. Owner:
   agency / business analyst, not engineering.
7. **Restore data_promotion smoke for `bom_resolution_profiles`**:
   confirm export-import roundtrip handles the new client-scoped
   table correctly (data_promotion.py was updated; need an
   integration smoke).
8. **`tests/test_co_columns.py` real-data marker** — gate the
   failing test behind the `DATA_HUB_REAL_DATA_DIR` env, not the
   regular suite.

## Files changed

- `db/migrations/030_btp_sourcing_and_resolution_profiles.sql` (new)
- `app/stores/bom.py` — `bom_shape()` helper added
- `app/data_promotion.py` — `bom_resolution_profiles` in TABLES
- `scripts/setup_clients_for_reingest.py` (new)
- `scripts/dry_parse_supplier_xlsx.py` (new)
- `scripts/ingest_technical_raw_batch.py` (new)
- `scripts/ingest_curated_xlsx_direct.py` (new)
- `scripts/bootstrap_catalog_from_bcct.py` (new)
- (`scripts/bootstrap_btp_roster.py` from prior session, used here)
- (`scripts/verify_btp_rollup.py` from prior session, used here)

Backlog updated:
- `.ai/BACKLOG.md` — added "Aggregate-data git-history" item.

Memory updated:
- `project_growatt_bom_v1_v2_equivalence.md` (post-bootstrap state)
- `project_bom_immutable_principle.md` (new)
- `reference_dev_db_topology.md` (new)
