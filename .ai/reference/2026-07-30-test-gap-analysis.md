# Test-gap analysis — high-risk CO modules

Date: 2026-07-30. Scope: map where a bug would cause the worst outcome (wrong C/O issued,
wrong tồn, over-claim, data loss) against what the test suite actually guards. Analysis only —
no tests written here; this is the map.

## Method + suite shape

- 97 test files under `tests/` (94 Python + 3 `.mjs` legal-lookup). Grepped test names and
  skip markers, then read the high-risk production paths and the tests that touch them.
- **File-mode is the default.** `tests/conftest.py` forces `CO_ALLOW_LOCAL_SOURCE=1` and does
  not set `BARRY_DATABASE_URL`. Every store gated on `database_url()` falls back to the local
  file backend or no-ops.
- **DB-mode tests skip without Postgres.** Files that `pytest.skip("needs BARRY_DATABASE_URL")`
  or `@pytest.mark.skipif(not database_url())`:
  `test_co_stock_lock_concurrency.py`, `test_recalc_lock_parity_db.py`,
  `test_supplier_evidence.py` (`test_append_only_round_trip_latest_event_wins`),
  `test_co_stock_workbook.py` (line 270), `test_cost_allocation_store.py` (line 37),
  and large parts of `test_co_demo.py` (ledger/events blocks at lines 3445, 4040, 4184, 4612).
  `test_origin_narrow_source_context.py::test_origin_parity_e2e...` additionally needs
  `DATA_HUB_ENABLED` + a materialized snapshot.
- Many file-mode tests actively `monkeypatch.delenv("BARRY_DATABASE_URL")` to force the local
  path (bulk-lock, substitute, cost-allocation, column9-flip, preview-stock, portfolio).

Consequence: the modules that decide **tồn correctness and over-claim** (`co_stock_ledger`,
`co_stock_materializer` DB pipeline) execute their real logic **only in DB-mode**, which is not
run in a file-mode / CI-style pass. The pure helper functions around them are covered; the
persistence and cross-case invariants are not.

## Module → risk → coverage table

