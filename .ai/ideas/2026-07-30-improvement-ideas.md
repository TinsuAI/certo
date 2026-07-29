# Improvement ideas — 2026-07-30

Ideation only. No app code changed. Each idea is grounded in a specific code or domain
observation and ranked within its bucket by value/effort. Nothing here re-opens a settled
ADR (`.ai/DECISIONS.md`): no soft-reservation stock model, no bảng kê grain migration,
`allocation_code` stays a derived non-key, no logic in export renderers, client-config
ownership stays partitioned, phase-2 in-bloc stays deferred.

Path note: current code lives at `app/routers/co_case.py` (was `app/co_case.py`) and
`app/web/co_case_context.py` (was `app/co_case_context.py`).

---

## Bucket 1 — Operator workflow

### OW1 — Offload heavy Data Hub pulls off the async event loop
Run the synchronous ~15s DH source pull in a thread so one operator's cold open stops
freezing every other operator's request on the same instance.
- **Grounding:** `co_case_detail` (`app/routers/co_case.py:1076`), `co_case_step` (`:1095`)
  and `co_case_origin_sheet_substitute_candidates` (`:2315`) are `async def` but call the
  synchronous `co_case_source_context` / material-catalog pulls; STATUS residual H2
  (`.ai/STATUS.md:29`, `:388`) records the ~15s first-open still blocks the loop after the
  524 fix removed the 100s case.
- **Effort:** M
- **Main risk:** the sync pull touches module-level caches
  (`co_case_source_context_cached`, `co_case_material_catalog_cached`); moving it to a
  thread needs those caches proven thread-safe first (pairs with AG3), else a race corrupts
  a cached snapshot.

### OW2 — Readiness chip so "Đã nạp BOM" stops lying after batch Tính
After "Tính tồn tất cả", a guard-blocked sheet keeps the badge "Đã nạp BOM", so the
operator thinks the batch never ran. Add a read-only chip next to the badge stating the
computed block reason.
- **Grounding:** BACKLOG ST1 (`.ai/BACKLOG.md:703`); `calculated_sheet_status` holds a
  blocked sheet at `bom_loaded` (`app/routers/co_case.py:2038`); all flags
  (`lvc_allocation_shortage` / `lvc_missing_price` / `lvc_declarable_unmatched` /
  `missing_bom` + `origin_lock_block_reason`) already exist per-product. ADR 2026-07-11
  explicitly blessed a readiness chip and rejected a status-enum refactor.
- **Effort:** S
- **Main risk:** must render from existing context only and NOT change what
  `calculated_sheet_status` returns (the save-route bypass depends on the current enum).

