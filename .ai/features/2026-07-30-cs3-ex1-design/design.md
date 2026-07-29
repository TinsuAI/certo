# CS3(a) + CS3(b) + EX1 — Design

**Date:** 2026-07-30 · **Type:** design (spec only, no app-code changes) · **Depends on:** settled
3-source harmonization (`.ai/DECISIONS.md` 2026-06-14/15; `.ai/features/2026-06-14-cs3-costock-three-sources/brief.md`).

## Settled model this builds on (do NOT re-open)

Three sources own three quantities, orthogonal, no field contention:

| Source | Owns | Written to |
|---|---|---|
| DH BCCT | `opening` (customs number) | `opening_qty`, `baseline_used_qty = 0` |
| Import workbook | off-app remaining @T → `baseline_used = opening − remaining` | `baseline_used_qty`, `remaining_qty`, `payload.co_stock_source = 'workbook_snapshot'` |
| CO cases | live consumption (claim/lock) | `co_stock_ledger` / `co_stock_claims`, overlaid at read |

`tồn = opening − baseline_used − live_claims` (`co_stock_ledger.apply_used_qty`). With a workbook row,
`= remaining_import − live_claims`. Lot key = `(declaration_no, line_no, customs_item_code)`. Legacy
`fold_baseline` / `co_stock_adjustments` removed 2026-06-15 (mig 017). One materialize path:
`co_stock_materializer.refresh_co_stock_for_client` (UPSERT + targeted DELETE, `app/co_stock_materializer.py:78-189`).

Both CS3 configs are **CO-owned** and live in the `co_stock` section of client config
(`app/client_config_store.py:77-79`; per DECISIONS 2026-07-16, CO owns `co_stock` + `allocation_code`).

---

## CS3(a) — Configurable workbook re-import conflict rule

### Current behavior

Re-import is `POST /clients/{id}/co-stock/import-snapshot` (`app/routers/co_stock.py:314-340`) →
`co_stock_workbook.import_standard_snapshot` (`app/co_stock_workbook.py:396-429`) →
`refresh_co_stock_for_client(..., mode="full")` (`:412-414`). Full mode is REPLACE:

- `_plan_removed_keys(mode="full")` sets `removed = old_keys − new_keys` (`app/co_stock_materializer.py:295-319`).
- `_claims_blocking_removal` keeps any removed lot that still has a `status='locked'` claim
  (`:165-171`, `:321-339`) — orphan-safe, so a claimed lot dropped from the new workbook is NOT deleted.
- **But every lot present in the new derive set is UPSERTed unconditionally** (`:164`, `_upsert_records`
  `:255-292`), including a lot that has an active claim. Its `baseline_used_qty` / `remaining_qty` are
  overwritten with the new @T' workbook figures, and the live claim still overlays at read.

