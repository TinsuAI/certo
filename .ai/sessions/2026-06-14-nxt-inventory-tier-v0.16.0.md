# Session — NXT (Nhập-Xuất-Tồn) + year-end inventory data tier → v0.16.0

**Date:** 2026-06-14 (PM)
**Outcome:** New shared data tier built (slices 1–4), reviewed, merged (PR #8),
released **v0.16.0**, deployed to prod (`https://ttdatahub.tinsu.ai`, git_sha
`02412d5`, /healthz 200, mig 082–086 applied at boot).
**Feature folder:** `.ai/features/2026-06-14-nxt-inventory-tier/` (brief + 8 screenshots + ui_smoke.py).

## What the user asked
1. Find the year-end **NXT** (Nhập-Xuất-Tồn) aggregate files + **year-end
   inventory closing** files in the provided data (and the BCQT projects).
2. Develop these data items in Data Hub with a **smart, flexible parser**.
Then, across the session: plan → build all 4 slices → review → release to prod.

## Discovery (where the data actually lives)
Neither shape exists in Data Hub. The `BaoCaoHangChiTiet NK/XK` files already in
`data/source_inventory/` are detailed *transaction* reports, not NXT summaries.
Real source files are in the per-agency BCQT repos:
- **NXT movement:** `bcqt-growatt/.../TongHopNXT.xls` + `Tổng hợp Nhập-Xuất-Tồn …(phan hoi).xlsx`
  (EZSOFT/3TSoft sheet); `BCQT-DKE/.../物料收发汇总表`; `audit-hq/data/raw/HONG_*/*/NXT_TON/`
  (MISA "CÂN ĐỐI TỒN KHO"); `Johnson/output/CLEAN_MB5B_DETAIL.xlsx` (SAP MB5B).
- **Year-end inventory:** `BCQT-DKE/input/Archived/3. Kiểm kê tồn kho…/Bảng kiểm kê kho VN cuối tháng 12.2025.xlsx`
  (multi-warehouse, book vs physical); `bcqt-dothanh/…/BCQT TON KHO 2025…`; audit-hq NXT_TON.
- Reference parser replaced (too rigid): `BCQT-System/app/parsers/ezsoft_nxt.py`.

## Decisions made
- **Scope:** Data Hub owns parse+store+read only; **BCQT computes Mẫu 15/15a** (consumer). (user)
- **Model:** two linked immutable entities — `nxt_artifacts/lines` + `inventory_snapshots/lines`. (user)
- **Coverage:** all clients via **modular, Web-UI-manageable adapters** (user's Q3 emphasis);
  adding a format = adapter via git/CI, **no runtime code upload** (B.0). Plus system templates. (user)
- **Classification is provenance, not authority:** `reported_role` (nvl|tp|btp|null) records the
  role the *source* declared a line under — kept ONLY because multi-role codes (cải chế) make the
  catalog's single category insufficient; authoritative class resolves from the catalog at runtime.
- **outbound modelling:** most ERP exports give a lumped Xuất → added `outbound_total` (mig 084);
  only Mẫu 15 / system template carry the 4-way split. `closing_implied` prefers outbound_total.
- **Layout adapters MUST gate parse on a distinctive signal** (title/sheet/Chinese marker) — not
  just "has these headers" — or they greedily claim generic files.
- **Re-upload semantics:** one period = one consolidated file → a re-upload **supersedes** the
  prior artifact for that `(client, period_to)` / `(client, snapshot_date)`.

## What was built (commits on `feat/nxt-inventory-tier`, merged via PR #8)
- `aeb9df0` **Slice 1** — schema (mig 082, 4 immutable tables), 2 adapter registries +
  `system_template`, downloadable system templates (render==parse), stores (derived
  closing_implied/variance), data_promotion wiring, upload→preview→confirm UI both modules,
  "Quyết toán" nav group.
- `7ca64eb` **Slice 2a** — `ezsoft_3tsoft` (real Growatt; bilingual; group-row roles; lumped
  Xuất → `outbound_total`, mig 084); per-client adapter binding (mig 085 +
  `settlement_adapter_binding`); admin registry `/admin/settlement-adapters`.
- `1a6381c` **Slice 2c** — `manual_generic` (alias auto-match + `mapping_override` engine).
- `0a8b304` **Slice 2d** — interactive column-mapping page (mig 086 widens parser_mappings.module):
  rigid pre-fill + LLM suggest + confirm → `parser_mappings` cache → re-upload of same shape auto.
- `aa257bc` **Slice 3** — `sap_mb5b` (Johnson MB5B detail) + `misa_can_doi_ton` (Hồng Phúc/An,
  merged header + "Kho hàng:" section breaks).
- `a507db3` **Slice 4** — `kiem_ke_multi_kho` (DKE multi-warehouse stocktake) +
  `settlement_link.period_end_link` + `/v1/hub` read API (nxt, inventory-snapshots,
  period-end-link) + API_CONTRACT docs.
- `421d25d` **Review fixes** (see below).
- `049f836`/`626d35d` — API_CHANGELOG + release(0.16.0) bump; `02412d5` merge.

7 adapters total (5 NXT + 2 inventory), all validated on real files (Growatt 2936 lines /
Johnson MB5B 20064 / Hồng Phúc MISA 123 / DKE stocktake 727 across 6 kho).

## Review (3-agent parallel + self-verify) → fixed in `421d25d`
- **Critical** — re-upload double-count: `superseded_by` was never written, so `period_end_link`
  SUMmed across multiple "current" artifacts. Fixed: `create_artifact`/`create_snapshot` supersede
  the prior current artifact per period (the missing half of the immutability design) +
  `mapping_parse` parse_status guard.
- **Important** — `preview_reject` was not client-scoped (cross-client integrity). Now loads
  `get_upload(upload_id, client_id=...)` first (both modules).
- **Minor** — override two-headers→one-field now first-column-wins; best-effort code join documented.
- Deferred (Minor): broad `except` in `parse_with_fallback`; mapping_parse 3× workbook load;
  outbound≠Σbucket preview warning; MISA column-order fragility; mig 083 manual-reapply idempotency.

## What didn't work (and how it was fixed) — for the next AI
- **Adapter greediness, 3×:** ezsoft (`_target_sheet` fallback to "first sheet with header band"),
  misa (parsed any sheet with Đầu Kỳ/Cuối Kỳ), kiem_ke (marker "thực đếm" matched our own
  template). Each fixed by gating parse on the *distinctive* signal (ezsoft/3tsoft title;
  "cân đối tồn kho" title; **Chinese** 实盘/實盤 only). This is now a documented rule.
- **EZSOFT header combine bug:** "first-non-empty per column" picked the merged category label
  ("Vật tư") over the real sub-header ("Mã"). Fixed by JOINing all header rows per column.
- **Test non-hermetic, 2×:** the test DB persists across pytest invocations → MAT-LINK artifacts +
  parser_mappings cache accumulated → assertions saw inflated/duplicate state. Fixed by using
  throwaway clients (`secrets.token_hex`) / clearing cache at test start. **Lesson: any test that
  writes to a shared client and asserts on aggregates/cache must isolate (fresh client) or clean.**
- **outbound_total**: surfaced mid-slice-2 when ezsoft showed a single Xuất; required a new
  migration (084) + reworking closing_implied. Modelled it as canonical total with the 4 buckets
  as optional breakdown.

## Release
- Bumped `CHANGELOG.md` ([0.16.0], VN client-facing) + `pyproject` 0.15.0→0.16.0;
  `API_CHANGELOG.md` 2026-06-14 Additive; tag `v0.16.0` + GitHub Release.
- **CD = prod deploy.** Merge → CD run #27497927944 (~3 min, green) → prod v0.16.0 verified.
- Tests at merge: 30 in-feature + **full suite 1524 passed, 16 skipped**.

## Open items (next session)
1. **Cross-link BCQT-System** to consume `/v1/hub` (nxt, inventory-snapshots, period-end-link).
   Settlement reconciliation (Mẫu 15/15a, BCCT↔NXT) lives in BCQT, not here. Write a sister-app note.
2. **Best-effort code join (I2)** in period_end_link — resolve NXT (internal/customs) ↔ snapshot
   `code` through catalog/code_mappings for exact matching (currently raw-string, lossy).
3. Deferred review minors (above) — pick up if/when they bite.
4. Carry-over (not this session): UoM review P4 (CO allocation unit guard); declarability prod
   rollout + CO adoption; outage tar-prune confirm after ~20/06.

## Notes / gotchas
- `reported_role` = provenance, never authoritative class (resolve from catalog).
- Re-upload supersedes per period; model does NOT support piecewise per-class uploads of one period.
- Pre-existing dirty working tree (`uv.lock`, `.ai/BACKLOG.md`, untracked session files) is NOT from
  this session — left uncommitted, as before.
- Dev server restarted on :8754 (`--workers 1 --reload`) during the session.
