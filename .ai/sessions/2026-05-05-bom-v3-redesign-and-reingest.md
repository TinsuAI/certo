# Session 2026-05-05 — BOM v3 redesign + multi-client re-ingest + push

Single long session. Started as an investigation question ("why does
Growatt SD00.0010600 v1 have 130 rows but v2 has 484?") and ended
with a full v3 BOM-handling architecture deployed to demo via CI/CD.

## What Was Done

### 1. Investigation phase

Audited Growatt SD/SA: discovered that v1 (`manual_flat`,
agency_upload) is the **level-1 cross-section of v2** (`technical_raw`,
factory_export). Verified: 32/41 (manual_flat, technical_raw)
Growatt pairs match perfectly when v2 is rolled up to BTP boundary.

### 2. Design v3 (3 critic rounds + 1 code-review round)

Adopted **A1 + A3 from the critic**:
- **A3** — 3 BOM shapes (raw_graph / shallow / full_flat) with
  per-BTP BOMs encapsulating sub-trees (k stays small, no
  exponential blowup).
- **A1** — `bom_resolution_profiles` table; CO/BCQT certs reference
  `(version_id, profile_id)` instead of cloned per-cert versions.

Round 2: don't drop `flatten_status` + `flatten_strategy` (170 refs).
Use a Python helper `bom_shape()` deriving the 3-shape concept.

Round 3: wipe + re-ingest instead of in-place backfill (pre-MVP =
no customer data to preserve).

Round 4 (code review): 3 fixes shipped — tp_roots correctness,
first_seen preservation, demote-published guard.

### 3. Schema (migration 030)

- `materials.btp_sourcing` enum (nullable; `purchased_only` /
  `self_produced_only` / `dual_source` / `unknown`).
- `clients.auto_derive_shallow_from_raw` enum (default `draft_only`).
- `bom_resolution_profiles` table (Phase 4 schema; not yet used).

### 4. Scripts (8 new + 1 fix)

- `setup_clients_for_reingest.py` — 5 client rows, manual proposal mode.
- `dry_parse_supplier_xlsx.py` — pre-flight hash compare.
- `ingest_technical_raw_batch.py` — bulk-ingest raw XLSX with
  --dry-run, --resume-from, JSON log per file.
- `ingest_curated_xlsx_direct.py` — direct catalog/BQD/BCCT/manual_flat
  ingest, bypasses unified-mapping-flow UI gate.
- `bootstrap_btp_roster.py` — BTP detection. Rule evolved over 3
  rounds (own_bom + consumed → parent anywhere → parent + never
  consumed elsewhere as TP-root exclusion).
- `bootstrap_catalog_from_bcct.py` — fill NVL/TP gaps from BCCT,
  preserves `first_seen` across re-runs (post round-4 fix).
- `materialize_shallow_and_full_flat.py` — derives 3-shape derivatives
  with cycle-safe recursive CTE; demote-published guard (post round-4).
- `verify_btp_rollup.py` — equivalence check between manual_flat and
  raw rollup.

### 5. Phase A cutover (~5 min downtime, local only)

`pg_dump` backups → `dropdb && createdb` (sudo) → migrations →
seed master + admin → `setup_clients_for_reingest.py` → 5 empty
clients ready.

### 6. Phase B re-ingest

**Growatt** (5 batches):
- root: 14 TPs (variant `agency_2026-01-root`)
- supplemental: 39 TPs initially, then deduped 8 (variant
  `agency_2026-01-supplemental`, 31 alive after dedup)
- 20260423: 4 TPs (variant `agency_2026-04-23`)
- BTP files (drive-download/2025 半成品 BOM - BTP/): 137 BTPs
  (variant `agency_2026-04-23-btp`)
- TP additional (drive-download/2025年成品BOM/): 6 TPs (variant
  `agency_2026-04-23-tp-additional`)
- Rescued: 14 TPs/BTPs cloned from tombstoned GOM BOM rows
  (variant `agency_rescued_only_gom`) before physical DELETE.

**Johnson** (1 batch):
- 82 TPs from supplier (variant `agency_2026-04-23`).
- BCCT: 52,224 rows (T4/2025 → T3/2026, 12 months continuous).

**BCCT for Growatt**: full year 2025 + T3-T4/2026 = 23,080 rows.
T1-T2/2026 missing (no source file in workspace).

### 7. Cleanup phase (pre-MVP exception to BOM immutability)

User explicitly authorized physical DELETE of 309 tombstoned
`bom_versions` (285 GOM BOM + 24 supplemental dups), cascading
27,637 child rows + 4,050 edges. Memory updated to scope this as
pre-MVP seed-prep only — rule re-engages once first real cert
references any version_id.

### 8. BTP rule fix (Johnson-shape)

Original rule (`has_own_bom AND consumed_as_child`) detected 0 BTPs
for Johnson because Johnson supplier dumps full multi-level trees
in one workbook per TP — intermediate parents have no own
`bom_versions` row.

New rule (round 4 fix): "code that appears as parent_code AND has
own_bom but is never consumed elsewhere" = TP root. Anything else
that appears as parent = BTP. Result:
- Growatt: 153 BTPs (148 from old rule + 5 from intermediate
  parents the old rule missed).
- Johnson: 2,427 BTPs (was 0).

### 9. UI provenance

- `bom_versions.html` (list) — added variant + shape + source columns.
- `bom_version_detail.html` (single version) — added Provenance
  panel showing actor / intent / shape / source file / source batch
  / parser adapter / created_at / tombstone metadata.
- `list_versions_for_product` query updated to fetch new fields.

### 10. Multi-role insight (recorded in memory)

Discovered during code review: a code can be TP **and** BTP
simultaneously (rework / cải chế). Growatt has 1 such code
(PV01.0104300), Johnson has 1 (1000305146). `materials.category`
single-value enum can't express multi-role; data graph is truth.
Saved to `project_bom_code_multirole.md` for Phase 3 design.

### 11. Push + deploy

5 commits pushed to `origin/main`:
- d2899f1 feat(bom): v3 3-shape model + supplier-batch ingest
- 11409c3 fix(bom): BTP detection covers Johnson-shape
- 6784762 fix(bom): tp_roots + first_seen + demote guard
- 8e77996 docs(backlog): UI BOM upload deferred to Phase 3
- (data-promotion commit was already on origin from prior session)

CI/CD success in 1m20s. Demo `ttdatahub.tinsu.ai` now has v3
schema + code (migration 030 applied automatically). **Data on
demo is still old** — re-ingest scripts not yet run there.

## Decisions Made

- **3-shape concept** maps onto existing flatten_status/strategy
  via Python helper, not a new column. Avoids 170-ref refactor.
- **Wipe + re-ingest** for pre-MVP, not backfill. Source XLSX
  files all available; backfill complexity not worth the risk.
- **`bom_variant_id` per supplier batch** — avoids the
  ordering-trap critique by giving each batch its own version_no
  sequence. Same product across batches = parallel variants, not
  conflicting versions.
- **`bom_proposal_mode='manual'` for the re-ingest window** —
  bypasses the auto-rule's 5% qty-tolerance which would silently
  reject re-ingests. Flip back to `auto` post-Phase-B per agency
  preference.
- **`auto_derive_shallow_from_raw='draft_only'` default** — safety
  rail so system-derived BOMs don't silently land as canonical.
  Override with `--force-publish` script flag.
- **Materialize shallow + full_flat AFTER BTP catalog populated**
  — stop_set depends on `materials.category`, so order matters.
  If BTPs aren't classified yet, "shallow" walks past them to
  true leaves (= same as full_flat). Re-materialize after BTP
  bootstrap.
- **Pre-MVP DELETE exception** to BOM-immutable rule — explicit,
  scoped, documented in memory. Re-engages at first real cert.
- **Don't update UI BOM upload route** in this session — defer to
  Phase 3 with resolver + profiles work to avoid two rounds of
  UI churn.

## What Didn't Work

- **`smoke_real_uploads.py`** — uploaded files but they all sat in
  `parse_status='mapping_pending'`. Unified-mapping-flow (commit
  `b278ff5`) requires UI confirm steps the smoke script doesn't
  drive. Pivoted to direct-ingest scripts.
- **First BTP rule** — `has_own_bom AND consumed_as_child` fits
  Growatt (where each B700.* has own factory file) but misses
  Johnson (intermediate parents in a single TP tree).
- **Round 1 of revised BTP rule** — TP root definition was too
  inclusive (any code with own bom_versions = TP root), excluded
  Growatt B700.* family that have own files AND are consumed.
  Caught by code-review critic. Fixed with "never consumed
  elsewhere" qualifier.
- **`createdb` permissions** — local user `vp` lacks CREATEDB
  privilege. Required `sudo -u postgres createdb -O vp data_hub`.
  Documented in re-ingest recipe.
- **2 BOM parses failed** during direct ingest with
  `qty_per_unit <= 0` validation: `B700.0087101-1`, `B700.0236502-1`.
  Pre-existing source-data quality issue.
- **PV01.0104500 + PV02.0229100** — dry-parse hash mismatch from
  trial 2026-05-04 ingest. Diagnosed as parser improvement (more
  edges captured by HEAD parser), not regression. Re-ingest produced
  more-complete data which is desired.
- **Initial `materialize` policy override** — flipped published →
  draft regardless of when version was created, risking BOM
  immutability violation. Round-4 fix: only demote rows created
  in last 60s and not referenced by any alive profile.

## Open Items

1. **Demo data sync** (highest priority for next session). Demo at
   `ttdatahub.tinsu.ai` has v3 schema+code but old data. To match
   local: scp `~/workspace/client/barry-CO-data/extracted/CO/`
   (~vài GB) to tinsu, install scripts, run pipeline. Or:
   `pg_dump` local + restore on tinsu (faster but skips audit
   chain on tinsu side).
2. **Phase 3 work** — resolver + profile CRUD + sourcing_choice
   intent + auto-rule + UI integration. ~25-35h per critic
   estimate. Should bundle UI BOM upload v3 wiring (BACKLOG
   "UI BOM upload — wire up v3 concepts").
3. **14 orphan BTPs Growatt** — codes with own raw_graph but no
   parent TP in current dataset. Documented as known limitation
   in `bootstrap_btp_roster.py`. Staff manually classify when TP
   context arrives.
4. **`detect_dual_source_btps.py` script** — was deferred during
   Phase B. Cross-join `materials.category='btp_sx'` × `bcct_rows.direction='import'`
   → set `btp_sourcing='dual_source'`. Small script.
5. **Restore `bom_proposal_mode='auto'` for Growatt** — currently
   `manual` from re-ingest. Decide based on whether agency wants
   auto-validation back on.
6. **Multi-role schema improvement** (Phase 3+). Replace
   `materials.category` enum with multi-value flags
   (`has_decomposable_bom`, `is_finished_product`,
   `is_consumed_in_bom`, `is_imported`). Per memory
   `project_bom_code_multirole.md`.
7. **`tests/test_co_columns.py::test_backfill_populates_typed_co_columns_from_payload`**
   is real-data dependent. Already deselected on CI. Should be
   marked with a `@pytest.mark.real_data` and skip-if-missing
   instead of hardcoded deselect.
8. **24 stale `mapping_pending` / `pending_preview` file_uploads**
   in local DB from old smoke runs. Cosmetic — won't hurt anything
   but staff seeing them in UI might be confused. Cleanup:
   `delete from hub.upload_pending` + `update file_uploads set
   parse_status='abandoned' where parse_status in
   ('mapping_pending','pending_preview','pending')`.
9. **Push `feed_demo_company.py` deprecation comment** — script
   still exists, used to seed `demo-precision-manufactu-480e`
   client which is currently empty after Phase A wipe. Either
   re-run or drop the client.
10. **24 BCCT BOM rows still on demo synthetic data**. After
    demo data sync (item 1), re-verify.

## Files Changed (cumulative across all session commits)

**Schema**:
- `db/migrations/030_btp_sourcing_and_resolution_profiles.sql` (new)

**Code**:
- `app/stores/bom.py` — `bom_shape()` helper, list_versions_for_product
  query expansion, get_version_with_rows tombstone_reason fetch.
- `app/data_promotion.py` — `bom_resolution_profiles` in TABLES.
- `app/templates/clients/bom_versions.html` — variant/shape/source
  columns.
- `app/templates/clients/bom_version_detail.html` — Provenance panel.

**Scripts** (all in `scripts/`):
- `setup_clients_for_reingest.py` (new)
- `dry_parse_supplier_xlsx.py` (new)
- `ingest_technical_raw_batch.py` (new)
- `ingest_curated_xlsx_direct.py` (new)
- `bootstrap_btp_roster.py` (rule rewritten across 3 rounds)
- `bootstrap_catalog_from_bcct.py` (new + first_seen fix)
- `materialize_shallow_and_full_flat.py` (new + demote guard)
- `verify_btp_rollup.py` (new)

**Docs**:
- `.ai/STATUS.md` (rewritten)
- `.ai/BACKLOG.md` (added "Aggregate-data git-history" + "UI BOM upload — wire up v3 concepts")
- `.ai/sessions/2026-05-05-bom-v3-redesign-and-reingest.md` (this file)
- `.ai/sessions/2026-05-05-data-promotion.md` (predecessor session, was untracked)

**Memory** (auto-memory, not git):
- `project_bom_immutable_principle.md` (new)
- `project_bom_code_multirole.md` (new)
- `reference_dev_db_topology.md` (new)
- `project_growatt_bom_v1_v2_equivalence.md` (updated)
