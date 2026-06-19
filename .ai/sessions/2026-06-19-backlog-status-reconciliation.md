# Session 2026-06-19 — BACKLOG/STATUS reconciliation

Pure docs/state-hygiene session: no app code changed. Verified 16 tracked items
against the actual code at `c483673` and corrected stale markers in `.ai/BACKLOG.md`
+ `.ai/STATUS.md`. Committed as `56f750d` (docs-only, **not pushed**).

## What Was Done
- **Spotted STATUS staleness:** STATUS claimed `bad2c1a` / v0.15.0 with "version NOT bumped";
  git + `curl …/version` showed **v0.16.0 already released** (`bfd7aff`) and prod+nightly both
  on `c483673`. Fixed STATUS Current State / Recent Changes / Next Steps to match.
- **Verified 16 backlog items vs code** with 5 parallel `general-purpose` agents (read-only),
  each owning a cluster and returning per-item `STATUS | EVIDENCE(file:line) | SUGGESTED_MARKER`:
  1. UI/criteria/columns — B7, XX1, EX1
  2. bulk/wizard/aggregate — Phase 2 bulk, client #12, wizard "BOM #N"
  3. declarability — DC3a/b/c, DC1, DC2, BG1
  4. propose-BOM + currency — M1, B6
  5. tồn-CO infra — D1, P1, CS1, CS3, T1, LK1
- **Reconciled BACKLOG.md (7 items)** + **STATUS.md** strictly from agent evidence (file:line).
- Committed `56f750d` "docs: reconcile BACKLOG/STATUS with shipped work (v0.16.0)".

## Verdicts (evidence-based, HEAD c483673)
**Stale → now corrected (were tracked as open/placeholder):**
- **B7** DONE `cb3504b` — native datalist → segmented criterion picker (`co_case.html:1277-1294`); old
  `<datalist id="origin-criteria-options">` (`:844`) orphaned, safe to delete.
- **CS1** COMMITTED `ca11c37` (PR #2 `a295a7d`) — lot-history modal redesign shipped; "chưa commit" note stale.
- **D1** mostly done `2c856da` (fixes A/B/D + 13 tests in `test_co_stock_empty_pull_guard.py`); only narrow
  **C** (tombstone retry/full backstop), **E** (sync-status), **F** (refresh mode/reason UX) + **parity harness** remain.
- **B6** re-scoped — "always VND" no longer true; working native↔VND toggle (`co_case.html:3361-3399`,
  values at `co_case_context.py:2319-2324`). Remaining work = verify **FX accuracy** (`fob_fx_rate` cross-convert + missing-rate fallback `:3382`).
- **Phase 2 bulk** — backend BUILT (`co_case.py:1635/1646/1732` = preview_stock_all / bulk_substitute / bulk_lock);
  UI buttons gated off intentionally (`834e1da`, "routes untouched"). Not a placeholder.
- **DC3b** PARTIAL — export now strips rác render-time (`workbook_io.py:617`, `bang_ke_renderer.py:259`,
  `bang_ke_xml_generator.py:391` call `is_bom_technical_noise`); still leaks on pre-mig-078 sheets until re-Tính.
- **LK1** narrow lock guards landed (`66d5ad7` empty/no-BOM + `0e7128a` missing-price in `origin_can_lock`); only broad review remains.

**Confirmed still open (refs refreshed):**
- **M1** both sub-bugs live — write-only `proposed_status` (`co_case.py:2622`, no DH read-back in `data_hub_client.py`)
  + re-POST button (`initOriginProposeBom` `co_case.html:5406-5438`, label `:1196`).
- **DC3a** update-BOM still ships rác (`build_bom_proposal_rows` `co_case.py:2647-2661`, no noise filter).
- **DC3c** `declarable_unmatched=0 → LVC thổi` — display-only warning (`co_case_context.py:2692-2699`);
  no hard block in `origin_sheet_action_error` (`:1367-1406`), lock route (`co_case.py:2047-2115`), or export (`:1001-1235`).
- **#12** số tồn TỔNG PARTIAL — `#13a c9f5183` aggregates shortage per-material (`co_case_context.py:1675-1716`)
  but no SUM total across products (`co_case.html:5782` shows only "Thiếu tồn: N mã/M SP").
- **Wizard "BOM #N (mặc định)"** still silent (`co_case.html:6018-6021`, no version dataset read).
- **XX1** interim only (`afea9db` blanks M-N cols `bang_ke_renderer.py:296-300`, `workbook_io.py:659-662`); no có-xuất-xứ/LVC branch.
- **EX1** interim K=số only; no `import_ref_format` toggle. **P1** ~40s cold-load unchanged (`co_case.py:986-993`).
  **T1** no DB schema isolation (`tests/conftest.py`). **CS3** both PARK items unimplemented (`co_stock_materializer.py:545`).
  **DC2** name from `material_name` (`co_case_context.py:1978`), no sample_text path.

**Already correct (untouched):** BG1 DONE `60e55a1` (soft-delete stable index — also resolves the off-by-one
hypothesis still living in its `<details>`); DC1 DONE CO-side / blocked-on-DH (Material Group re-ingest).

## Decisions Made
- **Verify, don't trust:** treated every "open"/"partial" marker as suspect and required file:line proof
  before editing — caught 7 stale items the prior backlog edit (06-18) predated.
- **Parallel read-only agents** for the 16-item sweep (each returns a compact structured verdict) — kept
  file dumps out of context, evidence in.
- **Committed docs straight to `main`** (repo convention: docs commits go to main, e.g. `6099440`/`facc572`),
  not a branch. **No AI co-author trailer** (user rule). **Not pushed** (user must ask).
- Excluded `uv.lock` from the commit (unrelated, pre-existing modification).

## What Didn't Work
- N/A — no failed approaches. (One self-correction: initially summarized **BG1** as "open/hypothesis" by
  skimming its `<details>` block; it was already DONE at the top of the section. Verified before editing.)

## Open Items
- **Push `56f750d`** to origin so prod/nightly git_sha advances past `c483673` (docs-only, safe). Pending user ask.
- The reconciled Next Steps now lead with: #1 ranking #4 (DH-side, needs api-request), #2 Phase 2 bulk
  re-enable/retire + wizard "BOM #N", #3 client #12 SUM total, #4 correctness (DC3a/DC3c hard-block + B6 FX accuracy).
- Backlog markers are authoritative only as of `c483673`; re-verify if more app commits land before next backlog edit.
