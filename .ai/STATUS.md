# Project Status

**Date:** 2026-06-14 (later PM) — **NXT year-keyed period + browsable detail
views + Catalog cross-link** built on top of v0.16.0. Branch
`feat/nxt-period-year-detail-views` (`6385ec2`), **PR #9 open against `main` (not
merged yet)**. Prior: v0.16.0 shipped earlier same day (PR #8, tag `v0.16.0`,
prod `https://ttdatahub.tinsu.ai`, mig 082–086 applied at boot).

## Current State

**PR #9 OPEN (awaiting merge)** — follow-up to the NXT/inventory tier:
1. **NXT keyed by settlement year** — `period_year` (mig 087), required on upload,
   supersede key `(client_id, period_year)`; `period_from/to` default to the
   calendar year so date-keyed `period_end_link` (BCQT) still matches year-only
   uploads. Inventory `snapshot_date` now required.
2. **Browse-detail views** — `GET …/nxt/{id}` + `…/inventory-snapshots/{id}`:
   paginated line tables, derived closing_implied/variance with mismatch
   highlight, clickable list rows, `Năm` column on the NXT list.
3. **Cross-link** — line mã → `/catalog/{code}/detail` when it resolves in
   `hub.materials` (`.xlink` affordance). Real ingested codes mostly DON'T resolve
   yet (I2 lossy join) — links fire only for resolvable codes; demo client used
   for the live screenshots (09/10).
`/v1/hub` nxt gains `period_year` (additive). `/rev` done: fixed the
`period_end_link`-vs-year gap (Important) + customs_code mislink (Minor).
**Full suite 1531 passed, 16 skipped.** Session summary:
`.ai/sessions/2026-06-14-nxt-period-year-detail-crosslink.md`.

**Prior — v0.16.0 SHIPPED** via PR #8: NXT (Nhập-Xuất-Tồn) + year-end inventory
snapshot (chốt tồn kho) data tier — parse/store/read; BCQT computes Mẫu 15/15a.
Brief: `.ai/features/2026-06-14-nxt-inventory-tier/`.

**What's in it (slices 1–4):**
- **Schema** (mig 082–086): `nxt_artifacts/nxt_lines` + `inventory_snapshots/
  inventory_snapshot_lines`, immutable (edit = new artifact; **supersede prior**
  per `(client, period_to)` / `(client, snapshot_date)`); `outbound_total`;
  `default_nxt/inventory_adapter` bindings; widened `chk_module` +
  `parser_mappings.module`. All additive/DDL-only, no client seed.
- **7 modular adapters** (clone of BOM registry: Protocol + detect-ranked
  fallback; each layout adapter gates parse on a distinctive signal so it never
  grabs a generic file). NXT: `ezsoft_3tsoft`, `sap_mb5b`, `misa_can_doi_ton`,
  `system_template`, `manual_generic`. Inventory: `kiem_ke_multi_kho`,
  `system_template`. Validated on real files (Growatt 2936 / Johnson MB5B 20064 /
  Hồng Phúc MISA 123 / DKE stocktake 727 across 6 kho).
- **Web-UI adapter mgmt** — admin registry `/admin/settlement-adapters` +
  per-client default-adapter binding (respects B.0: no runtime code upload).
- **Smart ingest** — alias auto-match → interactive column-mapping page (rigid +
  LLM suggest + confirm → `parser_mappings` cache). Unknown format = 0 code.
- **System-standard templates** (`/templates/nxt.xlsx`,
  `/templates/inventory-snapshot.xlsx`) — render == parse.
- **Upload→preview→confirm UI** both modules + "Quyết toán" nav group. Derived
  `closing_implied`/`variance` shown, never stored. `reported_role` = provenance
  only (authoritative class from catalog).
- **Read API `/v1/hub`** (additive — `docs/API_CHANGELOG.md` 2026-06-14):
  list/get NXT, list/get inventory snapshots, `period-end-link?date=` (per-code
  NXT closing ↔ next-period opening ↔ snapshot book/physical, best-effort code
  join). `data_promotion` exports the 4 tables.

**Review (3-agent + self-verify) done; fixes in PR:** Critical re-upload
double-count → supersede-on-confirm + `mapping_parse` guard; Important
`preview_reject` now client-scoped; Minor override dup-target → first-wins;
best-effort join documented. **Tests: 30 in-feature + full suite 1524 passed.**

