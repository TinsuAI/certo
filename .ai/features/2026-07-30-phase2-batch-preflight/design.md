# Phase-2 batch flow: re-enable decision + pre-flight summary + D2 early-warning

Date: 2026-07-30
Status: design (no app code changed)
Scope: three linked backlog items — Phase-2 bulk/wizard gate, batch-lock pre-flight
summary, D2 cross-dossier early-warning banner.

## 0. State correction (read this first)

The backlog framing ("the batch buttons are intentionally GATED OFF, commit `834e1da`,
decide re-enable vs retire") is **stale against HEAD `520b720`**. What actually happened:

- `834e1da` (2026-06-19) disabled the OLD toolbar buttons — `data-run-stock-all` →
  `preview-stock-all` (a non-committing dry run) and `data-bulk-lock` — with an
  "đang xây dựng" tooltip pointing at the "Xử lý tuần tự" wizard.
- `5851d19` (2026-07-07) **re-enabled** the batch flow under a redesigned, committing
  model, and later commits (`392bfe3`, `8c5ca58`, `b163233`, `2d6538f`, `ceabdb5`)
  built it out. The gate is gone.

Current wiring at HEAD (`app/templates/co_case.html:917-936`, all enabled, no gate):

| Button | data-attr | Route | Behaviour |
|---|---|---|---|
| Xử lý tuần tự | `data-origin-wizard-start` | (client-side wizard) | one sheet at a time: tính → review → chốt |
| Tổng hợp NVL | `data-origin-aggregate-open` | — | shortfall roll-up sub-view |
| Tính tồn tất cả (SP) | `data-run-stock-all` | `POST …/origin/calculate-all` (`co_case.py:1758`) | whole-case allocate + persist per-sheet status; **committing** |
| Chốt tất cả | `data-bulk-lock` | `POST …/origin/bulk-lock` (`co_case.py:1906`) | sequential lock, commit ledger claims |
| (aggregate NVL swap) | `data-bulk-substitute-url` | `POST …/origin/bulk-substitute` (`co_case.py:1815`) | batch material_override |

The old `preview_stock_all_route` (`co_case.py:1747`, `POST …/origin/preview-stock-all`)
is **orphaned** — `grep` finds no template/JS caller; `calculate-all` superseded it.
Its only remaining referrer is `tests/test_preview_stock_all_route.py`.

So the real decision is not "re-enable vs retire the batch flow" (it is already live and
guarded), it is: keep it, retire the one dead route, and close the coherence gap the
`834e1da` note actually named — there is still **no pre-flight**; "Chốt tất cả" runs a
bare `window.confirm` and only reports skips *after* attempting the locks
(`co_case.html:6330-6354`).

## 1. Recommendation: KEEP the re-enabled batch flow; RETIRE only the dead route; ADD the pre-flight

**Decision: re-enable (formalize the already-live flow), do not retire it.** Concretely:

1. Keep `calculate-all`, `bulk-lock`, `bulk-substitute` and the wizard.
2. **Retire `preview_stock_all_route`** (`co_case.py:1747`) and delete
   `tests/test_preview_stock_all_route.py` — it is a second whole-case-allocate path
   that no longer has a caller, and leaving it invites a future button re-pointing at a
   non-committing preview that then disagrees with `calculate-all`. One path
   (`allocate_whole_case_preview` → persist) is the single source of truth.
3. Add the batch-lock pre-flight (§2) — the missing coherence piece.

**Why re-enable, not retire the flow.** The correctness risk that would justify retiring
is already covered by machinery shared with the per-sheet path:

- `bulk_lock_route` locks **in `origin_product_order`**, per sheet calls the same guard
  the single `/lock` uses — `origin_sheet_action_error(case, code, "lock", client)`
  (`co_case_context.py:1621`) — and skips with the returned reason.
- The actual ledger write is the same `record_sheet_lock_claims` →
  `co_stock_ledger.record_sheet_lock`, which takes `co_stock_rows … FOR UPDATE`, nets
  Σ other-case/other-sheet claims, and aborts with `StockOverclaimError` on any negative
  lot (`co_stock_ledger.py:198-234`). `bulk_lock_route` catches it, skips that sheet, and
  because locking is sequential the sheets after it are blocked too — no ghost claims
  (each sheet persists individually, `co_case.py:1938-1940`).
- So batch lock cannot over-claim any more than N single locks can. The remaining risk is
  **UX coherence** (the user pressing "Chốt tất cả" without knowing which sheets will
  actually lock and why the rest will not), which the pre-flight fixes — not correctness.

**Why not retire (force per-sheet only).** The client explicitly asked for "tự tính tất
cả sheet" and "Chốt tất cả" (commit `5851d19` body). Real cases carry many products
(Growatt/Johnson dossiers), so retiring the batch would mean N manual lock clicks in a
strict order the user must discover by trial. The wizard ("Xử lý tuần tự") is the careful,
review-each-step alternative that already exists; it is a complement, not a reason to drop
the one-shot batch. Keep both; make the one-shot honest with a pre-flight.

## 2. Pre-flight summary spec

**Problem.** Today "Chốt tất cả" → `window.confirm` → POST → toast counts *after* the
attempt. The user cannot see, before committing, which sheets lock and which skip and why.

**What it shows, per sheet, in `origin_product_order`.** Each sheet lands in exactly one
bucket. The reason strings already exist — they are what `origin_sheet_action_error(…,
"lock", …)` returns and what the render attaches as `product.origin_lock_block_reason`.

| Bucket | Category key | Source condition | Copy shown |
|---|---|---|---|
| Will lock | `will_lock` | `origin_can_lock` after sequential simulation (see below) | "Sẽ chốt" |
| Already locked | `already_locked` | `origin_sheet_status == "locked"` | "Đã chốt (bỏ qua)" |
| Skip | `not_calculated` | status ∈ {draft, bom_loaded, stale, calculating}, i.e. `status != "calculated"` | "Chưa tính — bấm Tính trước" |
| Skip | `missing_bom` | `lvc_status == "missing_bom"` (empty/no active NVL) | "Chưa có BOM/NVL" |
| Skip | `declarable_unmatched` | `lvc_declarable_unmatched` truthy | "Còn NVL chưa khớp tồn (declarable_unmatched)" |
| Skip | `shortage` | `lvc_allocation_shortage` truthy | "Còn NVL thiếu tồn/không có lô nhập khớp — bổ sung chứng từ" |
| Skip | `missing_price` | `lvc_missing_price` truthy | "Còn NVL không xuất xứ thiếu đơn giá" |
| Skip | `column9_mode_mismatch` | code ∈ `column9_mode_mismatches(case, client)` | "Cột (9) materialize theo quy ước cũ — tính lại" |
| Skip | `out_of_order` | sequence guard: predecessor still unlocked / later sheet locked | "Cần chốt bước trước / mở chốt bước sau" |
| Warn (still attempts) | `overclaim_at_commit` | cannot be predicted read-only (see below) | "Tồn được kiểm tra tại thời điểm chốt" |
| Warn (still attempts) | `cold_start_no_snapshot` | client has 0 rows in `co_stock_rows` (Fix F) | "Chưa có snapshot tồn — chốt KHÔNG kiểm tra vượt tồn" |

Category order matches `origin_sheet_action_error` precedence: sequence → not-calculated →
missing_bom → declarable_unmatched → shortage → missing_price → column9. That precedence is
already encoded in the guard; the pre-flight must not reorder it, so it reads the guard
rather than re-deriving the flags.

**The sequential-simulation wrinkle (why the raw render flags are not enough).** At render,
`origin_can_lock` uses the *current persisted* `previous_unlocked` list
(`co_case_context.py:1371-1383`). A sheet whose predecessor is `calculated` (not yet
locked) therefore shows `origin_can_lock == False` with an `out_of_order` reason — but in
the batch that predecessor locks first, so the successor *will* become lockable. A pre-flight
that naively echoed the render flag would falsely mark every sheet after the first as
"skip: out_of_order". The pre-flight must **walk in order and treat a sheet already
classified `will_lock` as locked** when evaluating the next sheet's sequence guard — exactly
the state progression `bulk_lock_route` itself produces as it sets each sheet `locked`
(`co_case.py:1938`) before evaluating the next.

**Where it renders.** Replace the bare `window.confirm` in `runBulkLock`
(`co_case.html:6330-6333`) with a pre-flight panel next to the "Chốt tất cả" button (a new
`data-bulk-lock-preflight` container, sibling of the existing `data-run-stock-summary` at
`co_case.html:1006`). The panel lists the buckets ("Sẽ chốt N · Đã chốt M · Bỏ qua K"),
each skip with its sheet code + reason, plus any warn rows, and a "Chốt N sheet" confirm
button (disabled when `will_lock` is empty). Confirming POSTs the existing `bulk-lock`.

**Read-only computation — recommended: a dry-run branch of `bulk_lock_route`.** Add
`dry_run` (query flag or a sibling `POST …/origin/bulk-lock/preview`) that runs the **exact
same loop** as `bulk_lock_route` but:
- does **not** call `record_sheet_lock_claims` and does **not** persist;
- for each sheet computes `origin_sheet_action_error(case, code, "lock", client)`, and where
  it returns "", advances the in-memory `origin_sheet_states[code].status = "locked"` so the
  next sheet's sequence guard sees the simulated lock (matches the real loop);
- returns `{will_lock: [...], already_locked: [...], will_skip: [{product_code, reason,
  category}], warnings: [...]}`.

This makes the pre-flight the *same function* the real lock uses, so the two can never
disagree — except on the two conditions a read-only pass genuinely cannot predict:

- **Over-claim.** `StockOverclaimError` is only raised inside the `FOR UPDATE` transaction
  at commit (`co_stock_ledger.py:198-234`). A dry-run without the transaction cannot know
  it. Surface it honestly as the `overclaim_at_commit` warning, not as a bucket. This is
  acceptable: over-claim contention is the rare late-conflict case (Gap A), and the real
  lock still aborts safely.
- **Cold-start (Fix F).** When the client has 0 `co_stock_rows`, `record_sheet_lock` **skips
  the over-claim check entirely** (`co_stock_ledger.py:198-204`) and trusts calculate-time.
  The pre-flight probes `exists(select 1 from co_stock_rows where client_id=%s)` (read-only,
  same predicate the ledger uses) and, when false, shows the `cold_start_no_snapshot` warning
  so the operator knows this batch is committing without a tồn check. The pre-flight does
  **not** block on it (that would be a scope creep into Fix F's own decision); it only warns.

**Alternative considered — pure client-side from rendered flags.** The buttons already carry
`product.origin_can_lock` / `origin_lock_block_reason` / `origin_sheet_status` per row in the
DOM, so the panel could be built with zero new endpoint. Rejected as the primary because the
sequential simulation would have to be reimplemented in JS against per-row flags and kept in
lock-step with `origin_sheet_action_error`'s precedence — two copies of the ordering rule
that will drift (the same class of bug the `resolve_selected_product_version` ADR unified
away). The dry-run keeps one source of truth. (If a no-endpoint version is ever wanted, it is
a thin client renderer over the dry-run JSON, not a re-derivation.)

## 3. D2 cross-dossier early-warning spec

**Goal (from BACKLOG D2 + the 2026-07-08 decision).** Treat Gap A ("ai CHỐT trước thắng",
conflict surfaces late at Chốt) with a **read-only advisory** at the Tính step: warn that an
NVL this sheet plans to use is also planned by another *open* dossier of the same client, so
the operator does not do work that a competing lock will invalidate. This is
anti-wasted-work, **not** a reservation. Soft-reservation (`pending`/TTL claims) was
explicitly rejected in `.ai/DECISIONS.md` (2026-07-08) — this design does not propose it and
writes no claim.

**Reuse the mining scaffold, not the mining function.** `app/substitution_history.py`
already has exactly the plumbing D2 needs:
- `get_case_workspace(client)["cases"]` — one scan over all of the client's case records,
  each carrying `products[].materials` and `origin_sheet_states` (verified: that is what
  `build_substitution_history` walks).
- a 60s TTL cache keyed by `client_id` (`_CACHE`, `_TTL_SECONDS`), and
  `invalidate(client_id)` — **already called on every lock/reopen** via
  `invalidate_co_case_source_cache` (`co_case.py:245`).

But `build_substitution_history` filters to `status == "locked"` (line 44) and emits
substitute-history — the **opposite** of D2. D2 wants *uncommitted intent*: sheets that are
calculated/loaded but **not** locked. So add a sibling reader in the same module:

```
build_intended_usage(cases, exclude_case_id) -> dict[material_code, list[usage]]
  usage = {case_code, case_id, product_code, sheet_status}
```

- skip `case_id == exclude_case_id` (the sheet being worked on);
- skip locked sheets (`origin_sheet_states[code].status == "locked"`) — a locked sheet's
  draw is already a committed claim reflected in tồn; D2 is only about *un*committed intent;
- include sheets with status ∈ {calculated, bom_loaded, stale};
- the intended NVL set per product = base `products[].materials[].material_code`, **overlaid
  with `material_overrides[].material_code`** (a substitution changes what the sheet intends
  to draw). Deleted/added overrides handled the same way `build_substitution_history` does.

`get_intended_usage(client)` mirrors `get_substitution_history`: 60s TTL, keyed by
`client_id`, reuses/parallels `_CACHE`, dropped by the existing `invalidate(client_id)` on
lock/reopen. Advisory tolerates ≤60s staleness, so no new invalidation hook is required;
optionally add `invalidate(client_id)` to the save / bulk-substitute / calculate-all paths so
a just-made substitution shows within one render, but that is a refinement, not a correctness
need.

**What the banner says.** At the origin/Tính section for the current sheet, for each of its
intended material codes that also appears in `get_intended_usage(client).get(code)` (grain =
`material_code` overlap — cheap and correct for an advisory; do **not** attempt lot-level
contention, which needs the allocation and is expensive):

> ⓘ NVL `<code>` đang được hồ sơ `<case_code>` dự tính dùng (chưa chốt). Ai chốt trước trừ
> tồn trước — cân nhắc phối hợp trước khi tính lại.

Multiple competing cases → list up to a few case codes then "+N nữa". It is a non-blocking
info banner: no button is disabled, no status changes, nothing is written. It renders from
the read-only map and disappears once the competing sheet locks (its intent becomes a claim,
excluded by the locked-sheet filter) or is released.

**Explicitly out of scope / must not do.** No `pending`/`reserved` claim, no TTL hold, no
change to `origin_sheet_states`, no effect on `origin_can_lock` or the lock gate. The banner
reads state; it never mutates it. Contention remains safely resolved at commit by the
over-claim guard — D2 only moves the *discovery* of the conflict earlier.

## 4. Tests, seams, and what must not change

### Seams touched

| File:line | Symbol | Change |
|---|---|---|
| `app/routers/co_case.py:1906` | `bulk_lock_route` | add read-only `dry_run` branch (or sibling `bulk-lock/preview`) reusing the loop; **commit path unchanged** |
| `app/routers/co_case.py:1747` | `preview_stock_all_route` | **retire** (orphaned by `calculate-all`) |
| `app/web/co_case_context.py:1621` | `origin_sheet_action_error` | **read-only reuse** — the pre-flight's per-sheet reason source; do not modify |
| `app/web/co_case_context.py:1402-1417` | render flags `origin_can_lock` / `origin_lock_block_reason` | read-only reuse in the pure-client fallback |
| `app/co_stock_ledger.py:198-204` | Fix F snapshot check | pre-flight *reads* `exists(co_stock_rows)` for the cold-start warning; **guard itself unchanged** |
| `app/substitution_history.py` | new `build_intended_usage` / `get_intended_usage` | parallel to `build_/get_substitution_history`; reuse workspace scan + 60s TTL + `invalidate` |
| `app/templates/co_case.html:6330` | `runBulkLock` | replace `window.confirm` with the pre-flight panel |
| `app/templates/co_case.html:1006` area | new `data-bulk-lock-preflight` panel + D2 banner container | render surface |

### Tests

New:
- `tests/test_bulk_lock_preflight.py` — dry-run returns `will_lock` / `already_locked` /
  `will_skip[{category, reason}]` for each guard reason (not_calculated, missing_bom,
  declarable_unmatched, shortage, missing_price, column9_mode_mismatch, out_of_order);
  **sequential simulation** case: `[calculated, calculated]` → both `will_lock` (not "second
  blocked by first"), proving the walk treats will-lock predecessors as locked;
  assert `record_sheet_lock_claims` is **not** called in dry-run (no ledger write); cold-start
  (no `co_stock_rows`) → `cold_start_no_snapshot` warning present; over-claim documented as
  *not* predicted. Reuse the `_seed` / `_stub_claims` helpers from `test_bulk_lock_route.py`.
- `tests/test_bulk_lock_preflight.py::test_preview_matches_commit` — parity: for the same
  seed, dry-run `will_lock`/`will_skip` equals the real `bulk_lock_route` `locked`/`skipped`,
  **except** the over-claim sheet (which only the commit path reports).
- `tests/test_intended_usage.py` — `build_intended_usage` excludes the current case; includes
  calculated/bom_loaded/stale; **excludes locked**; overlays `material_overrides` onto the
  intended code set; keyed by `material_code`; `get_intended_usage` 60s TTL + `invalidate`
  drops it.

Changed/removed:
- delete `tests/test_preview_stock_all_route.py` with the route (or repoint its smoke to
  `calculate-all` if a whole-case-allocate smoke is still wanted — `test_preview_stock_all_route.py`
  already covers `calculate-all` per commit `5851d19`, so confirm before deleting).

Regression (must stay green, unchanged — proves the pre-flight moved no guard):
- `test_bulk_lock_route.py`, `test_shortage_lock_guard.py`, `test_missing_price_lock_guard.py`,
  `test_declarable_unmatched_guard.py`, `test_origin_lock_readiness_guard.py`,
  `test_column9_mode_flip.py`, `test_co_stock_lock_concurrency.py`,
  `test_recalc_lock_parity_db.py`.

### Must NOT change

- **Commit-time claims model.** Claims are written only at lock
  (`record_sheet_lock_claims`), status is `locked`/`released` only — no `pending`/`reserved`.
  D2 is read-only advisory; the pre-flight is read-only. Neither writes a claim.
- **The over-claim guard.** `co_stock_ledger.record_sheet_lock` `FOR UPDATE` + net-other-claims
  abort stays the authority. The pre-flight does not bypass, weaken, or pre-empt it;
  over-claim remains a commit-time hard stop, surfaced in the pre-flight only as a warning.
- **The three-belt lock guards** (`calculated_sheet_status` downgrade →
  `origin_sheet_action_error` re-check → export blocker) for shortage / missing_price /
  declarable_unmatched / column9. The pre-flight is display-only and must never become a new
  bypass that lets a blocked sheet lock.
- **Fix F** stays its own open item. The pre-flight only *reports* cold-start; deciding
  whether to block Chốt without a snapshot is Fix F's call, not this feature's.
