# Project Status

## Current State
- Active branch: `main`; do not push unless the user asks.
- Local CO dev server is running at `http://127.0.0.1:8001`; `/healthz` returned `{"status":"ok"}` on 2026-05-07.
- CO remains a Data Hub consumer. Keep raw `/v1/hub/*` endpoint strings inside `app/data_hub_client.py`; `tests/test_data_hub_policy.py` enforces this.
- C/O origin allocation remains snapshot-only inside CO, with a customer-scoped soft lock for official origin stock calculation/export:
  - only one dossier per customer can hold the origin stock calculation session at a time
  - `Tính lại snapshot` and dossier XLSX export acquire/renew the lock
  - other dossiers stay editable for preparation but cannot calculate/export official origin stock output until the lock is released
  - lock TTL is currently 60 minutes
- C/O dossier creation now uses a dual shipment reference model:
  - `invoice_no` is optional
  - `export_declaration_nos` is optional
  - when export declarations are present, BCCT matching is declaration-authoritative
  - invoice is used for fallback matching and mismatch/missing-reference warnings
  - if an export declaration has no `invoice_ref`, the dossier can still be created and matched by declaration
- The create/shipment UI now has separate fields for `Invoice` and `Số tờ khai xuất`. Backend still tolerates a declaration accidentally pasted into the invoice field and resolves it where possible.
- Invoice preview layout no longer overflows over adjacent create-form controls.
- Dossier deletion remains implemented with backend guardrails:
  - only roles configured in Technical Settings `CO_CASE_DELETE_ROLES` can delete
  - draft/preparation dossiers can be deleted
  - dossiers holding the stock lock must release the lock before deletion
  - completed/submitted/closed dossiers cannot be deleted
  - delete uses an in-app confirmation modal
- Pre-existing unrelated worktree artifacts remain separate and should not be committed unless explicitly requested:
  - `docs/co-form-index-confirmation.md`
  - `docs/co-form-index-confirmation.xlsx`
- Local screenshot artifacts remain under `.ai/screenshots/`; they are not required for the current commit.

## Recent Changes
- Fixed invoice preview/create-form overlap by making invoice preview responsive and letting populated preview span the create form row.
- Added dual reference persistence in `app/co_case_store.py`:
  - create/update stores `shipment.export_declaration_nos`
  - existing state normalizes missing declaration lists
  - case workbook export includes export declarations and reference warnings
- Updated BCCT matching:
  - file-backed matching prefers `declaration_no` when declarations exist
  - invoice-only dossiers still match by `invoice_ref`
  - invoice mismatch and missing `invoice_ref` cases surface `reference_warning`
  - Postgres source index matching accepts declaration refs with backward-compatible fallback for older adapters/fakes
  - Data Hub mode uses existing `list_bcct` data for declaration-authoritative matching, without adding new Data Hub endpoints
- Updated C/O UI copy and fields:
  - create form has separate `Invoice` and `Số tờ khai xuất`
  - shipment step shows and edits both references
  - exports/origin surfaces say “tham chiếu hồ sơ” instead of assuming invoice-only matching
  - export match table shows reference warnings
- Added regression coverage for:
  - declaration-only matching with missing invoice
  - declaration-authoritative matching when invoice is wrong
  - create-by-declaration with and without invoice refs
  - declaration lookup resolving to invoice where available
  - existing invoice market hint behavior remaining unchanged
- Verification completed:
  - targeted invoice/declaration tests passed
  - `uv run pytest` passed: `178 passed in 30.08s`
  - `curl -fsS http://127.0.0.1:8001/healthz` returned `{"status":"ok"}`

## Next Steps
1. Manually review the C/O create and shipment forms in the browser with real customer data:
   - invoice-only
   - declaration-only
   - invoice + matching declaration
   - invoice + mismatched declaration
   - declaration with missing `invoice_ref`
2. Confirm whether multi-declaration dossiers should allow manual row selection when one declaration contains multiple products or invoice refs.
3. Confirm the production definition of a “completed” dossier. Current delete blocking recognizes `completed`, `done`, `finished`, `submitted`, and `closed` from `status`, `case_status`, or `origin_snapshot.case_status`.
4. Decide whether the origin calculation lock should move from CO local state into a Data Hub-owned reservation/ledger when global shared stock decrement becomes real.
5. Revisit mixed-currency allocation rules before automatically summing VNM across currencies.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User wants concise but non-black-box explanations: briefly say what was inspected, what failed, and how it was resolved.
- The term to use in Vietnamese UI is “dòng tồn”, not “lot”.
- Current allocation behavior is still snapshot-only inside CO. The lock prevents concurrent same-customer calculations in CO, but it does not reserve/decrement shared stock globally.
- The important CO reference decision is: dual reference, declaration-authoritative when present.
- Do not add Data Hub endpoints from CO. Declaration-authoritative matching currently uses already available `list_bcct`/source rows.
- Do not commit unrelated `docs/co-form-index-confirmation.*` changes unless the user explicitly asks.
- Screenshot folders under `.ai/screenshots/` are local verification artifacts; keep them out of commits unless explicitly requested.