| Module | Risk | Coverage | Untested critical path | Suggested test |
|---|---|---|---|---|
| `app/co_stock_ledger.py` (over-claim, claims, release) | **H** | partial | Cold-start skip: over-claim guard is nested in `if snapshot_exists:` (`:203-204`); a client with **0 materialized rows** skips the check entirely (Backlog Fix F/D2). `StockOverclaimError` raise (`:261`) + `FOR UPDATE` serialization only run in DB-mode. `apply_used_qty` overlay (`:571`), `claims_summary_for_case` (`:405`), `used_qty_by_lot` (`:478`) have no direct test. `record_sheet_release`/`release_all_claims_for_case` soft-release only in DB `test_co_demo`. | needs-DB: cold-start over-claim. file-mode: `apply_used_qty` overlay math (pure). |
| `app/co_stock_materializer.py` (delta/full refresh) | **H** | partial (pure funcs only) | `refresh_co_stock_for_client` DB pipeline (`:78`) — UPSERT (`_upsert_records :252`) + targeted DELETE — has **no test in any mode**; file-mode tests only prove it bails early and echoes `mode` when no DB. `_claims_blocking_removal` (`:321`), the guard that keeps a claimed lot from being deleted by a refresh, has **zero coverage**. `_emit_diff_events` (`:338`), `_snapshot_marker` (`:400`) untested. Delta-vs-full end-to-end parity (Backlog D1) has no harness. | needs-DB: delta-vs-full parity + `_claims_blocking_removal`. Pure `_classify_changes`/`_plan_removed_keys`/`co_config_fingerprint` already covered file-mode. |
| `app/routers/co_case.py` `record_sheet_lock_claims` (`:181`) | **H** | thin (always stubbed) | The bridge that reads `products[].materials[].allocation_lines` and builds the ledger allocations (`source_row`, `claimed_qty=allocated_qty`, `customs_code` preferring `customs_material_code`), plus the fall-back-to-persisted-case when the form-rebuilt case strips allocation_lines. Every route test monkeypatches this away (`test_bulk_lock_route.py:54`). If the extraction is wrong the claim is wrong → wrong tồn. | file-mode: stub `co_stock_ledger.record_sheet_lock`, assert the allocations list shape + persisted-case fallback. |
| `app/routers/co_case.py` lock/export/batch routes | **H** | partial | Bulk lock ordering + overclaim-skip is tested with a **stubbed** ledger (`test_bulk_lock_route.py`). Single-sheet `lock_co_case_origin_sheet` `StockOverclaimError`→409 (`:2273`) has no file-mode test. **LK1 dirty-before-lock**: lock reads the persisted case with no forced save/recalc; the 409 "Origin case state changed" (`:1831`,`:3080`) is a structural-revision check, not a stale-vs-config check — a sheet calculated under an old client-config/eligibility fingerprint can be locked with stale allocations. | file-mode: single-sheet route 409-on-overclaim; LK1 stale-config lock regression. |
| `app/web/co_case_context.py` (calc, belts, VN-origin) | **H** | good on belts, partial on core | Belts well covered file-mode: declarable_unmatched (`test_declarable_unmatched_guard.py`), shortage (`test_shortage_lock_guard.py`), missing-price (`test_missing_price_lock_guard.py`), lock-readiness (`test_origin_lock_readiness_guard.py`), VN-origin resolver + RVC rise (`test_vn_origin_resolver.py`), column9 (`test_column9_materialization.py`), shortfall rollup (`test_shortfall_rollup.py`). Gaps: **DC3b** — a sheet whose materials lack the `customs_relevance` field (pre-mig-078) leaks junk to export until re-Tính; only the unit `is_bom_technical_noise({...no field})` is checked (`test_technical_noise_filter.py:63`), not the sheet→export leak. FX cross-conversion accuracy (Backlog B6) unasserted. | file-mode: DC3b field-absent sheet reaches export; FX cross-convert value. |
| `app/data_hub_client.py` (narrow/heavy pulls, auth) | **H** | good | Auth/JWKS/ACL, cursor pagination, canonical-UOM normalization, code-shadow fallbacks, bom-service + portfolio boundary, narrow vs heavy fetch all covered (`test_data_hub_integration.py`, `test_dh_normalization_fallbacks.py`, `test_co_case_skip_heavy_context.py`, `test_origin_narrow_source_context.py`, `test_substitute_modal_no_full_pull.py`). Recent narrow-fetch fixes (commits `520b720`/`544840e`/`c104615`) have regression tests. | Low residual. Consider a mutating-scope (`hub:propose:bom`) auth assertion for the propose path (M1). |
| `app/bang_ke_renderer.py` / `app/workbook_io.py` (export = pure renderer) | **M–H** | good | Export==web parity (`test_bangke_export_web_parity.py`), strip==fold invariant, column9 parity across 3 formats (`test_column9_materialization.py:233`), HQ template branch EUR.1↔LVC/PSR/CTH (`test_hq_sheet_codes.py`), currency mode (`test_renderer_currency_mode.py`, `test_export_field_wiring.py`). Gap: Backlog B6 nit — legacy rows lacking `*_vnd` double-apply the FX rate (`bang_ke_renderer.py:185`). | file-mode: FX-rate applied exactly once on a `_vnd`-less legacy row. |
| `app/supplier_evidence_store.py` | **M** | partial | Damage/benefit list logic + route validation covered file-mode (`test_supplier_evidence.py`). The append-only latest-event-wins projection — the persistence correctness — is **DB-only** (`:188`, skipif). | needs-DB kept; if the projection is a pure fold over events, add a file-mode fold test. |
| `app/substitution_history.py` | **M** | good | Locked-swap recording, cross-case ranking, out-of-range/no-op skip covered file-mode (`test_substitution_history.py`); history-pin route covered (`test_substitute_history_route.py`). | Low residual. |
| `app/co_stock_derivation.py` | **M** | partial | Identity/plumbing invariants touched (`test_origin_field_plumbing.py`, `test_code_identity_invariants.py`); eligibility math has its own test (`test_co_stock_eligibility.py`). `remaining_qty`/`baseline_used` derivation into `derive_rows` not asserted end-to-end. | file-mode: derivation of remaining_qty from opening − baseline_used. |

## TOP 10 tests to write next

Ranked by (severity of harm) × (currently unguarded). Each names the exact assertion.

1. **Cold-start over-claim guard (Fix F / D2)** — *needs-DB.* Seed a client with **zero**
   `co_stock_rows`, then `record_sheet_lock` an allocation whose qty exceeds real availability.
   Assert the intended post-fix behavior: `StockOverclaimError` is raised (today the
   `if snapshot_exists:` branch at `co_stock_ledger.py:204` is skipped and the claim is written
   silently). This is the guard the fix needs. Harm: over-claim / wrong tồn on fresh workspaces.

2. **`_claims_blocking_removal` orphan-claim guard** — *needs-DB.* Seed `co_stock_rows` + a
   `locked` claim on lot L, then run `refresh_co_stock_for_client(mode="full")` whose
   `derive_rows` omits L (upstream deletion). Assert L is **not** deleted from `co_stock_rows`
   (`co_stock_materializer.py:321`). Harm: a refresh silently strands a locked case's claim →
   over-claim next cycle, wrong tồn. Zero coverage today.

3. **Delta-vs-full materializer parity (D1)** — *needs-DB.* Full-refresh a snapshot, apply a net
   change once via `mode="full"` and once via `mode="delta"` (tombstones + changed rows) from the
   same starting snapshot; assert the resulting `co_stock_rows` payloads are identical to a
   from-scratch full refresh of the final state. Harm: silent delta under/over-apply corrupts tồn.

