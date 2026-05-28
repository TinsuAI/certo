# Audit: Case / Sheet / Stock state machine

Date: 2026-05-28
Author: research pass on `main` @ e4888cd
Scope: Hồ Sơ (case open/close), Sheet (chốt tính toán), Tồn (giữ / nhả) — verify invariants and find drift before code changes.

This is an audit only — no code is being modified. Recommendations at the end need approval before implementation.

---

## 1. Three state machines

### 1.1 Case status (`case.status`, persisted in `co_case_states.payload.cases[].status`)

```
                 +-----------+
   create  ----> |   open    | <----+
                 |  ("")     |      |
                 +-----+-----+      |
                       |            |
   POST /close         | (status="completed")
   only if every sheet |            |
   is "locked"         v            |
                 +-----------+      |
                 | completed |      |
                 |  (∈ CCS*) |------+ POST /reopen-case
                 +-----------+        sets status="open"

* CCS = COMPLETED_CASE_STATUSES = {completed, done, finished, submitted, closed}
```

Sources:
- `app/co_case_store.py:28` — `COMPLETED_CASE_STATUSES`.
- `app/co_case_store.py:31` — `CaseClosedError(ValueError)`.
- `app/co_case_store.py:96-106` — central close-gate inside `update_case_record`.
- `app/main.py:175-178` — FastAPI handler maps `CaseClosedError → 409`.
- `app/main.py:6190-6239` — `POST /close`.
- `app/main.py:6242-6253` — `POST /reopen-case`.

Note: persistence side does not validate the status string; any text that hashes into `COMPLETED_CASE_STATUSES` is treated as closed. Reopen always lands on literal "open".

### 1.2 Sheet lock status (per product, `case.products[*].origin_sheet_status`, persisted in `case.origin_sheet_states[code].status`)

Vocabulary: `draft → calculated → locked` with a recoverable `stale` rung and an unused `calculating` rung.

```
                       (initial)
                          |
                          v
   +------------------>+-------+
   |                   | draft |
   |                   +---+---+
   |                       |  POST /origin/sheet/{code}/calculate
   |                       |  (acquires origin_calculation_lock,
   |  mark_origin_sheets_  |   clears material_overrides,
   |     stale (any save   |   sets status="calculated")
   |     after a sheet     v
   |     ahead of it) +-----------+ <----+
   |  <------+--------|calculated |      |
   |         |        +-----+-----+      | POST /origin/sheet/{code}/reopen
   |         |              |            | (releases ledger claims,
   |   +-----+-+            |            |  status -> "calculated")
   +-->| stale |            |  POST /origin/sheet/{code}/lock
       +-------+            |  (record_sheet_lock writes claims,
                            |   pre-check vs co_stock_rows)
                            v            |
                       +--------+        |
                       | locked +--------+
                       +--------+
```

Sources:
- `app/main.py:124-130` — labels.
- `app/main.py:2787-2924` — `attach_origin_sheet_states` derives gates `origin_can_calculate / _lock / _reopen` and sequence reasons.
- `app/main.py:2942-2956` — `mark_origin_sheets_stale` cascades any-`draft`+ to "stale" forward.
- `app/main.py:3033-3067` — `origin_sheet_action_error` (server pre-check).
- `app/main.py:6318-6480` — calculate + lock endpoints.
- `app/main.py:7309-7368` — reopen-sheet endpoint.
- `"calculating"` exists in `ORIGIN_SHEET_STATUS_LABELS` but no code path ever assigns it (see Gap 7).

### 1.3 Stock claim status (`co_stock_claims.status`)

```
                (no row)
                    |
                    | record_sheet_lock
                    | (one row per (case, sheet, source_row, mat_idx))
                    | claim_id = sha256(case|sheet|source_row|mat_idx)[:16]
                    | DB CHECK: status in ('locked','released')
                    v
              +----------+
              |  locked  | <----+
              +-----+----+      | re-lock of same sheet:
                    |           | UPSERT replaces qty+key in place,
   record_sheet_    |           | status back to 'locked',
   release          |           | released_at -> NULL
                    v           |
              +----------+      |
              | released +------+ (re-lock against same claim_id)
              +----------+
```