The gap the brief flagged (`brief.md:88-91`): re-import moves cutover T→T'. For a lot CO claimed during
T..T', the new workbook `remaining_import@T'` may already reflect that same consumption (agency also
recorded it in Excel). Re-baselining then re-applying the live claim **double-subtracts** that quantity.
There is no rule today; the de-facto behavior is "workbook wins, claim re-overlays".

### Proposed config

`co_stock.reimport_conflict_policy`, enum, default preserves today's behavior:

- `replace` (default) — current behavior: UPSERT the new baseline for every derived lot, claims overlay.
- `keep_claimed_lots` — for a derived lot that has an active `status='locked'` claim, do NOT re-baseline
  it; keep the existing `co_stock_rows` payload (old `baseline_used`/`remaining`). New/unclaimed lots
  upsert normally. Removes the double-subtract by declining to move cutover on lots CO already owns.
- `abort_on_claimed` — if any lot in the new derive set has an active claim, abort the whole re-import
  with a report of the conflicting lots; operator releases those cases first, then re-imports. Safest for
  a supervised onboarding; no partial state.

### Exact seam

`refresh_co_stock_for_client` already computes `blocked` (claim-holding removed lots) at
`app/co_stock_materializer.py:165`. Extend it to also compute **claimed lots that are in the new set**
(intersection of `new_by_key` keys with active-claim `source_row`s), then apply the policy before/at the
UPSERT:

- Thread a `reimport_conflict_policy` kwarg into `refresh_co_stock_for_client` (default `"replace"` →
  byte-identical to today). Only `import_standard_snapshot` passes a non-default value; DH refresh never
  does (its config knob is CS3(b), separate).
- `replace`: no change to `_upsert_records`.
- `keep_claimed_lots`: filter the record list passed to `_upsert_records` (`:164`) to exclude claimed
  lots, i.e. `records_to_upsert = [r for r in records if r["source_row"] not in claimed_new]`. Report the
  skipped lots in the summary (`rows_kept_by_claim`).
- `abort_on_claimed`: if `claimed_new` non-empty, return early with `summary["aborted_claims"] = [...]`
  and persist nothing — mirror the existing `abort_wipe` early-return shape (`:155-163`).

`import_standard_snapshot` reads `config["co_stock"].get("reimport_conflict_policy", "replace")` and passes
it through. Route surfaces the extra summary fields (`app/routers/co_stock.py:326-340`).

The claim intersection must key on the **semantic lot key** `(declaration_no, line_no, customs_item_code)`,
not raw `source_row`: `stock_rows_from_standard` keys workbook rows differently from a prior DH-derived
snapshot (brief R2), so a `source_row`-only compare can miss a claim sitting on the same physical lot.
`_load_existing_snapshot` already returns per-`source_row` lot-key dicts (`:192-210`); resolve the active
claim's `source_row` to its lot key through that map before intersecting.

### Migration / back-compat

- Config: additive key with a default. `migrate_config` (`app/client_config_store.py:90-107`) already
  overlays `co_stock` over defaults (`:98`), so old configs without the key resolve to `replace`
  automatically. Add the enum to `validate_config` (`:110-112`) next to `lot_policy`. No DB migration.
- Behavior: default `replace` = no change to any existing client. First import (cutover, no claims yet)
  is unaffected by any policy — the rule only fires on re-import over claimed lots.
- Fingerprint: this policy does NOT change derived rows, so it must NOT enter
  `co_config_fingerprint` (would force a needless full re-derive; see DECISIONS 2026-07-16). It is read
  per-import only.

### Risk

- `keep_claimed_lots` leaves a claimed lot on its OLD baseline while the rest of the client moves to T'.
  The lot's `opening`/`remaining` can then disagree with the new workbook for that lot until the case is
  released and a later re-import re-baselines it. Acceptable and intended (CO is system-of-record after
  cutover for claimed lots), but the summary must name each kept lot so the operator sees it.
- `abort_on_claimed` can make re-import feel "stuck" if many lots are claimed; the abort report must list
  lot + case so the operator knows what to release.
- Policy is per-client global; a client can't mix policies per import. Sufficient for current need; no
  per-upload override designed.

### Tests

- `replace` default: re-import over a claimed lot upserts new baseline, claim overlays (locks in today's
  behavior; extend `tests/test_co_stock_workbook.py:271` reimport-replaces test).
- `keep_claimed_lots`: claimed lot keeps old `baseline_used`/`remaining`; unclaimed lots re-baseline;
  `rows_kept_by_claim` reported.
- `abort_on_claimed`: any active claim in the derive set → nothing persisted, conflict list returned,
  existing snapshot intact.
- No-claim re-import: all three policies behave identically (rule dormant).
- Semantic-lot-key match: claim whose workbook `source_row` differs from the DH-era `source_row` for the
  same `(decl,line,customs)` is still detected.
- `migrate_config` default resolves to `replace`; `validate_config` rejects an unknown enum.
- Fingerprint unchanged when only `reimport_conflict_policy` changes (no forced re-derive).

---

## CS3(b) — Loosen `is_workbook_sourced` so DH adds opening for NEW lots

### Current behavior

`app/routers/co_stock.py:353-359`: `POST /co-stock/refresh` early-returns `skipped: "workbook_sourced"`
whenever `is_workbook_sourced(client_id)` is true. That guard is EXISTS-any-one-row
(`app/co_stock_materializer.py:582-597`: one row with `payload.co_stock_source = 'workbook_snapshot'`).
Result: a single workbook lot blocks the **entire** DH refresh for the client — a customs declaration
imported after cutover never flows back into `co_stock_rows` (brief.md:92-94).

The reason the guard is total, not partial: DH refresh runs `refresh_co_stock_for_client` in full/delta
(`app/web/co_case_context.py:3766` delta, `:3794` full). In **full** mode `removed = old_keys − new_keys`
(`app/co_stock_materializer.py:314-319`), so a DH full pull that doesn't contain the workbook's off-app
lots would mark them `removed` and DELETE them (only claim-blocked ones survive). And for a lot present in
BOTH, the DH derive carries `baseline_used_qty = 0`, so its UPSERT would overwrite the workbook's baked
`baseline_used` → wrong remaining. The guard exists to prevent both.

### Proposed loosening

Opt-in, per-client: `co_stock.dh_opening_for_new_lots` (bool, default `false`). When false, the guard
behaves exactly as today (total skip). When true, DH refresh runs in an **additive, DH-owned-only** mode
that (1) adds opening only for lots the workbook does not own, and (2) never touches or removes
workbook-owned lots.

Partition `co_stock_rows` by owner:
- **Workbook-owned** = rows with `payload.co_stock_source = 'workbook_snapshot'`.
- **DH-owned** = every other row (`co_stock_source` absent/`bcct`).

DH refresh, in loosened mode, reconciles ONLY the DH-owned partition, plus inserts genuinely new lots.

### How DH-new-lot opening coexists with workbook-owned remaining WITHOUT double-counting

Per-lot arithmetic at read is `remaining = opening − baseline_used − live_claims` (`apply_used_qty`), and
`co_stock_summary` / the Tồn CO table sum this per lot. Double-counting can only happen if the **same
physical lot** `(declaration_no, line_no, customs_item_code)` appears as two `co_stock_rows` (two
different `source_row` hashes — workbook keys and DH keys differ, brief R2), because then the total adds
both.

The design forbids that by construction:

1. **Disjoint ownership by lot key.** Before UPSERT, drop every DH-derived record whose lot key equals a
   workbook-owned lot key. So a lot the workbook already owns is never re-inserted by DH. DH only inserts
   lots whose `(decl,line,customs)` is absent from the workbook partition — genuinely new declarations
   after cutover.
2. **DH never mutates workbook rows.** The removed-set and the UPSERT-set are scoped to the DH-owned
   partition; workbook rows are invisible to this reconciliation — never updated, never deleted.
3. **Result.** Every lot has exactly one owner and one `co_stock_rows` row:
   - Workbook lot: `remaining = opening_wb − baseline_used_wb − claims = remaining_import − claims`.
   - DH-new lot: `baseline_used = 0`, `remaining = opening_dh − claims`.
   - Total `tồn = Σ_workbook (remaining_import − claims) + Σ_DH-new (opening_dh − claims)`. No lot is in
     both sums → no double count. CO claims still subtract once, on whichever single row owns the lot.

The anti-double-count guarantee holds **iff** the collision filter (step 1) uses the semantic lot key, not
`source_row`. That is the load-bearing rule of this design.

### Exact seam

Two coordinated changes:

1. **Guard (`app/routers/co_stock.py:353-359`).** Replace the unconditional skip with:
   `if is_workbook_sourced(client_id) and not config["co_stock"].get("dh_opening_for_new_lots"): <skip as today>`.
   When the flag is true, fall through to `_refresh_co_stock_delta_or_full(client)` but signal
   owner-scoped mode.

2. **Materializer scoping.** Add a `manage_source` kwarg to `refresh_co_stock_for_client` (default `None`
   = today's whole-client behavior; DH loosened path passes `manage_source="bcct"`). Effects:
   - `_load_existing_snapshot` (`:192-210`) filters to DH-owned rows only when `manage_source="bcct"`
     (`payload->>'co_stock_source' is distinct from 'workbook_snapshot'`). So `old_keys` excludes workbook
     lots → they can never enter `removed`.
   - Before UPSERT (`:164`), drop DH-derived records whose lot key collides with a workbook-owned lot.
     This needs a workbook-owned lot-key set: one query `select import_declaration_no, line_no,
     customs_item_code from co_stock_rows where client_id=%s and payload->>'co_stock_source' =
     'workbook_snapshot'`. Filter records by `(decl,line,customs)` membership.
   - `removed = old_keys(DH-owned) − new_keys(DH-owned, collision-filtered)`. Existing claims-blocking and
     event emission unchanged.

The DH derive callback itself (`co_stock_derivation.co_stock_rows_from_bcct`) is unchanged — it still
derives the full BCCT-based set; the materializer scoping does the partitioning. Both the delta call
(`co_case_context.py:3766`) and full call (`:3794`) pass `manage_source` when the flag is set. In delta
mode the collision filter still applies to added rows; workbook lots can't be tombstoned because tombstone
source_rows come from DH and won't match workbook `source_row`s.

### Migration / back-compat

- Config: additive bool, default `false` → every existing workbook-sourced client keeps today's total
  skip. `migrate_config` overlay handles old configs (`:98`). Add to `validate_config`.
- No DB migration — reuses `payload.co_stock_source` already present on workbook rows and the null/absent
  convention for DH rows.
- `manage_source` default `None` keeps every current caller (tests, first-refresh, non-workbook clients)
  byte-identical.
- Fingerprint: flipping the flag OFF→ON should trigger a DH refresh so new lots appear; ON→OFF is inert.
  Do not add it to `co_config_fingerprint` (that forces a full re-derive of the whole snapshot); instead
  the flag simply gates the guard on the next manual/scheduled refresh.

### Risk

- **Source keying drift.** If a lot is workbook-owned but DH later derives it under a lot key that differs
  by whitespace/format (`line_no` "7" vs "07", customs code prefix), the collision filter misses and DH
  inserts a duplicate row → double count. Mitigation: normalize the lot-key tuple (trim, canonical
  `line_no`) on both sides before comparison; add a test with a formatting-variant lot. This is the single
  highest risk of the design.
- **Ownership flip.** A lot that starts DH-owned and is later imported by workbook (same `(decl,line,
  customs)`) would then exist as a DH row AND get a workbook row on next import unless import-snapshot also
  reconciles against DH-owned rows. Scope note: CS3(b) covers DH-adds-new only; the reverse (workbook
  claims a DH lot) is governed by CS3(a)'s replace/keep policy on the import path and by the disjoint-key
  rule — a workbook import that re-keys an existing DH lot should delete the DH row for that lot. Call this
  out but keep it in the import path, not the DH path.
- **Claims on workbook lots during a DH refresh.** Unaffected — DH reconciliation never sees workbook rows,
  and claims overlay at read regardless of owner.
- **Mixed-state visibility.** Operator can no longer assume "workbook client = no DH". The Tồn CO / refresh
  UI should show per-lot provenance (`co_stock_source`) so a mixed client is legible. UI is out of scope
  here but flagged.

### Tests

- Flag `false`: workbook-sourced client still skips DH refresh (locks today's behavior; guard test).
- Flag `true`, DH derives a NEW lot absent from workbook: lot is inserted, `baseline_used=0`; workbook
  lots untouched (same payload, same `baseline_used`).
- Flag `true`, DH derives a lot that COLLIDES with a workbook lot: DH row dropped, no duplicate, total
  `tồn` unchanged for that lot (no double count) — the core invariant test.
- Flag `true`, DH full pull missing a workbook lot: workbook lot is NOT removed (excluded from `old_keys`).
- Flag `true`, DH delta with a tombstone that matches only a DH lot: DH lot removed, workbook lots stay.
- Claim on a workbook lot + DH refresh: claim still subtracts once; DH does not re-add the lot.
- Lot-key normalization: workbook `line_no="07"` vs DH `line_no="7"` treated as the same lot (no dup).
- `manage_source=None` (all existing callers): behavior byte-identical to current suite.

---

## EX1 — Configurable import-declaration reference format in col K

### Current behavior

`app/bang_ke_renderer.py:294`: `put("import_decl_no", part.get("import_declaration_no", ""))`. `put`
maps the key to a cell via the form config `body.columns` (`:250-254`); `import_decl_no → K` in every
form (`config/bang-ke-forms/*.json`). So col K = declaration number(s) only. The line number is separate:
`import_line_no → O` on wide layouts (CTH/CTSH/RVC/PSR), a hidden helper outside the print area
(`hidden_helper_cols`); LVC has no `import_line_no` column at all.

Template audit (backlog EX1, `.ai/BACKLOG.md:622-632`): `form-mau-combined.xlsx` block is merged
`K12:L13` = K (Số) + L (Ngày) only; "dòng hàng" lives in hidden col O, outside `print_area` (A:N). So col K
is the single visible place a declaration reference can render; the form has no dedicated line column.

Multi-lot joining: a rendered part's `import_declaration_no` and `import_line_no` are each produced by
`bang_ke_rows._joined` (`app/bang_ke_rows.py:66,68` → `:108-114`), which de-dups **each field
independently** with `", "`. Upstream, `co_case_context.py:2704,2712` also `", ".join` per allocation. So
by the time the renderer runs, K holds e.g. `"108097982530, 108097982531"` and O holds `"2, 5"` as two
separately-deduped strings. On the identity fast-path (`bang_ke_rows.py:32-37`) the raw material dict is
returned with those already-joined upstream fields.

Consequence: the number-slash-line format `108097982530/2` **cannot be built by pairing the two joined
strings** — independent de-dup can drop or reorder elements so the zip is unsafe. The pairing must happen
where per-lot allocation lines are still available.

Invariant (memory `bang-ke-export-equals-web-invariant`): the bảng kê export is a pure renderer of the web
grid; all logic lives at Tính, none in the export step. So the format choice must be materialized upstream,
and the renderer only selects which pre-built field lands in K.

### Proposed config

Primary home is **per-client**, CO-owned: a new `bang_ke` section in client config (sibling of `co_stock`).
Field `bang_ke.import_ref_format`, enum `number` (default) | `number_line`. Rationale for per-client over
per-form: form JSON (`config/bang-ke-forms/*.json`) is keyed by criterion and shared across all clients, so
a field there is per-criterion, not per-client; the requirement and DECISIONS 2026-07-16 ownership split put
presentation of a client's declarations at client-config grain. Optional secondary knob
`bang_ke.import_ref_separator` (default `", "`; template mẫu uses `"; "`) covers the multi-lot join
separator the backlog flagged (`:631`).

- `number` — K = declaration number(s) only (today's output, byte-identical).
- `number_line` — K = `declaration/line` pairs, e.g. `108097982530/2, 108097982531/5`.

### Exact seam

Keep the renderer a pure reader. Build a paired field at Tính and let the renderer pick it:

1. **Materialize the paired string upstream, per lot before de-dup.** In `bang_ke_rows.material_render_parts`
   (`app/bang_ke_rows.py:48-78`), where `group_lines` still hold per-lot `import_declaration_no` +
   `import_line_no`, add `"import_decl_ref": _joined_pairs(group_lines, "import_declaration_no",
   "import_line_no", sep)` — a new helper that pairs per line THEN de-dups the pair, so number/line stay
   aligned. Also populate it on the identity fast-path: build the paired field on the material upstream at
   `co_case_context.py:2704/2712` alongside the existing `", ".join`, so the fast-path material already
   carries `import_decl_ref`.
2. **Renderer selects the field by config** (`app/bang_ke_renderer.py:294`):
   `ref = part.get("import_decl_ref") if fmt == "number_line" else part.get("import_declaration_no", "")`
   then `put("import_decl_no", ref)`. The format value is threaded in via the render context — pass the
   client's `import_ref_format` into `render_into_sheet` (it already receives `case`; resolve the client's
   config in the caller and put the resolved format on `case`/`product` at Tính, so the renderer reads a
   ready value, no config lookup in the export step).

Field-selection-by-config is the same pattern the renderer already uses for column mapping (`cols.get`),
so no real logic enters the export step. `number` mode reads the exact field it reads today → unchanged.

### Migration / back-compat

- Config: additive enum, default `number` → every client renders exactly as today. Add a `bang_ke` overlay
  line in `migrate_config` next to the existing `co_stock`/`allocation_code` merges (`:98-99`), and the
  enum check in `validate_config`.
- No template change: `number_line` writes a longer string into the existing K cell, still inside
  `print_area` (A:N). Col O helper is untouched.
- `import_decl_ref` is additive on the part/material dict; nothing reads it unless the format is
  `number_line`, so no other renderer/consumer changes.
- The paired field is derived at Tính; because export is a pure renderer, no persisted case data changes
  format retroactively — a re-Tính (or the field being computed at render-context build) applies the new
  format. Recommend persisting `import_decl_ref` at Tính, consistent with the invariant.

### Risk

- **Pairing correctness.** `_joined_pairs` must pair per line before de-dup; pairing two already-joined
  strings is wrong (independent de-dup misaligns). Lots with a blank `line_no` render `108097982530/`
  (trailing slash) — decide: drop the slash when line is blank, or keep number-only for that lot.
- **Fast-path parity.** The identity fast-path returns the raw material; if `import_decl_ref` is only built
  in the split branch, fast-path rows fall back to number-only silently. Must populate it upstream so both
  paths carry it.
- **Legacy renderer.** `app/workbook_io.py` (legacy path) has its own K/O wiring; if `number_line` must
  apply there too, it needs the same field. Scope: config path (`bang_ke_renderer.py`) is primary; state
  whether legacy is in scope.
- **Separator divergence.** Renderer default `", "` vs template mẫu `"; "` is cosmetic; only change the
  default if a client asks, to avoid churning existing outputs.

### Tests

- `number` default: K byte-identical to current output for LVC and a wide layout (regression lock).
- `number_line`: single lot → `decl/line`; multi-lot → `decl1/line1, decl2/line2` with pairs aligned.
- Blank line_no under `number_line`: chosen fallback (number-only or trailing-slash) is deterministic.
- Fast-path (uniform lots) and split-path (mixed origin) both honor `number_line`.
- De-dup: two allocation lines with identical `(decl,line)` collapse to one pair (no `decl/line, decl/line`).
- `migrate_config` default `number`; `validate_config` rejects unknown enum.
- Custom `import_ref_separator` applied between pairs.

---

## Cross-cutting notes

- All three configs are additive keys with today's-behavior defaults; no DB migration; `migrate_config`
  (`app/client_config_store.py:90-107`) already overlays the `co_stock` section, so old configs are safe.
- None of the three should enter `co_config_fingerprint` unless they change derived `co_stock_rows`
  (only CS3(b) affects rows, and it is gated by the guard, not the fingerprint — see DECISIONS 2026-07-16
  on why `updated_at`-bearing hashes must not drive re-derivation).
- Build test-first (`/tdd`) per the brief. The load-bearing invariants to lock as tests: CS3(b) no-double-
  count on collision (semantic lot key), CS3(a) no double-subtract on claimed re-import, EX1 pure-renderer
  parity for `number`.