Working tree: branch `feat/nxt-inventory-tier` (pushed). Pre-existing `uv.lock`
modification still uncommitted (NOT this session). Dev server restarted on :8754
this session (`--workers 1 --reload`).

## Next Steps

1. **Merge PR #9** (`feat/nxt-period-year-detail-views`). On merge (CD = prod
   deploy, mig 087 applies at boot): bump `CHANGELOG.md` (VN) + `pyproject` + tag
   + `gh release create`. Then confirm `/healthz` + `/version`.
2. **I2 code-join resolver** — real NXT/inventory codes don't match catalog
   `material_code` (e.g. `001.002` vs `001.0001100`), so cross-links +
   `period_end_link` don't fire on real data. Resolve both sides through
   `code_mappings`/catalog to a canonical code; optionally make `period_end_link`
   year-aware directly (now coherent via the Dec-31 default).
3. **Cross-link BCQT-System** to consume the `/v1/hub` read API (NXT, inventory,
   period-end-link; settlement reconciliation lives in BCQT). Write a sister note.
4. **UoM review P4 (CO side, deferred)** — guard CO stock allocation against UoM
   mismatch. Spec: `.ai/sister-app-notes/2026-06-14-co-allocation-unit-match-guard.md`.
   Apply on a clean CO branch after `barry-CO-main` `feat/rd3-bangke-split` lands.
5. **Declarability rollout** (open since v0.14.0) — mig 078–081 live on prod,
   `exclude_non_declarable` default-OFF. Decide prod backfill
   (`backfill_johnson_material_group.py --apply`), then CO adoption, then flip
   the flag for johnson-vn.
6. **Outage ops follow-up** — after ~**20/06** confirm pre-fix appfiles tars
   pruned via GFS (`~/logs/verify-old-tars.log` self-removes when clean).
7. **Backlog, unblocked:** B.0b rename `material_group` → `item_type_token`;
   A.0 RD07 drawing name-level auto-hide; B.0 item 3 (mandatory `detect()` +
   capability metadata). NXT-tier deferred minors (in feature brief): broad
   `except` in `parse_with_fallback`; mapping_parse 3× workbook load;
   outbound≠Σbucket preview warning; MISA column-order fragility.

## Notes for Next AI Session

- **CD = prod deploy.** Any push to `main` redeploys prod + applies pending
  migrations at boot. Every merge is a prod release — update `CHANGELOG.md`
  (+ `API_CHANGELOG.md` if `/v1/hub` changed), bump `pyproject` + tag + release.
- **STATUS/BACKLOG lag HEAD** — trust `git log` + code over the docs.
- **Branch flow:** `main` uses merge commits; `delete_branch_on_merge` off
  (delete branch manually after merge). One repo dir = dev server shows only the
  checked-out branch; prefer fewer switches while the user reviews live.
- **NXT supersede semantics (post-PR #9):** keyed by **`period_year`** — one
  consolidated NXT per client per year; a re-upload for the same year supersedes
  the prior. `period_from/to` default to the calendar year. Model does NOT support
  piecewise per-class or sub-annual uploads of the same year.
- **Cross-link is best-effort:** NXT/inventory mã links to Catalog only when the
  code is in `hub.materials`. Real ingested codes mostly DON'T match catalog
  `material_code` yet (I2 lossy join) — needs a `code_mappings`/catalog resolver.
- **Dev DB has no NXT/inventory data** (cleaned this session — was all test/smoke
  junk; real NXT lives in the BCQT repos, not data-hub). Re-seed to demo: see
  `.ai/sessions/2026-06-14-nxt-period-year-detail-crosslink.md` (demo client used
  real Growatt codes so cross-links resolve).
- **Adapter pattern:** layout-specific adapters MUST gate `parse()` on the same
  distinctive signal as `detect()` (title/sheet/Chinese marker), else they
  greedily claim generic files (this bit ezsoft, misa, kiem_ke during the build).
- **Screenshots:** two-tier rule — committed proof → `.ai/features/<slug>/
  screenshots/`; scratch → gitignored `data/screenshots/`. Never mix.
- **uv.lock** shows modified but is pre-existing — don't commit without reason.
- **Migration gotcha:** client-specific seed FK→`hub.clients` must be guarded
  `where exists (select 1 from hub.clients …)`.
