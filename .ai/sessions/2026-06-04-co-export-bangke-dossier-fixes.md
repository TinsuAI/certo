# Session: CO export (bảng kê) + dossier ZIP bug fixes

**Date:** 2026-06-04
**Scope:** Four production bugs on the johnson-vn case `co-case-ede4d913bafa`, reported
by the user one at a time from the live demo (`barry-co.tinsu.ai`). Each was root-caused
against real prod data, fixed, deployed to `tinsu`, and verified on prod.

## What Was Done

### 1. Bảng kê export 500 — `decimal.InvalidOperation` (`7727e3e`)
- **Symptom:** "Xuất bảng kê" → Internal Server Error.
- **Root cause:** when a material is allocated across stock lots with differing unit
  prices, `allocation_unit_value_summary` (co_case_context) synthesizes the string
  `"Nhiều đơn giá"` as `unit_value`. The legacy shell export path
  (`create_hq_bang_ke_workbook` → `_create_hq_bang_ke_workbook_shell` →
  `write_hq_sheet_materials`) called strict `decimal_value()` on it → crash. DB raw
  values are all numeric — the bad value is synthesized at runtime, so grepping the DB
  finds nothing.
- **Fix:** `decimal_value` (app/workbook_io.py) now returns `Decimal("0")` on
  `InvalidOperation` (protects all fields). The unit-price display cell preserves the
  marker text instead of a misleading 0.

### 2. "Form lạ" — export not using the template (`533cd5c`)
- **Symptom:** export worked but rendered a bare form, not the provided template, and
  not one sheet per finished product.
- **Root cause:** `hq_template_path()` reads `data/local/hq-templates/form-mau-combined.xlsx`
  and `config/`. The Dockerfile only `COPY app db docs`. `data/` is `.dockerignore`'d
  (and a symlink to sibling repo `barry-CO-bom-data`), `config/` wasn't copied either.
  So prod always fell back to `_create_hq_bang_ke_workbook_shell` (criteria-grouped bare
  sheets). The styled template path (one sheet per product, titled `<seq><product_code>`)
  only ran locally.
- **Fix:** committed a shippable copy at `assets/hq-templates/form-mau-combined.xlsx`
  (540K, government form = shared asset, not client data), added `COPY config ./config`
  + `COPY assets ./assets` to the Dockerfile, and added `HQ_FORM_MAU_ASSET_PATH` as a
  fallback in `hq_template_path()`. Verified on prod: template resolves to `/app/assets/…`,
  4 products → sheets `1MFW0525-39 … 4MFW0502-39`.

### 3. TKX/TKN false "Thiếu tờ khai" (`65157ff`)
- **Symptom:** exports page showed all 84 TKN + 1 TKX as "Thiếu tờ khai" though Data Hub
  had the files (`file_count=1`).
- **Root cause (NOT Data Hub — DH was verified correct):** `co_case_context` flips on
  `cached_case_context=True` whenever the case has a `source_snapshot` (true after origin
  ran). That routes through `cached_origin_source_context`, which returned a dict WITHOUT
  `declaration_file_counts` → `case_tkx_tkn_summary` got `… or {}` → every declaration
  `in_data_hub=False`.
- **Fix:** `cached_origin_source_context` now calls the narrow
  `portfolio_service.declaration_file_counts(...)` (guarded on `data_hub` present) and
  includes it. Verified on prod: `missing_tkn` 84→0, `missing_tkx` 1→0.

### 4. Dossier ZIP missing declaration files → then missing TKX (`75ad33f` + DH-side fix)
- **Symptom:** dossier `.zip` `TKX/…zip` and `TKN/…zip` contained only
  `DANH_SACH_TO_KHAI.txt`, no real `.xls` files.
- **Root cause A (Data Hub side):** the Bearer `GET /v1/hub/clients/{c}/declarations/download.zip`
  built the manifest (correctly naming the files) but never embedded the blobs — violating
  its own approved contract. Logged a defect artifact + a self-contained DH fix prompt
  (`.ai/api-requests/2026-06-04-declarations-download-zip-missing-file-bytes*.md`, committed
  in `74d1903`). **The Data Hub team fixed it** (root cause slightly different from CO's
  guess, same symptom). After that, TKN files appeared.
- **Root cause B (CO side):** TKX (export) was still empty. The dossier route
  (`export_co_case_dossier_zip`) recomputes `invoice_matches` via the heavy
  `co_case_source_context`, which derives them from a LIVE shipment reference
  (`invoice_no` / `export_declaration_nos`). This case has an empty shipment ref but
  carries `case["source_invoice_matches"]` persisted at origin (gồm TKX `308189816340`).
  The exports page reads those via the cached path → showed TKX fine; the dossier route
  didn't.
- **Fix:** the dossier route falls back to `case["source_invoice_matches"]` when the
  heavy recompute yields no matches, and recomputes `declaration_file_counts` from the
  matches actually used. Verified on prod: dossier `03-to-khai/TKX/…zip` = 1 real `.xls`,
  `TKN/…zip` = 84 real `.xls`, total 11.5MB.

### Tests
- Added regression tests for each: non-numeric `unit_value` in shell builder; cached
  source context carries `declaration_file_counts`; dossier keeps TKX from persisted
  matches when heavy recompute is empty. All pass plus existing bang_ke/dossier/context
  suites (9 + 62 + 5 green respectively).

## Decisions Made
- **`decimal_value` tolerant + preserve marker text:** mirrors the newer
  `bang_ke_renderer._decimal` (already tolerant). Chose to keep "Nhiều đơn giá" in the
  display cell rather than zero it, since 0 is misleading for an operator.
- **Ship the template as a committed `assets/` asset, not via server volume.** User chose
  this over the XML/config renderer or a server-mounted file — exact provided-form styling,
  versioned, survives redeploys. The FORM MAU is a government form (client-agnostic), so
  committing it doesn't violate the "keep `data/` local" convention.
- **Honor the Data Hub guardrail:** the download.zip bug was DH-side; CO did not patch
  around it. Logged a defect + DH prompt artifact and let the DH team fix it. CO needed
  zero change for the blob embedding; only the separate TKX-source bug was CO's.
- **Did NOT push the docs commit (`74d1903`) to tinsu** — docs-only, no reason to redeploy.

## What Didn't Work / Dead Ends
- **Initial hypotheses on the TKX/TKN and dossier bugs blamed Data Hub data retrieval.**
  Direct in-container probes disproved the DH-side theory for bug #3 (DH returned correct
  `file_count`) and narrowed bug #4 to a CO routing issue after the DH fix. Lesson:
  probe the real endpoint before assuming the remote service is wrong.
- **Grepping the DB for the bad `unit_value`** (bug #1) found nothing — the value is
  synthesized in the context layer at runtime, not stored. Had to read the summary
  functions, not the data.
- **Momentary misread:** `CO_CASE_STORE_ROOT` is only uploaded supporting files; case
  data is in Postgres (`co_cases`/`co_case_states`). Corrected mid-session.

## Open Items
- **Push `74d1903`?** Optional — carries the DH defect docs into the demo repo (harmless
  redeploy). Currently local only.
- **`.ai/scripts/*.cjs`** e2e smoke scripts still untracked — decide whether to commit.
- **Batch 1 #2/#4** still need client input (unchanged from last session).
- The Data Hub team's `download.zip` fix should ideally get a provider test on their side
  matching the cookie route byte-for-byte (requested in the DH prompt artifact).
