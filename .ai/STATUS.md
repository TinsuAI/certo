# Project Status

**Date:** 2026-06-14 (PM) — **v0.16.0: NXT + year-end inventory data tier merged
to `main` + released** (PR #8). CD redeploys `https://ttdatahub.tinsu.ai` and
applies mig 082–086 at boot. Tag `v0.16.0`.

## Current State

**v0.16.0 SHIPPED** via **PR #8** (`feat/nxt-inventory-tier` → `main`, merge
commit; release commit bumps CHANGELOG + pyproject 0.15.0→0.16.0). New shared
data tier for two BCQT settlement *inputs* Data
Hub did not own: **NXT** (Nhập-Xuất-Tồn period flow) + **year-end inventory
snapshot** (chốt tồn kho). Data-tier only — parse/store/read; BCQT computes
Mẫu 15/15a. Brief + 8 screenshots: `.ai/features/2026-06-14-nxt-inventory-tier/`.

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

1. **Post-deploy verify (v0.16.0)** — confirm prod `/version` →
   `{"version":"0.16.0", git_sha=main HEAD}`, `/healthz`, both auth smoke gates,
   nightly refresh. Tag `v0.16.0` + `gh release create` on the merge commit.
2. **Cross-link BCQT-System** to consume the new `/v1/hub` read API (settlement
   reconciliation lives in BCQT, not here). Write a sister-app note.
3. **UoM review P4 (CO side, deferred)** — guard CO stock allocation against UoM
   mismatch. Spec: `.ai/sister-app-notes/2026-06-14-co-allocation-unit-match-guard.md`.
   Apply on a clean CO branch after `barry-CO-main` `feat/rd3-bangke-split` lands.
4. **Declarability rollout** (open since v0.14.0) — mig 078–081 live on prod,
   `exclude_non_declarable` default-OFF. Decide prod backfill
   (`backfill_johnson_material_group.py --apply`), then CO adoption, then flip
   the flag for johnson-vn.
5. **Outage ops follow-up** — after ~**20/06** confirm pre-fix appfiles tars
   pruned via GFS (`~/logs/verify-old-tars.log` self-removes when clean).
6. **Backlog, unblocked:** B.0b rename `material_group` → `item_type_token`;
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
- **NXT supersede semantics:** one period = one consolidated file (the real
  sources are). A re-upload supersedes the prior artifact for that period; the
  model does NOT support piecewise per-class uploads of the same period.
- **Adapter pattern:** layout-specific adapters MUST gate `parse()` on the same
  distinctive signal as `detect()` (title/sheet/Chinese marker), else they
  greedily claim generic files (this bit ezsoft, misa, kiem_ke during the build).
- **Screenshots:** two-tier rule — committed proof → `.ai/features/<slug>/
  screenshots/`; scratch → gitignored `data/screenshots/`. Never mix.
- **uv.lock** shows modified but is pre-existing — don't commit without reason.
- **Migration gotcha:** client-specific seed FK→`hub.clients` must be guarded
  `where exists (select 1 from hub.clients …)`.