Sources:
- `db/migrations/007_co_stock_ledger.sql:6-18` — table; CHECK constraint `status in ('locked','released')`.
- `db/migrations/010_co_stock_claims_lot_key.sql` — adds `declaration_no/line_no/customs_code` (back-fill defaults to empty string).
- `app/co_stock_ledger.py:54-56` — `claim_id_for(case_id, sheet_product_code, source_row, material_index)`.
- `app/co_stock_ledger.py:66-281` — `record_sheet_lock` (idempotent re-lock, availability pre-check, audit events).
- `app/co_stock_ledger.py:284-332` — `record_sheet_release` (UPDATE to 'released', audit events).

There is no "expired" status. The comment at the top of `co_stock_claims.html` template hint references it, but no expiry path exists; the only transitions are `(none) → locked → released → locked → ...`.

There is also no record of claims being released on case-close, case-reopen, or case-delete. The only release trigger is `POST /origin/sheet/{code}/reopen`.

---

## 2. Cross-state invariants

Severity: ✅ = enforced uniformly, ⚠️ = enforced but with gaps, ❌ = missing/weak.

| # | Invariant | Enforced where | Layer | Status |
|---|-----------|----------------|-------|--------|
| I1 | A closed case rejects every mutating route. | `update_case_record` (`co_case_store.py:101-106`), `CaseClosedError → 409` handler (`main.py:175-178`), template banner (`co_case.html:460`), Đóng/Mở lại button visibility (`co_case.html:1529-1551`). | Server (centralized) + UI gate + 1 inline check at `upload_supporting_file` (`main.py:5934`). | ✅ |
| I2 | Case can only close when every product sheet has `origin_sheet_status='locked'` AND ≥1 product. | `POST /close` (`main.py:6205-6224`); button `disabled` gate (`co_case.html:1543`). | Server + UI. | ✅ |
| I3 | Case re-close (already-closed) is a no-op redirect, not a state mutation. | `main.py:6198-6203` (`co_case_is_completed` short-circuit). | Server. | ✅ |
| I4 | On close, release the `origin_calculation_lock` if this case holds it. | `main.py:6230-6235` (best-effort, swallows exceptions). | Server (only). | ⚠️ See Gap 4 (silent failure path). |
| I5 | Locking a sheet must write claims atomically; on overclaim, no claim is written and case state is unchanged. | `main.py:6438-6464` (record before case mutation, `StockOverclaimError` returns 409 before `update_case_record`). | Server. | ✅ (regression test `tests/test_co_demo.py:3516-3608`). |
| I6 | Reopening a sheet must release claims atomically; on ledger failure, sheet stays `locked`. | `main.py:7333-7354` (ledger first, only set status to `calculated` after success). | Server. | ✅ |
| I7 | A sheet's "calculate" / "lock" / "reopen" buttons obey forward-only ordering (no leapfrog; reopen only from last locked). | `attach_origin_sheet_states` (`main.py:2890-2921`) sets `origin_can_*` + `*_block_reason` on each product; server side `origin_sheet_action_error` (`main.py:3033-3067`) enforces; template wires `disabled` from `origin_can_*` flags. | Server + UI. | ✅ |
| I8 | Locked sheet rejects material add / delete / substitute. | Server: `update_case_record → CaseClosedError` only fires on closed-case, NOT on locked-sheet; per-route enforcement is implicit (sheet status is `locked` → calculate/lock/reopen blocked, but other endpoints like material-override aren't guarded). UI: `disabled` + JS early-return on locked panel (`co_case.html:1296-1473`, JS `sheetIsLocked`). | Mixed: UI + JS. | ⚠️ See Gap 1. |
| I9 | `co_stock_claims.claim_id` is deterministic from `(case_id, sheet_product_code, source_row, material_index)`. | `co_stock_ledger.py:54-56`. Re-lock idempotency relies on this. | Code. | ✅ Implicit but no DB UNIQUE on the tuple to back it up. |
| I10 | Materializer refresh never deletes a `co_stock_rows` row that still backs a locked claim. | `co_stock_materializer.py:237-251` (`_claims_blocking_removal` filters out claimed lots). | Server. | ✅ (commit `ca368cd` option B). |
| I11 | Materializer refresh in `delta` mode never deletes untouched rows. | `co_stock_materializer.py:104-110`. | Server. | ✅ |
| I12 | A case can only be deleted if it (a) is not completed AND (b) doesn't hold the origin_calculation_lock. | `co_case_store.py:151-156`. | Server. | ⚠️ See Gap 2 — locked claims are NOT a delete blocker. |
| I13 | `origin_calculation_lock` is per-client, single-holder, with 60-min TTL. | `co_case_store.py:172-223`. | Server. | ✅ (test `test_origin_calculation_lock_blocks_parallel_cases_for_same_client`). |
| I14 | Closed case is not allowed to re-acquire the calculation lock or write claims. | Implicit via I1 — every endpoint that takes the lock or writes claims funnels through `update_case_record` for the final state save, which trips `CaseClosedError`. | Server (indirect). | ⚠️ Lock could still be acquired *before* the gate hits (`main.py:6344` vs save). |
| I15 | Closed case keeps sheet status as-is on reopen-case (locked sheets stay locked, claims stay locked). | Behavior of `reopen-case` (`main.py:6242-6253`) which only flips status to "open" and does not touch sheets/claims. | Server. | ✅ Intended; documents the round-trip. |
| I16 | `co_case_states` writes are atomic per-client. | `case_lock` fcntl in `co_case_store.py:911-921` for file mode; Postgres mode (`workflow_state_store.py:297-345`) is single-statement INSERT…ON CONFLICT. | Server. | ⚠️ See Gap 3 — Postgres `save_state` has no row version / no optimistic concurrency. |

---

## 3. Triggers — endpoint → target state → side effects

| Trigger (route) | Case | Sheet | Claims | Calc-lock |
|---|---|---|---|---|
| `POST /co-case/create` | new (open) | — | — | — |
| `POST /co-case/{id}/shipment` etc. | unchanged (rejects if closed via I1) | — | — | — |
| `POST /co-case/{id}/supporting-files` | unchanged (rejects if closed via I1, explicit check) | — | — | — |
| `POST /co-case/{id}/origin/save` | unchanged (rejects if closed) | calls `mark_origin_sheets_stale(stale_from_index)` → forward sheets `calculated/locked → stale` | — | — |
| `POST /co-case/{id}/origin/autosave` | unchanged | always `mark_origin_sheets_stale` | — | — |
| `POST /co-case/{id}/origin/sheet/{code}/calculate` | unchanged | target → `calculated`, forward sheets → `stale`, clears `material_overrides` for the target | — | acquires (this case) |
| `POST /co-case/{id}/origin/sheet/{code}/lock` | unchanged | target → `locked` (only if `calculated`, only if no `previous_unlocked`) | inserts/replaces claims for the sheet; aborts on `StockOverclaimError` | — |
| `POST /co-case/{id}/origin/sheet/{code}/reopen` | unchanged | target → `calculated` (only if last `locked`) | releases all claims for the sheet | — |
| `POST /co-case/{id}/close` | open → `completed` (only if all sheets locked + ≥1 product) | unchanged | unchanged (claims stay `locked`) | releases (if this case holds it) |
| `POST /co-case/{id}/reopen-case` | `completed → open` (no precondition checks) | unchanged (sheets stay locked) | unchanged | — |
| `POST /co-case/{id}/origin-lock/release` | unchanged | calls `mark_origin_sheets_stale(0)` → all sheets → `stale` (or stays draft) — even locked sheets get flipped to `stale`! See Gap 6 | unchanged | releases (always) |
| `POST /co-case/{id}/delete` | row purged (only if not completed AND doesn't hold calc-lock) | rows purged with case | **NOT purged — orphan claims remain** (Gap 2) | — |
| `POST /clients/{cid}/evaluate` | unchanged | target → recalculated in-memory | — | acquires (this case) |
| `POST /clients/{cid}/refresh-co-stock` (materializer) | — | — | claimed lots survive refresh (Gap 10 candidate) | — |

---

## 4. Identified gaps / loose ends

### Gap 1 — Locked-sheet material edits are UI-gated only (HIGH)
`I8` is enforced in the template (`co_case.html:1296-1473`) and JS (`sheetIsLocked`), but the *server-side* material-override endpoints (substitute, add-row, delete-row, manual override) do not call `origin_sheet_action_error` to refuse mutations when the sheet is `locked`. A dev-tools user (or an attacker with the case URL) can POST overrides directly and the server will accept them, leaving the claim qty out of sync with the persisted material list.

Where the holes are (search `update_case_record` calls around `origin/material` / `origin/recommendation` etc.):
- `main.py:6877`, `6943`, `7022`, `7072`, `7289` — all `update_case_record` on the sheet without a "sheet not locked" pre-check. They typically flip the sheet to `stale`, but that does NOT release the existing claims; result: claims pinned to the *old* allocation while UI shows different materials.

Layered defense gap: server should check sheet `locked` state and 409 the request, OR the route should auto-release claims (effectively a sheet-reopen). The current behavior silently desyncs.

### Gap 2 — `delete_case_record` leaves orphan claims (HIGH)
`co_case_store.py:133-148` blocks delete on (case completed) or (case holds calc-lock), but never queries `co_stock_claims`. A user with `co_case:delete` role can delete an open case whose sheets are locked; the rows in `co_stock_claims` stay with `status='locked'` pointing at a `case_id` that no longer exists.

Downstream effect:
- `co_stock_ledger.used_qty_by_lot` still counts those qty as consumed, reducing `remaining_qty` for every other case forever.
- Materializer `_claims_blocking_removal` still blocks BCCT lot removal because of these phantom claims.
- `co_stock_claims_client_case_idx` becomes a small leak that an audit query can't unlock without a manual SQL delete.

Same hole exists for the close-case path if we ever choose "delete after close": today close keeps claims (intentional — see Gap 5 discussion below).

### Gap 3 — `co_case_states` Postgres write is last-write-wins (HIGH — already known)
`workflow_state_store.py:297-317`: `save_state` does `INSERT … ON CONFLICT (client_id) DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()` with no version comparison. Two operators editing two different cases for the same client at the same time will overwrite each other, because the entire `cases` array is replaced wholesale.

The file-backed store mitigates this with `fcntl.flock` (`co_case_store.py:911-921`), but the Postgres store has no equivalent. The unit-of-write is the whole client payload, not a single case. This is the "concurrent edit on co_case_states" issue the user already flagged.

Mitigation candidates: optimistic concurrency on `updated_at`, per-case rows instead of one JSONB blob, or row-level locks. Picking one is out of scope for this audit but the read-modify-write hazard is real for any client with ≥2 simultaneous operators (which is the demo's primary use case).

### Gap 4 — Close-case lock-release swallows exceptions silently (MED)
`main.py:6230-6235`:
```python
try:
    existing_lock = active_origin_calculation_lock(client)
    if existing_lock and existing_lock.get("case_id") == case_id:
        release_origin_calculation_lock(client, case_id)
except Exception:  # noqa: BLE001 — lock release is housekeeping
    pass
```
A genuine release failure means the case is now `completed` but the calc-lock still belongs to it. Since closed cases can no longer save state through `update_case_record`, the operator now has a stuck lock that won't expire until the 60-min TTL. There is no observability / log line on this code path.

### Gap 5 — Closed case keeps claims locked, but no surface tells the operator (MED)
The audit deliberately keeps claims `locked` on close so the consumed qty is honored against other cases. That is correct (a "submitted" CO has consumed its material). But:
- There's no API/UI affordance to say "this closed case is the reason lot X is depleted".
- `claims_for_case` exists (`co_stock_ledger.py:383-403`) but is not wired into the close-case view or the Tồn CO sync banner.
- If the operator deletes a closed case (currently blocked by I12) we'd hit Gap 2.

Risk: when a closed case is reopened (`reopen-case`) and the operator unlocks a sheet, the claim release works (Gap is small). But if the close was a mistake and they want to retract, today there's no "release everything" affordance.

### Gap 6 — `origin-lock/release` clobbers locked sheets to `stale` (MED)
`main.py:6256-6268`: `mark_origin_sheets_stale(case, 0)` is called on the case before saving. `mark_origin_sheets_stale` (`main.py:2942-2956`) only re-stales non-`draft` sheets, so locked sheets become `stale` — but **claims are NOT released** (only `/origin/sheet/{code}/reopen` releases claims).

Result: a manual "nhả phiên tồn" click can leave the case in a "sheet displayed as stale, but ledger still claims qty" state. The cross-case "remaining_qty" calculation will still subtract this case's qty, while the operator believes the sheet is open for re-calculation.

Reproduction: lock a sheet, then click the calc-lock release banner on /co-case index. Check `co_stock_claims` — still locked.

### Gap 7 — Unused / undefined statuses (LOW)
- `"calculating"` exists in `ORIGIN_SHEET_STATUS_LABELS` (`main.py:127`) but no code path ever assigns it. Dead enum entry; remove or wire it (the sheet-action gate at `origin_sheet_export_blockers` does mention it at `main.py:3028`).
- `"reopen"` is accepted by the close-gate carve-out (`co_case_store.py:103`) but no endpoint sends `status="reopen"`; only `"open"` is sent. Dead carve-out; tighten to `"open"` only.

### Gap 8 — Sheet ordering check is by `case.products` list order, not domain order (LOW)
`attach_origin_sheet_states` derives `previous_unlocked` and `later_locked` from index in `products[]`. If the operator reorders the products in BOM (or if `origin_product_order` differs from `products` order), the "lock the previous sheet first" requirement diverges from the display order. Today the two are kept in sync by `merge_origin_action_payload`, but it's load-bearing in a way that is easy to break.

### Gap 9 — No DB UNIQUE backstop for `(client_id, case_id, sheet_product_code, source_row, material_index)` (LOW)
The primary key is `claim_id` (sha256). Idempotency on re-lock is implemented entirely in app code by the `DELETE WHERE (client, case, sheet)` + `INSERT … ON CONFLICT (claim_id)` pair (`co_stock_ledger.py:205-228`). If two requests race the same lock (e.g., AJAX double-submit), they could both pass the delete, both insert, and then `ON CONFLICT` collapses them — but the `record_sheet_lock` is wrapped in a single connection transaction, so the practical risk is small. Recommend a unique index on `(client_id, case_id, sheet_product_code, source_row, material_index)` as documentation + defence.

### Gap 10 — No claim-expiry sweeper (LOW)
The state machine `(none → locked → released → locked → …)` has no time-based release. If a case is created, sheet calculated, sheet locked, then the operator vanishes, the claim sits forever. The 60-min TTL on `origin_calculation_lock` does not apply to claims — only to the "currently-editing" lock.

For the demo this is acceptable, but it should be on the radar: a stuck claim from an abandoned case looks identical to an active claim from a closed case (Gap 5).

### Gap 11 — Semantic confusion across the three lock concepts (LOW — naming)
The codebase / UI uses several near-synonyms:
- `origin_calculation_lock` (per-client, TTL, "I'm currently editing")
- `origin_sheet_status='locked'` (per-sheet, "finalized")
- `co_stock_claims.status='locked'` (per-lot, "consumed by this sheet")
- "đóng hồ sơ" (case closed, ≠ any of the above)
- "chốt" (sheet locked, also "ledger locked")

The UI surfaces "Đang giữ tồn / Nhả phiên" (calc-lock), "Chốt / Mở chốt" (sheet), "Đóng / Mở lại hồ sơ" (case). Operators have reported confusion (the original "đóng vẫn sửa được" bug fixed in `c7f24d5`). Not a state-machine bug, but the naming makes auditing harder.

---

## 5. Recommendations (prioritized)

| Pri | Rec | Rationale | Blast radius |
|---|---|---|---|
| HIGH | **R1.** Add a server-side `sheet_locked` pre-check to every endpoint that mutates `case.products` (material override, substitute, add/delete row, recommendation override). Reuse `origin_sheet_action_error(case, code, "edit")` or equivalent. | Closes Gap 1. Today the lock is UI-only; an operator who reloads with stale JS or a malicious POST can bypass. | 5–8 endpoints in `main.py` around lines 6877, 6943, 7022, 7072, 7289. Add 1 regression test per endpoint. |
| HIGH | **R2.** Block `delete_case_record` when any claim is `status='locked'` for the case (or auto-release them in the same txn). | Closes Gap 2. Today delete leaves orphan claims. | `co_case_store.py:133-156` + `co_case_delete_block_reason`. Need a thin DB read of `co_stock_claims`. 1 test. |
| HIGH | **R3.** Add optimistic concurrency to Postgres `co_case_states.save_state` (compare-and-swap on `updated_at` or add `version int`). | Closes Gap 3. Today multi-operator demo runs can silently overwrite. | `workflow_state_store.py:297-345`; `co_case_store.save_state` callers. Needs schema migration + retry on conflict in `update_case_record`. Larger change, but the known issue. |
| MED | **R4.** Make `/close` calc-lock release surface failures (log + return 409 if release fails). | Closes Gap 4. Stuck lock after a successful close leaves the workspace unusable for 60 min. | `main.py:6229-6235`. Trivial. |
| MED | **R5.** Decouple "release calc-lock" from "stale all sheets" in `origin-lock/release`. Release calc-lock without rewriting sheet states. | Closes Gap 6. Current behavior stales locked sheets without releasing claims. | `main.py:6256-6268` — drop the `mark_origin_sheets_stale` call (or change it to a pure no-op when the case has any locked sheet). |
| MED | **R6.** Surface "this lot is held by a closed case" in the Tồn CO row detail + add `claims_for_case` to the closed-case review page. | Mitigates Gap 5. Gives operators visibility into why a depleted lot stays depleted. | Read-only template wiring, no migration. |
| LOW | **R7.** Remove `"calculating"` from `ORIGIN_SHEET_STATUS_LABELS` and the `"reopen"` carve-out from `update_case_record`. | Closes Gap 7. Dead code. | `co_case_store.py:103`, `main.py:127`. Tiny. |
| LOW | **R8.** Lock the canonical sheet order to `origin_product_order` (or `products[]` — pick one) and assert at the top of `attach_origin_sheet_states`. | Closes Gap 8. Defensive. | `main.py:2787-2924`. |
| LOW | **R9.** Add `UNIQUE (client_id, case_id, sheet_product_code, source_row, material_index)` index on `co_stock_claims`. | Closes Gap 9. Belt-and-braces on the sha256 PK. | 1 new migration file. |
| LOW | **R10.** Add a periodic sweeper or a manual "release claims for case X" admin endpoint. Out of scope for now; track in `.ai/STATUS.md`. | Closes Gap 10. Operational hygiene. | New endpoint or cron; depends on scheduling story. |
| LOW | **R11.** Rename one of the three locks in the codebase or add a `docs/state-machines.md` glossary so future audits don't have to do this work. | Closes Gap 11. Pure ergonomics. | Docs-only or a search-and-replace. |

---

## 6. Test gaps

### Coverage today
- `tests/test_case_close_gate.py` — `case_from_record` propagation, `co_case_is_completed`, `CaseClosedError` inheritance. 3 tests, all unit-level.
- `tests/test_co_demo.py:3380-3608` — end-to-end ledger lock/release (`test_origin_sheet_lock_writes_ledger_claims`) + over-claim rejection (`test_origin_sheet_lock_rejects_overclaim_against_materialized_snapshot`). Postgres-required; skips otherwise.
- `tests/test_co_demo.py:5167+` — calc-lock cross-case parallel blocking + release.
- `tests/test_co_stock_materializer_diff.py` — UPSERT classification, `_DIFF_IGNORED_PAYLOAD_KEYS`, `_claims_blocking_removal` (the option-B refresh path).

### What's missing (mapped to recommendations)

| Missing test | Maps to |
|---|---|
| `POST /co-case/{id}/close` happy path → status, calc-lock released, claims preserved. | I2, I4, R4 |
| `POST /close` rejects when any sheet is `calculated`/`draft`/`stale`. | I2 |
| `POST /close` is idempotent (re-click is a 303 not a 409). | I3 |
| `POST /reopen-case` → reopened case can mutate again; sheet status preserved; calc-lock not re-acquired. | I15 |
| `POST /co-case/{id}/origin/sheet/{code}/material/*` (substitute, add, delete, override) rejected when sheet is locked. | Gap 1 / R1 — currently no test, currently no enforcement. |
| `POST /co-case/{id}/delete` blocked when any locked claim exists. | Gap 2 / R2 |
| Two concurrent `update_case_record` writes to two different cases of the same client → both persist. | Gap 3 / R3 (currently expected to fail) |
| `POST /origin-lock/release` does NOT clobber a locked sheet's status to `stale`. | Gap 6 / R5 (currently expected to fail) |
| `materializer refresh` after a closed case → claimed lots are still in `blocked_lots`. | I10 (likely passes, but no explicit test) |
| `record_sheet_lock` with duplicate alloc rows (race) → only one claim survives. | Gap 9 / R9 |

### Suggested test file layout
- Add `tests/test_close_reopen_lifecycle.py` for the close/reopen happy + edge paths (I2–I6, R4, R5).
- Extend `tests/test_co_demo.py` with the delete-blocked-by-claims regression (R2) and the locked-sheet edit-blocked regression (R1).
- Add `tests/test_co_case_state_concurrency.py` to encode the Gap 3 hazard (will currently fail; this is the user's call whether to land as `xfail` or to gate R3 on it).

---

## Appendix A — File:line index for fast navigation

- Close gate: `app/co_case_store.py:96-106`
- Close-case route: `app/main.py:6190-6239`
- Reopen-case route: `app/main.py:6242-6253`
- Calc-lock release route: `app/main.py:6256-6268`
- Lock-sheet route: `app/main.py:6411-6480`
- Reopen-sheet route: `app/main.py:7309-7368`
- `attach_origin_sheet_states`: `app/main.py:2787-2924`
- `origin_sheet_action_error`: `app/main.py:3033-3067`
- `record_sheet_lock`: `app/co_stock_ledger.py:66-281`
- `record_sheet_release`: `app/co_stock_ledger.py:284-332`
- Materializer refresh: `app/co_stock_materializer.py:38-135`
- Claims-blocking removal: `app/co_stock_materializer.py:237-251`
- Postgres `save_state`: `app/workflow_state_store.py:297-345`
- File-store lock: `app/co_case_store.py:911-921`
- Migration 007 (claims table + check constraint): `db/migrations/007_co_stock_ledger.sql`
- Migration 010 (lot-key cols): `db/migrations/010_co_stock_claims_lot_key.sql`
- Close-case template + buttons: `app/templates/co_case.html:460-465, 1487-1551`
- Sheet lock/reopen buttons + ordering UI: `app/templates/co_case.html:954-1014, 1296-1473`
