# Project Status

**Date:** 2026-05-25 — Johnson UoM drift audit + btp_sx uom auto-capture bug fix shipped. Local DB synchronized with 159 new overrides + 440 catalog uom corrections. Demo box deploy pending.

## Current State

**Branch:** `main` at `d7508ef`. One commit ahead of `origin/main` (push pending).

Recent commits:
- `d7508ef` — **NEW:** btp_sx uom auto-capture switches from Base UoM (`parent_code`) to Component unit (`child_code`); 3 tests updated
- `5e9a4fb` — docs(handoff): catalog time-series ship + UoM drift Excel tool
- `58587ca` — per-material BCCT time-series on catalog detail page
- `6d45f77` — declaration file status + A.2 conflicts handoff
- `21f3620` — declaration file status API + bulk ZIP download for CO
- `d4ea2d7` — catalog conflicts review queue (A.2)

**Tests:** 1143 passed, 15 skipped. `tests/test_fixup_johnson_btp_uom.py` 3/3 PASSED with corrected assertions.

**Migrations:** at mig 066. No new mig.

**Working tree:** clean of code/test drift after `d7508ef`. Untracked artefacts unchanged from 2026-05-21 (uom_drift_report.py, training scripts, prior session notes).

**Dev server:** `:8754` workers=4 — restarted at session start, healthz HTTP 200.

**Demo box (`100.84.189.87:8754`):** still NOT updated. Backlog now also includes the btp_sx bug fix + 159 new override rows + 440 catalog uom corrections (data) on top of the prior bundle (mig 065/066 + M16 ingest + UoM overrides + A.2 conflicts + declaration API + ZIP route + time-series).

**Local DB Johnson state:**
- Catalog: 2,614 btp_sx EA + 1 G (was 2,174 EA + 440 KG + 1 G — 440 corrected this session)
- Overrides: 516 (was 357 at session start — +3 mass + +156 EA→SETS)
- Stale tech_flat: 2,812 (was 2,543 baseline; peaked 3,445 after first materialize, cleared 633 net)
- Drift-flagged codes: 39 unique (was ~180 at session start)

## Recent Changes

### 1. Johnson UoM audit + btp_sx uom bug fix (commit `d7508ef`)

Full session note at `.ai/sessions/2026-05-25-johnson-uom-audit-and-btp-uom-bugfix.md`.

Headlines:
- **Inserted 3 mass-synonym overrides** for thép tấm + dây hàn (`1000478156`, `1000480137`, `K60000900`) — closes the 3-code gap from `factor_inventory.md` (2026-05-12). Evidence: M16 declared qty matches SAP tech_flat qty byte-identical → SAP "EA" is mass synonym, factor 1.0 (or 0.001 for MT scale).
- **Discovered + fixed 440-code btp_sx uom bug**: `scripts/fixup_johnson_btp_sx_after_bom.py` queried `bom_edges WHERE parent_code = code` (= Base UoM of inputs the BTP consumes) instead of `child_code = code` (= the BTP's own Component unit). Per `project_bom_component_unit_canonical` memory, Component unit is canonical; Base UoM is SAP stockkeeping internal and must not populate catalog. Root-cause fix: 440 catalog rows updated KG→EA, script patched, 3 tests rewritten to assert Component unit behaviour.
- **Inserted 156 EA→SETS overrides**: bidirectional synonym gap from the Johnson reply (2026-05-21 confirmed "1 EA = 1 SET"). Overrides table previously had SETS→PIECES but not EA→SETS — surfaced after 2026-05-25 catalog correction.
- **Re-materialized** Johnson tech_flat 3 times. Net: 633 stale artifacts cleared, ~6,000 BOM rows now have `applied_uom_factor` populated.

### 2. Local DB cleanup — Johnson + Growatt only

Other clients (6 inactive/test) deleted from local hub schema in preparation for demo box sync.

## Next Steps

Priority order:

1. **Deploy bundle to demo box** (`100.84.189.87:8754`). Includes: mig 065/066, M16 ingest, UoM overrides (516 total), A.2 conflicts page, declaration file status API + ZIP route, time-series feature, btp_sx fix, 440 catalog corrections. Single deploy picks all of them up.

2. **Sync DB to demo box** — pg_dump local hub schema (Johnson + Growatt only) and restore on demo. Data changes from this session (440 catalog + 159 overrides + re-materialized BOM) are local-only until synced.

3. **Wait for CO consumer PR** on the declaration file status endpoint. Provider tests + changelog + sister-app note shipped. Nothing to do until CO pings back.

4. **Audit 39 remaining drift codes** — 5 small buckets:
   - 20 SETS→SETS same-UoM drift (alias case suspected)
   - 15 EA→SETS residual (not in original 156 set)
   - 2 EA→EA factor_missing (same-UoM weird)
   - 1 G→EA outlier
   - 1 Chai/Lọ/Tuýp→EA Vietnamese token

5. **Verify `1000454182` factor=2.0** with Johnson (n=2/3 small sample, carry-over).

6. **70 sản phẩm XK 2026 thiếu BOM** — get from Johnson or document (carry-over).

7. **CO repo dropdown logic for dual_source 409** (carry-over).

8. **Next backlog item if bandwidth.**
   - F.1 Growatt programmatic bulk re-ingest (~0.5-1d, mirror Johnson).
   - A.4.2 Substitute XLSX bulk upload (~0.5d).
   - A.4.3 Smarter goods_name similarity — gated on pg_trgm.

## Blockers

- Johnson contact / customs broker for UoM factor confirmation (carry-over for 39 residual codes + `1000454182` + 70 SP XK).
- CO repo dev availability for declaration consumer PR + dual_source dropdown logic (carry-over).

## Notes for Next AI Session

- **`scripts/fixup_johnson_btp_sx_after_bom.py` is now correct.** Re-running on Johnson would be a no-op (440 codes already fixed via UPDATE). For new client onboarding, the corrected `child_code` query yields Component-unit-canonical uom from the start.

- **Bidirectional synonym pattern requires bidirectional overrides.** When agency confirms "X = Y" as synonym, you may need to insert BOTH `X→Y` AND `Y→X` rows depending on which direction each affected code's catalog uom drifts in. This session surfaced the inverse-direction gap (EA→SETS) only after re-materialize after catalog correction. Generalize: future agency synonym replies should be cross-checked for required override directions before assuming the insert is complete.

- **Materialize script `--cleanup-stale` is the canonical re-derive path** after override changes. Be aware it ALSO runs a main loop that fills missing shapes for raw_graph artifacts — first run this session unexpectedly created 6,274 new shallow+full_flat for raws that had been missing shapes. Net coherent; just know the scope before kicking off.

- **39 codes drift remaining** — 5 small buckets per Next Steps #4. Each bucket needs its own evidence path. 20 SETS→SETS same-uom case most suspicious for an aliasing bug; the rest are likely small data-quality outliers.

- **Local DB now Johnson + Growatt only.** Other 6 test/seed clients cleaned out 2026-05-25 in preparation for demo box sync. Don't expect demo-precision-manufactu-* or DKE/Do-Thanh in queries anymore.

- **Demo box deploy bundle is large** — covers ~2 weeks of unshipped work. Test plan after deploy: login, navigate to /catalog/conflicts, view Johnson product detail page (verify time-series renders), trigger a sample M16 ingest preview, hit declaration file status API. If any step fails, isolate via mig version vs commit hash.

- **Push gate** — d7508ef + new STATUS commit pending push. Sync to origin before deploying so demo box can `git pull`.
