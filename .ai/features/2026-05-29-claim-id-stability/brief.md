# Feature: Claim ID stability (decouple claim_id from BOM order)

## Problem

`claim_id_for(case_id, sheet_product_code, source_row, material_index)`
(`app/co_stock_ledger.py:54`) hashes the material's **positional index** in the
sheet. `material_index` is `enumerate(materials)` from
`record_sheet_lock_claims` (`app/main.py:1402`), so reordering the BOM/sheet
changes the claim_id of physically-identical claims.

## What actually breaks (and what does NOT)

Investigated the lock/release paths before scoping:

- **Stock totals are NOT corrupted by reorder.** Re-lock replaces claims with a
  blanket `DELETE ... WHERE client_id AND case_id AND sheet_product_code`
  then re-insert (`co_stock_ledger.py:205`). Release is keyed the same way.
  Neither keys on `claim_id`, so reorder leaves no orphans and
  `used_qty_by_lot` stays correct.
- **What breaks #1 — audit-event churn (the reported symptom).** On re-lock,
  new claims are matched against prior claims *by claim_id* to suppress no-op
  events (`co_stock_ledger.py:237,264`). After a reorder no claim_id matches,
  so the events store gets a full set of phantom `claim_release` +
  `claim_lock` pairs (net-zero qty, but a misleading consumption history).
- **What breaks #2 — latent under-claim (independent of reorder).** Insert uses
  `on conflict (claim_id) do update set claimed_qty = excluded.claimed_qty`
  — **last-write-wins overwrite, not sum**. Any two allocation rows that hash
  to the same claim_id silently drop one row's qty. Today this can already
  happen when one material has two `allocation_lines` against the same
  `source_row`.

## Scope

In:
- Change claim identity from `material_index` to a stable natural key:
  `(case_id, sheet_product_code, source_row, material_code)`.
- **Aggregate `claimed_qty` by claim_id (sum) before insert**, replacing the
  overwrite semantics. Required: a stable key makes intra-material/lot
  collisions more likely (same material_code across reordered or split BOM
  lines), and summing is the correct disposition — the lot doesn't care which
  BOM line consumed it.
- Keep the `material_index` column populated for audit/display
  (`_row_to_dict`, `claims_for_*`) — only its role in the *identity* is removed.

Out:
- No DB migration. `claim_id` is the lone PK; no other unique constraint
  references it. Existing locked claims carry old-format ids but are replaced
  on their next lock/release cycle (keyed by case+sheet, not claim_id). Stock
  math and queries never parse the id. Document, don't migrate.
- No change to BCCT availability, lot policy, or the over-claim pre-check.

## Decisions

- **Natural key over positional index.** `(source_row, material_code)` within a
  `(case, sheet)` is the real-world identity of a consumption claim.
- **Empty material_code fallback.** `material_code` falls back to
  `internal_material_code` then `""` (`main.py:1403`). When the resolved code
  is empty, fall back to `material_index` in the hash so unnamed materials stay
  distinct. They reacquire reorder-instability, but materials almost always
  carry a code, so this edge is rare and lot totals remain correct via summing.
- **Sum on collision** done in `record_sheet_lock` while building `rows` /
  `new_allocs_by_claim`, so both the insert and the audit-event matcher see the
  aggregated qty consistently.

## Risks

- **Audit-event matcher fields.** Each claim also carries
  `declaration_no/line_no/customs_code`. Summing aggregates rows that share a
  claim_id; those rows should share the same lot declaration line in practice
  (claim is per `source_row`). Verify the matcher still suppresses true no-op
  re-locks after the change (no phantom events on identical re-lock).
- **Test coverage is Postgres-gated.** `test_origin_sheet_lock_records_cross_case_stock_ledger_claims`
  and neighbors skip without `BARRY_DATABASE_URL`. The reorder regression and
  the sum-on-collision behavior need explicit new tests, ideally a pure-unit
  test of `claim_id_for` + the aggregation helper that runs without a DB.

## Open Questions

1. Can one product legitimately list the same `material_code` twice with
   *different* lots? (Yes — different `source_row` keeps them distinct.) Same
   material_code + same lot across two BOM lines → intended to merge+sum?
   Assumed yes.
2. Should we also add a real unique constraint on
   `(client_id, case_id, sheet_product_code, source_row, material_code)` to
   enforce the new identity at the DB layer, or keep it app-only? Leaning
   app-only for now (matches the no-migration scope).

## Recommended next step

`/tdd` — write a DB-free unit test for the new `claim_id_for` (stable under
reorder) + a sum-on-collision test for the aggregation, then implement. Run the
Postgres-gated ledger tests if a DB is available before claiming done.
