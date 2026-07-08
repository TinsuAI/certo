# Session handoff — 2026-07-08 (PM2)

Reviewed the cross-dossier tồn (stock) contention logic for the "multiple dossiers,
same company" question (the NEXT task from the previous handoff), fixed the one
UX-level gap it surfaced (D), and committed the whole `feat/co-flow-guards` branch
(prior #1/#2 + this session's D). Suite **743 pass / 15 skip**.

---

## What this session did

### 1. Cross-dossier contention review (read-heavy, verified in code)
Traced the full stock/claims path and graded each race/contention mechanism:

- **A. Concurrent lock, same lot — CORRECT.** `record_sheet_lock` (`co_stock_ledger.py:150`)
  locks `co_stock_rows … ORDER BY source_row FOR UPDATE` before an availability check
  `net = remaining_qty − Σ(locked claims of OTHER case/sheet)` (`:219-234`, excludes self via
  `not (c.case_id=%s and c.sheet_product_code=%s)`), aborts over-claim (`StockOverclaimError`).
  Stable sort → no deadlock; READ COMMITTED sees the winner's committed claim.
- **B. Preview↔commit (TOCTOU) — CORRECT by design.** Calculate uses
  `_calculate_stock_rows_from_snapshot` → `apply_used_qty(used_qty_by_lot(client_id))`
  (`co_case_context.py:3533`), so preview nets other dossiers' LOCKED claims; the lock guard
  re-checks under FOR UPDATE. Preview advisory, commit authoritative.
- **C. Refresh↔lock — CORRECT.** Materializer `_upsert_records` sorts `source_row` +
  `on conflict (client_id, source_row)` (same lock order as the lock guard); `_claims_blocking_removal`
  blocks deleting a lot with active claims. `used_qty_by_lot` is a fresh query (never cached).
- **D. Substitute modal stock was GROSS — FIXED.** `/substitute-stock` (`co_case.py:~2553`) read
  the raw snapshot and reported `remaining_qty` without the claims overlay → a lot mostly locked
  by another dossier looked fully available. Not an over-claim (lock guard still blocks) but
  misleading. **Fixed:** overlay `apply_used_qty(rows, used_qty_by_lot(client_id))` (copy first for
  cache hygiene) before `case_allocation_pool`, mirroring the calculate path. One fix covers
  stock-first discovery too (it defers tồn to this endpoint).
- **E. `used_qty_by_lot` no case filter — SAFE (conservative).** Double-counts the CURRENT case's
  own locked sheets → under-states availability, never over-claims. Left as-is.
- **F. Cold-start guard skip — OPEN (narrow).** If a DB client has NO materialized snapshot,
  `record_sheet_lock` SKIPS the overclaim check (`co_stock_ledger.py:198-204`). Two dossiers could
  then lock the same lot with no cross-case guard. Real over-claim, but requires a never-refreshed
  client. → BACKLOG **D2**.

### 2. Reservation-model question ("2 dossiers both calculating NVL A")
VERIFIED: claims are written ONLY at CHỐT (`record_sheet_lock_claims` called from
`lock_co_case_origin_sheet:2214` + `bulk_lock_route:1880`); only statuses `locked`/`released`,
**no `pending`/`reserved`**. So **calculating-but-not-locked reserves nothing** — two drafts are
invisible to each other. The user's premise ("HS2 sees A short because HS1 is mid-calc") does NOT
hold under current logic: HS2 sees A net of only LOCKED claims, so it sees A full until HS1 locks.
- **Gap A** — "first to CHỐT wins", not "first to calculate": contention surfaces late (at lock,
  `StockOverclaimError`). `calculate-all` amplifies (calculates + persists the whole lô, 0 claims).
- **Gap B** — no re-evaluation: once a dossier switches away from A, nothing prompts it to reconsider
  when A frees up; `material_override` is a point-in-time snapshot.
- **Decision (recommended, logged in BACKLOG D2):** KEEP commit-time reservation; do NOT build
  soft-reservation (`pending`+TTL — reintroduces ghost-holds, schema change, over-engineered for
  low frequency). Treat Gap A with a **read-only early-warning** in the calculate step (read other
  OPEN cases' calc-state — the `substitution_history.py` cross-case mining path already exists) and
  **fold it into the Phase-2 pre-flight summary**. Priority LOW: current behaviour is safe (guard
  blocks real over-claim); this is waste-of-work prevention, not a correctness fix.

### 3. calculate-all
Reviewed for the cross-dossier stock question only: `calculate_all_route` (`:1711`) →
`_origin_preview_context` → `_calculate_stock_rows_from_snapshot` (nets LOCKED claims — correct) →
`allocate_whole_case_preview` → `prepare_case_origin_products` (one shared decrementing pool,
sequential; tested in `test_substitute_shared_pool.py`). It writes NO claim → same Gap A/B.
FULL logic review of calculate-all beyond cross-dossier (status gating, stale-mark, persistence)
NOT done — deferred.

### 4. Fix D — TDD
- **Red:** `tests/test_substitute_stock_claims_overlay.py` — lot 1000 gross + another dossier's
  locked claim 800 → assert endpoint returns 200. Failed (returned 1000).
- **Green:** the overlay edit above. Full suite **743 pass / 15 skip** (+2). TestClient exercises
  the real route end-to-end with injected claims.

---

## Committed (branch `feat/co-flow-guards`, base `840fb74`)
- **`ceabdb5`** feat(origin): BOM-version precedence (#1) + stock-first substitutes (#2) +
  cross-dossier stock fix (D). Bundles the previous session's #1/#2 (were uncommitted) with D.
- **`a0ec3f6`** docs(agents): AGENTS.md skills section + `docs/agents/` guides.
- **Intentionally left uncommitted (local-only):** `uv.lock` (unrelated ~1000-line churn, likely
  playwright add/uninstall) and `dev.sh` (this box's port overrides). Do NOT commit either.

---

## NEXT SESSION — user asked to do ALL of the below (deferred from this session)
1. **F (correctness, small):** cold-start guard skip. When DB is available but the snapshot is
   empty, `record_sheet_lock` should REFUSE the lock ("refresh tồn trước khi chốt") instead of
   silently skipping the overclaim check. ~1 edit (`co_stock_ledger.py:198-204`) + a test. File-mode
   (`_ledger_available()==False`) is unaffected (returns 0 early). BACKLOG **D2**.
2. **Early-warning for Gap A/B (UX, LOW):** read-only advisory in the calculate step — "NVL A is
   being planned by dossier X". Read other OPEN cases' persisted calc-state (reuse the cross-case
   mining in `substitution_history.py`). **Fold into Phase-2 pre-flight summary**, don't open a new
   feature. Do NOT build soft-reservation.
3. **#2 UI polish (presentation only):** substitute modal stock-first **badges** / catalog-no-stock
   **dimming** / `stock_only` "⚠ chưa đăng ký catalog" chip. Flags already in the JSON.
4. **Full calculate-all logic review** beyond cross-dossier — a separate `/code-review` pass.
- Also: branch now has committed #1/#2/D. Consider `/code-review` vs `840fb74` before any PR to
  `main` (note: pushing `main` from this box triggers prod CD — do not push casually).

## Conventions honoured
- Commits English, **no AI trailer/co-author** (user rule). Feature branch only, not pushed.
- Full analysis + verdict for all 6 race scenarios + reservation model live in **BACKLOG D2**.