### OW3 — Pre-flight summary before "Chốt tất cả" (re-enable the gated batch flow)
The bulk-lock backend already runs; the button is intentionally gated off. Re-enable it
behind a pre-flight table showing which sheets will lock vs skip and why, so a multi-SP
dossier locks in one reviewed pass instead of sheet-by-sheet.
- **Grounding:** `bulk_lock_route` / `preview_stock_all_route` / `bulk_substitute_route`
  exist and run (`app/routers/co_case.py`, STATUS Next Steps #2 `.ai/STATUS.md:434`); the
  gate is deliberate ("đang xây dựng", commit `834e1da`). Per-product block reasons are the
  same ones OW2 renders.
- **Effort:** M
- **Main risk:** batch lock writes claims across many sheets; the pre-flight must compute
  lock/skip from the exact gate the per-sheet lock uses (`origin_sheet_action_error`), or it
  builds false confidence and a wrong sheet gets locked.

### OW4 — Cross-dossier contention early-warning banner (read-only)
When a sheet is calculated/opened, read the calc-state of other OPEN cases for the same
client and show an advisory banner ("NVL A đang được hồ sơ X dự tính dùng"), so contention
surfaces early instead of as a `StockOverclaimError` at Chốt.
- **Grounding:** BACKLOG D2 (`.ai/BACKLOG.md:246`) recommends exactly this and says fold it
  into the Phase-2 pre-flight, not a new feature. The case-mining shape already exists in
  `build_substitution_history` (`app/substitution_history.py:32`, iterates cases +
  `origin_sheet_states`) — but that path counts only `status=="locked"` sheets
  (`:44`), so the warning needs a new read over draft/calculated sheets, same shape.
- **Effort:** M
- **Main risk:** advisory only, never a hold (a hold would re-create the rejected
  soft-reservation model). Draft state changes constantly, so it must be low-noise and
  cheap or operators ignore it. BACKLOG rates this priority LOW (contention is already safe
  — the Chốt guard blocks the real over-claim).

### OW5 — Reliable source preload with a progress state on case create
Fire the source preload at case-create POST (not only at the shipment GET) and show the
origin tab a "đang nạp dữ liệu nguồn…" state with polling, so the first origin open for a
large client stops hanging synchronously.
- **Grounding:** BACKLOG P1 residual (`.ai/BACKLOG.md:362`, `:395`): preload is best-effort
  background; clicking origin before it finishes eats the full pull. `create_co_case` at
  POST (`app/routers/co_case.py`) already 303s to `co_case_detail`. Reuse the background
  dossier-export poll pattern.
- **Effort:** M
- **Main risk:** adds a loading state to a currently-synchronous render; must surface pull
  errors, not hide them behind a spinner. Overlaps OW1 (OW1 is the reliability fix, OW5 is
  the UX layer on top).

---

## Bucket 2 — Correctness / risk reduction

Framed as the next layer beyond shipped guards (DC3c triple belt, missing-price belts,
schema-version + config-fingerprint forced re-derivation).

### CR1 — Force re-Tính before lock/export on stale or pre-migration sheets
One fix closes two open holes: a sheet can be locked/exported without a forced recalc, so
stale materials reach the CO — either pre-mig-078 rows missing `customs_relevance` (junk
leaks to export) or client edits saved but not recalculated (lock captures old numbers).
- **Grounding:** BACKLOG cross-item finding (`.ai/BACKLOG.md:35`) names DC3b and LK1
  dirty-before-lock as one root; `lock_co_case_origin_sheet` reads the persisted case
  (`app/routers/co_case.py:2264-2272`) and the only re-validation is the StockOverclaim
  pre-check (`:2273`). DC3b (`.ai/BACKLOG.md:24`) and LK1 dirty-before-lock
  (`.ai/BACKLOG.md:670`) are both still OPEN.
- **Effort:** M
- **Main risk:** forcing a recalc at lock changes numbers the user believed final; it must
  be idempotent (same inputs → same output, already proven by
  `test_recalc_stock_source_parity`) and fire only on genuine staleness (a content-revision
  / schema-version mismatch), not on every lock.

### CR2 — Cold-start over-claim guard (Fix F)
Block Chốt (or validate against BCCT directly) when the client has zero materialized stock
rows, so two dossiers cannot both lock the same lot with the overclaim check skipped.
- **Grounding:** BACKLOG D2 Fix F (`.ai/BACKLOG.md:229`); the guard is nested under
  `if snapshot_exists:` (`app/co_stock_ledger.py:198-204`) — with no snapshot it trusts the
  allocator's calculate-time check, which does not lock. A brand-new client that never ran
  Refresh tồn is the trigger.
- **Effort:** S-M
- **Main risk:** blocking lock on an empty snapshot could stop a legitimate first-ever lock;
  the remedy surfaced must be explicit ("Refresh tồn trước khi chốt"), not a silent 409.
  Rare in practice (needs a client that never refreshed).

### CR3 — Delta-vs-full parity harness for co_stock refresh
Add a harness that runs a full re-derivation then a delta on the same source and asserts
identical `co_stock_rows`, to catch the delta path drifting from full over time.
- **Grounding:** BACKLOG D1 (`.ai/BACKLOG.md:20`, `:202`): backstops shipped
  (schema-version `9f38afa`, config-fingerprint `0f0812f`) but the parity harness is still
  listed as remaining, and the standing suspicion is delta silently under/over-applying
  (qty change, non-tombstoned delete, block-by-claims skip).
- **Effort:** M
- **Main risk:** needs a real Postgres backend — file-mode is a false green
  (memory `test-env-filemode-vs-datahub`), so it cannot run in the default suite and needs
  the DB-isolation seam (AG1) to run cleanly.

### CR4 — Surface refresh mode/reason and fix the misleading row-count
Make Refresh tồn report whether it ran full vs delta-N and why, and stop writing the total
source count into `bcct_row_count_at_refresh` on a delta run, so a silent tồn desync
becomes visible to the operator.
- **Grounding:** BACKLOG D1 remaining items E/F (`.ai/BACKLOG.md:207-208`): refresh returns
  `ok:true, rows:0` without distinguishing "nothing new" from "snapshot error", and
  `bcct_row_count_at_refresh` records the total source count even on delta, which can mask
  drift.
- **Effort:** S-M
- **Main risk:** low — mostly a response field + a field-meaning correction; needs a test
  that the count reflects the actual operation.

### CR5 — bang_ke_renderer double-applies FX on legacy rows lacking `_vnd`
Fix the one confirmed money-display defect where a legacy row without a materialized `_vnd`
value gets the FX rate applied twice.
- **Grounding:** BACKLOG B6 nit (`.ai/BACKLOG.md:19`): `app/bang_ke_renderer.py:185`
  double-applies the rate on legacy rows. B6 otherwise CLOSED (the toggle works, missing-rate
  fallback is correct).
- **Effort:** S
- **Main risk:** touches money output; needs a regression test that both legacy (no `_vnd`)
  and current rows render the correct VND, since export == web grid must hold.

*(Lower-confidence, needs a product decision, not ranked:* **CR6** — a blank material name
on a declarable row currently only sets a non-blocking `material_name_missing` warning
(`app/web/co_case_context.py:2645`); whether an empty (2) name cell should join the export
blocker set (mirroring DC3c) is a legal/UX call the user should make first.*)*

---

## Bucket 3 — Agent-operability / codebase health

### AG1 — Test DB schema isolation + teardown in conftest
Give DB-backed tests their own schema and drop it on teardown, so agents can run the real
backend without polluting the shared dev `co` schema and without file-mode false greens.
- **Grounding:** BACKLOG T1 (`.ai/BACKLOG.md:412`); `tests/conftest.py` (18 lines) isolates
  only `DATA_HUB_CONFIG_PATH` and opts into `CO_ALLOW_LOCAL_SOURCE` — no
  `BARRY_DATABASE_SCHEMA`, no migrate/drop-cascade. BACKLOG records 845 growatt cases piled
  into the dev DB in ~4 weeks from unclean test runs.
- **Effort:** M
- **Main risk:** must first classify which tests create vs read seed data (BACKLOG T1 note);
  a wrong conftest change breaks the whole suite. Enables CR3 (parity harness needs a clean
  DB).

### AG2 — Make the export == web-grid invariant executable
The "export is a pure renderer of the web grid, no logic in export" rule is enforced today
only by convention and memory. Pin it with a test that feeds one materialized product dict
to all three export renderers plus the web-grid builder and asserts identical output.
- **Grounding:** memory `bangke-export-equals-web-invariant` (HARD rule); three renderers
  (`app/bang_ke_renderer.py`, `app/workbook_io.py`, `app/bang_ke_xml_generator.py`) each
  read materialized fields. An agent could easily add a computation in one renderer and
  silently break export/web parity — the highest-blast-radius convention with no test.
- **Effort:** M
- **Main risk:** building a representative fixture (rows with folds, splits, VN-origin,
  declarable_unmatched) is the work; an under-specified fixture gives false safety.

### AG3 — Data Hub client seam: thread-safe caches + a first-class test fake
Make the module-level DH caches thread-safe and ship a documented in-process fake DH client
as a test double, so OW1's threaded pulls are safe and DH-dependent tests become hermetic.
- **Grounding:** `app/data_hub_client.py` (1360 lines) is the single enforced DH boundary
  (`tests/test_data_hub_policy.py`); caches `co_case_source_context_cached` /
  `co_case_material_catalog_cached` are module-level. Memory
  `co-deployed-e2e-incontainer` already stubs the client ad-hoc to skip DH auth — formalize
  that stub.
- **Effort:** M
- **Main risk:** cache locking can add contention on the hot path; the fake must track the
  real contract or tests pass against a fiction. Direct prerequisite for OW1.

### AG4 — Split the two ~3.5k-line domain god-modules into deep modules
`app/web/co_case_context.py` (3905 lines / 195k) and `app/routers/co_case.py` (3432 lines /
171k) hold most of the domain logic; every edit loads the whole file and risks unrelated
churn. Extract the existing function clusters (origin-sheet context, co_stock preview,
allocation pool, VN-origin resolver, column-9 materialization) into cohesive modules behind
narrow interfaces.
- **Grounding:** the import line in `routers/co_case.py` pulls ~50 names from
  `co_case_context` in a single `from ... import` — direct evidence the module is a
  grab-bag, not a deep module. Backlog line refs routinely land in the 2000-3900 range of
  both files.
- **Effort:** L
- **Main risk:** a large mechanical refactor across the hottest path; it must be a pure move
  + re-import with zero behavior change, gated by the full suite plus the identity/parity
  invariant tests (`test_code_identity_invariants.py`, `test_recalc_stock_source_parity`).
  Do it in small commits (per the request-refactor-plan pattern), never one big diff.

### AG5 — Break up `co_case.html` (6750 lines) into per-step partials + external JS
The single template holds the whole case UI and its inline JS; backlog line refs routinely
point at `co_case.html:5687`, `:6018`. Split into Jinja partials per workflow step and move
inline handlers to static JS files.
- **Grounding:** `app/templates/co_case.html` is 6750 lines; inline handlers like
  `initOriginProposeBom` (`:5687`) and the wizard "BOM #N" render (`:6018`) are buried deep.
- **Effort:** L
- **Main risk:** template include ordering and JS scope (globals attached in `base.html`,
  e.g. `coToast`); a pure structural move gated by the existing browser e2e. Lower priority
  than AG4 (the Python god-modules carry the correctness logic).

---

## TOP 5 across all buckets

1. **CR1 — Force re-Tính before lock/export on stale/pre-mig sheets** (M): closes DC3b +
   LK1 dirty-before-lock in one fix — the two remaining ways a wrong CO (junk rows or stale
   LVC) can ship.
2. **OW1 — Offload heavy DH pulls off the async event loop** (M): stops one operator's cold
   open from freezing every other request on the instance; already scoped as STATUS H2.
3. **AG1 — Test DB schema isolation + teardown in conftest** (M): lets agents run the real
   DB backend safely, ends dev-DB cruft, and unblocks the parity harness (CR3).
4. **CR2 — Cold-start over-claim guard** (S-M): block Chốt with no materialized snapshot —
   closes the last real over-claim path (Fix F).
5. **OW2 — Readiness chip after batch Tính** (S): cheap, ADR-blessed, removes the daily
   "did the batch run?" confusion when a sheet is calculated-but-blocked.