4. **`record_sheet_lock_claims` allocation extraction** — *file-mode.* Build a case with
   `products[].materials[].allocation_lines` (`allocated_qty`, `source_row`,
   `customs_material_code`), stub `co_stock_ledger.record_sheet_lock` to capture its args. Assert
   each line maps 1:1 to `{source_row, claimed_qty=allocated_qty, customs_code=customs_material_code}`
   and that when the in-memory case has stripped `allocation_lines` the persisted-case fallback
   supplies them (`routers/co_case.py:181-210`). Harm: wrong claim → wrong tồn.

5. **DC3b pre-mig junk leak at export** — *file-mode.* Build a calculated/locked sheet whose
   technical-noise materials **lack** the `customs_relevance` field entirely, then run the export
   renderer (`bang_ke_renderer` / `workbook_io.write_hq_sheet_materials`). Assert these rows
   currently reach the export (because `is_bom_technical_noise` returns False without the field),
   and pin the expected fix (force-recalc gate or render-time reclassify). Harm: junk lines on an
   issued C/O.

6. **Single-sheet lock route over-claim → 409** — *file-mode.* POST `lock_co_case_origin_sheet`
   with `record_sheet_lock_claims` stubbed to raise `StockOverclaimError`; assert HTTP 409 with the
   violation detail (`routers/co_case.py:2273`). Only the bulk route's overclaim-skip is tested
   today; the single-sheet path is unguarded.

7. **LK1 dirty-before-lock** — *file-mode.* Seed a sheet marked `calculated` whose stored
   eligibility/config fingerprint differs from the current client-config (calc is stale), then lock.
   Assert the lock is blocked or forces a recalc rather than writing claims from stale allocations.
   Today the only guard is the structural revision 409 (`:1831`), which does not catch config drift.
   Harm: C/O locked on stale LVC/allocations.

8. **`apply_used_qty` overlay math** — *file-mode.* Given `stock_rows` and `used_by_lot`, assert
   `remaining_qty` drops by the used amount per lot and never renders negative, and that the
   documented same-case conservative under-state holds (`co_stock_ledger.py:571`). Pure function,
   feeds every tồn display and calc-time availability read.

9. **Supplier-evidence append-only latest-wins in file-mode** — *file-mode (if projection is a pure
   fold).* Two flip events for the same supplier resolve to the latest state. Today this guarantee
   is DB-only (`test_supplier_evidence.py:188`, skipif) so it never runs in CI. Harm: a stale
   origin flag flips a material's originating status → wrong RVC.

10. **B6 FX double-apply on legacy rows** — *file-mode.* Render a bảng kê row that lacks the
    `*_vnd` fields with an FX rate set; assert the rate is applied exactly once
    (`bang_ke_renderer.py:185`), not twice. Harm: wrong declared value on the bảng kê.

## File-mode-only blind spot

These correctness guarantees have **no file-mode test** and rely on DB-mode runs that a file-mode
/ CI-style pass skips. If they regress, nothing in a default `pytest` run catches it:

- **Over-claim rejection at lock** — the availability pre-check + `StockOverclaimError`
  (`co_stock_ledger.py:203-261`). File-mode `record_sheet_lock` is a no-op (`_ledger_available()`
  is False) returning 0. Guarded only by `test_co_stock_lock_concurrency.py` and
  `test_recalc_lock_parity_db.py`, both DB-gated. The **cold-start** sub-case (no snapshot) is
  guarded by neither, in any mode.
- **Concurrency serialization** — the `SELECT ... FOR UPDATE` lot lock that stops two concurrent
  locks from both passing the availability check. DB-only.
- **Materializer DB pipeline** — UPSERT + targeted DELETE + `_claims_blocking_removal` + event emit
  + snapshot-marker advance, and delta-vs-full parity. No test exercises it in any mode; only the
  pure planning/classification functions are covered file-mode.
- **Recalc↔lock allocation parity against the folded snapshot** — `test_recalc_lock_parity_db.py`
  (DB-only). The allocation-read side (recalc reads folded snapshot, not raw BCCT) is covered
  file-mode via monkeypatch (`test_recalc_stock_source_parity.py`), but the ledger-side rejection
  of a raw-sized claim is DB-only.
- **Supplier-evidence append-only projection** — `test_supplier_evidence.py:188` (DB-only).
- **`co_stock_workbook` trừ-lùi ingestion** and **`cost_allocation_store` dual-write** — partly
  DB-gated (`test_co_stock_workbook.py:270`, `test_cost_allocation_store.py:37`).

The cluster that matters most — over-claim and tồn integrity — is exactly the cluster whose real
logic only runs when Postgres is present. Items 1–3 above (cold-start, orphan-claim, delta/full
parity) are the highest-value additions because a bug there produces wrong tồn or a stranded claim
with no test to catch it, in either the local file-mode suite or CI.
