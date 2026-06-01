# Audit: Tồn CO refresh from Data Hub — override + history risks

User question (2026-05-28): "Refresh tồn CO từ Data Hub có làm override các dòng tồn CO đang lưu ở barry-CO không? Có bị mất lịch sử không?"

## TL;DR

**Yes, refresh is destructive.** `refresh_co_stock_for_client()` at
`app/co_stock_materializer.py:38` runs `delete from co_stock_rows where
client_id = %s` followed by a fresh bulk insert. There is **no audit log
entry** for "this refresh changed X rows" — only a count summary in
`co_stock_refresh_state`. Claims, adjustments, and events survive
(separate tables) but may become semantically orphaned if a BCCT row
they reference disappears from the new snapshot.

## What gets touched / preserved

| Table | Refresh wipes? | Why it matters |
|---|---|---|
| `co_stock_rows` | **YES — `DELETE` + `INSERT`** | The snapshot itself |
| `co_stock_refresh_state` | Updated (count + timestamp) | Only metadata, no diff history |
| `co_stock_claims` | No | Locked claims survive — but reference `source_row` |
| `co_stock_adjustments` | No | Operator manual additions preserved |
| `co_stock_events` | No | Audit log — but does NOT log materialization events (no event_type for "snapshot_refresh") |

`source_row` derivation (`source_row = row.import_row_id or import_row_id(row.transaction_key)`)
is stable as long as Data Hub's `transaction_key` is stable. In normal operation
the same BCCT row produces the same source_row across refreshes.

## Concrete risks

1. **Orphaned claims** — If a BCCT row is removed from Data Hub (e.g.,
   declaration corrected/deleted), its `source_row` disappears from the
   refreshed `co_stock_rows`. Active claims in `co_stock_claims`
   referencing that source_row still exist, but pointing to a lot that
   no longer materializes. Release path may fail; export gate may behave
   unexpectedly.

2. **Allocation-code drift** — If `client_config.allocation_code.strategy`
   or `description_regex` changes between refreshes, the same BCCT row
   can map to a different `material_code`. Claims reference
   `source_row` (stable) but the new snapshot's `material_code` for that
   lot may differ from what the case originally recorded.

3. **No "before/after" history** — Only the latest snapshot exists.
   Operator can't ask "what did this row look like before yesterday's
   refresh?". No diff log; no soft-delete; no event entries.

4. **Locked-case blindness** — Refresh proceeds even when other cases
   have active locks on the snapshot. User isn't warned that they may
   be about to detach claims from their lots.

5. **`record_sheet_lock` pre-check is fed by the new snapshot** — the
   stock availability check (`StockOverclaimError` from the recent
   stock-ledger hardening) reads `co_stock_rows`. After a refresh, an
   already-locked sheet's claim may now exceed available_qty (because
   the new snapshot has lower stock for that lot) without the lock
   being revoked.

## Recommendations (not implemented yet)

Pick whichever lands first:

- **Cheap fix — emit snapshot_refresh event** to `co_stock_events`:
  add `EVENT_TYPES = {..., "snapshot_refresh"}` and write one event row
  per refresh with `payload = {rows_persisted, rows_removed, bcct_count,
  config_hash}`. Gives audit trail without changing the materializer's
  destructive design.

- **Pre-refresh warning** — Before `delete from co_stock_rows`, query
  `select count(*) from co_stock_claims where client_id = %s and status = 'locked'`.
  If > 0, return a confirmation prompt to the user listing the affected
  case_ids. Block refresh unless user explicitly confirms with "I
  understand X cases may become orphaned".

- **Orphan detection report** — After refresh, run:
  ```sql
  select claim_id, case_id, source_row
  from co_stock_claims c
  where status = 'locked'
    and not exists (select 1 from co_stock_rows r
                    where r.client_id = c.client_id and r.source_row = c.source_row)
  ```
  Surface results in the response summary so the operator can investigate.

- **Soft-delete + history table** — Bigger lift. Rename current table
  to `co_stock_rows_current` and keep `co_stock_rows_archive` with a
  `snapshot_id` foreign key. Refresh writes a new snapshot_id; old rows
  flagged inactive. Enables diffability and recovery.

## Verification queries

```sql
-- Claims pointing to source_rows that no longer exist
set search_path=co;
select c.case_id, c.source_row, c.material_code
from co_stock_claims c
where c.status = 'locked'
  and not exists (select 1 from co_stock_rows r
                  where r.client_id = c.client_id and r.source_row = c.source_row);

-- Refresh history (only summary records)
select client_id, snapshot_row_count, bcct_row_count_at_refresh, refreshed_at
from co_stock_refresh_state order by refreshed_at desc;
```

## Status

Backlog: needs prioritization against the multi-currency work. Cheapest
mitigation (snapshot_refresh event + pre-refresh claim-count warning)
is a < 1 day change.
