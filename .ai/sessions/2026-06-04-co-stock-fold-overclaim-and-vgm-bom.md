# Session: CO stock fold refactor, overclaim cleanup, VGM BOM diagnosis

Date: 2026-06-04 (continuation, same day as the bảng kê/dossier session)
Client focus: **johnson-vn**, cases `co-case-e015fad11e4a` (SCI, EU/EVFTA/EUR.1) and
`co-case-ede4d913bafa` (VNG, Chile/Form B).

## What Was Done

### 1. UI fixes (commit `3e9f508`)
- **"Xem" button unreadable** on Tồn CO table: `.table-link` is used on a `<button>`,
  which inherited the base `button` rule's `background: var(--primary)` (teal) while
  `.table-link` only set `color: var(--primary)` → teal-on-teal. Fixed: `.table-link`
  now resets `background/border/padding` + underline. `app/static/css/app.css`.
- **Lot-history modal** (`app/templates/co_stock.html`): flipped Δ sign to the tồn
  convention (Lock CO = −qty red, Release = +qty green), filled the **"Tồn sau"** column
  by anchoring on the lot's current signed remaining and walking backward, added an
  overclaim warning in the header. Endpoint `co-stock/lot-history` now returns the lot's
  signed `remaining_qty` + `overclaim` flag (`_lot_effective_anchor`).

### 2. CO stock fold refactor (commit `66fe311`) — the main change
**Root bug:** `co_stock_rows.remaining_qty` was materialized as the *opening* qty (a
semantic lie). True tồn was recomputed at read time in **5 call sites**; **2 skipped the
trừ-lùi adjustment layer** (the lock-guard SQL in `co_stock_ledger.record_sheet_lock`,
and the calculate snapshot path `_calculate_stock_rows_from_snapshot`). Result: cases
could over-claim lots the agency had already marked fully consumed.

**Fix — fold the static layers into the snapshot:**
- `co_stock_adjustments_store.fold_baseline()` (new): writes `opening_qty`,
  `baseline_used_qty`, `bcct_qty`, and signed `remaining_qty = opening − baseline`. Idempotent.
- `co_stock_materializer`: folds on every refresh; `refold_adjustment_lots()` +
  `refold_all_adjustments()` re-fold on adjustment import/void and for backfill;
  STATUS_FILTERS handle negative folded remaining.
- `co_stock_ledger.apply_used_qty()` rewritten: overlays ONLY the live ledger; exposes
  `used_qty`, `remaining_signed_qty`, clamped `remaining_qty`, `ledger_overclaim`. The
  guard now reads the folded `remaining_qty` → rejects overclaim with no logic change.
- `co_stock_adjustments_store.apply_adjustments()` deprecated (removed from all read paths).
- `routers/co_stock.py` import endpoint re-folds touched lots immediately; table shows
  "⚠ Vượt tồn N" in the Lý do column.
- `tests/test_co_stock_fold.py` (new, 8 tests, all green).

### 3. Deployed to prod + backfilled
- Pushed `66fe311`+`3e9f508` → `tinsu/main`; CI green; verified container has `fold_baseline`.
- Ran `refold_all_adjustments("johnson-vn")` on prod (**25,714 lots**) and local (25,727).
  Snapshot `remaining_qty` is now the true tồn-after-reconciliation. Guard re-verified to
  block (tried locking 1 unit on the depleted lot → `StockOverclaimError`).

### 4. Reset the 2 over-claimed cases on prod (per user request)
- Overclaim was real: **378/533 lots, ~6298 units**, all from these 2 cases (1047 claims).
- Released ALL claims per sheet via `record_sheet_release` (e015: 798, ede4: 249 → **0**).
- `ede4` was status `completed` (closed) → reopened (`update_case_record({status:"open"})`)
  then `mark_origin_sheets_stale`. Both cases now **claims=0, sheets stale, status open**.
- Prod now: **0 locked claims, 0 overclaim** client-wide.

### 5. Investigated why the cases can't be re-built (the long tail)
Recalc preview (read-only) under new logic: VNG ~6% short (mostly fine), **SCI ~69% short,
concentrated in the 3 VGM products (87–96%)**. Root-caused decisively:
- **96.1% of SCI shortfall = materials that don't resolve to any BCCT tồn lot** (593 NVL),
  all with **0đ value (missing unit price)**. Trừ-lùi accounts for only 0.2%.
- The unresolving materials are **SAP internal codes** (`1000546547`, …). They ARE in the
  material catalog (12,482 rows — catalog is NOT empty) but as **bare stubs** (name = code,
  no HS, no customs-code mapping) → can't link to BCCT.
- The VGM products have **only technical SAP-flattened BOMs** (`agency_2026-05-07`,
  `sap_indented_raw`). They have **no `m16_2025` (Mẫu 16 / customs_declared) BOM**.
  `m16_2025` exists ONLY for the 6 MFW products — which were already fine.
- **UI switch test on prod** (Playwright, `10-vgm-switch-v5.png`): VGM0121-05 has only 2
  BOM options (#2 = 2-row shallow, #5 = 223-row technical); case already uses #5; recalc
  still "Thiếu tồn CO". No customs/Mẫu-16 option to switch to.

**Conclusion:** Two independent problems were tangled together:
1. **Overclaim/fold** = a real CO bug → fixed, deployed, prod cleaned. ✅
2. **VGM shortfall** = upstream **data gap**: VGM/MPL products have no Mẫu-16/định mức BOM
   ingested; their SAP-flattened BOMs reference materials not in BCCT. Not a CO bug, not
   trừ-lùi, not the fold. ❌ (Data Hub / agency data task.)

### 6. BOM picker shallow-flat filter (commit `72cc10d`, deployed)
The VGM diagnosis surfaced a second, smaller picker bug: VGM0121-05's BOM dropdown offered
BOTH a 2-row SHALLOW flatten (`purchased_btp_as_leaf`) and the 223-row full one. `shape=flat`
keeps any `flatten_status='flattened'`, so shallow leaks — picking it yields a 2-material
bảng kê / wrong CO. We filed a DH contract request (`.ai/api-requests/2026-06-05-bom-picker-
shallow-profile-filter*.md`); DH shipped a `depth=full` filter + per-item `is_shallow`. CO
wired it (commit `72cc10d`, deployed `tinsu/main`):
- `data_hub_client`: `depth` kwarg on `list_bom_artifacts_filtered` + `_batch`.
- `bom_service`: picker calls send `depth="full"`. Client-side fallback `_version_is_shallow`
  (prefers DH `is_shallow`, else strategy mirror `{purchased_btp_as_leaf, mixed_confirmed,
  no_strategy}`); `_picker_predicate_keeps` gained a `depth` param; shallow dropped on both
  trust-server and local paths.
- `bom_shallow_only_codes` + workspace field + `co_case.html`: a product whose only flat BOM
  is shallow shows "❗ Chưa có BOM khai triển đầy đủ" instead of the 2-row stub.
- 13 picker tests (incl. an end-to-end fallback test where DH omits `depth`).

**Verified on prod (data + UI):** VGM0121-05 picker now offers only the 223-row full BOM;
the shallow #2 is gone. Confirmed both at the data layer and on the real UI via Playwright
(`.ai/screenshots/2026-06-05-bom-picker-verify/01-vgm-picker.png` — dropdown shows only
`#5 · 223 dòng`). Notably `is_shallow=None` in the prod response → the demo's **DH instance
hasn't deployed the `depth`/`is_shallow` echo yet**, so CO's client-side fallback is what's
dropping the shallow — i.e. the back-compat path is proven live. NOTE: this is the picker
only; it does NOT fix the VGM shortfall (the full BOM v5 still has SAP-stub materials → still
needs Mẫu-16).

## Decisions Made
- **Fold the static trừ-lùi layer into the snapshot** (vs read-time overlay everywhere):
  makes `remaining_qty` honest and closes the guard gap for free. User chose this.
- **Overclaim display:** clamp "Còn lại" at 0 + "⚠ Vượt tồn N" badge; history shows signed.
- **Reset = release claims + mark sheets stale** (mirrors per-sheet "reopen"); did NOT
  auto-lock SCI because 94% of its VGM materials can't resolve (would produce a garbage dossier).
- Did NOT void the trừ-lùi batch — it's ~innocent (0.2% of shortfall) and the lots it
  marks consumed are genuinely consumed.

## What Didn't Work (don't retry)
- **"Trừ-lùi exhausted the VGM lots"** — disproven (0.2% of shortfall).
- **"Material catalog is empty"** — WRONG; it has 12,482 rows. The `0` I first reported was
  `material_rows` in the calc snapshot path, which is intentionally `[]`, not the catalog.
- **"Calc not loading the catalog is the cause"** — disproven: A/B recalc with the full
  12,482-row catalog gave the IDENTICAL shortfall (SAP entries are stubs, no HQ mapping).
- **Internal BOM-version override** (`bom_product_version_overrides` / `bom_product_artifact_id`
  on the case dict in a script) — did NOT change the selected version. The UI dropdown +
  calculate is the reliable switch path.
- **Sourcing `.env` for `test_co_demo`** — flips the app into Data Hub mode and causes ~56
  spurious failures; that suite is file-mode. Run it WITHOUT `.env`; DB-backed co_stock
  tests need `.env`. (Cost a 13-min false-alarm "60 failed" run.)

## Open Items
- **VGM0119/0120/0121-05 + MPL0104/0109-39 need a Mẫu-16/định mức BOM ingested** into Data
  Hub (customs-coded). This is the blocker for building the SCI (EVFTA) C/O. Agency/Data Hub task.
- **Decide on the 2 reset cases:** VNG (ede4, ~6% short) is re-runnable in the UI; SCI
  (e015) should stay stale until its VGM BOMs are fixed. Neither is locked now.
- **LVC on VGM is unreliable** (81% computed on ~half the BOM that has prices; SAP-stub
  materials have no price → invisible → optimistically high). Don't trust it for issuance.
- **(optional CO improvement)** The calc snapshot path runs `material_rows=[]` (skips the
  catalog). Harmless today (catalog stubs don't help), but if Data Hub completes the SAP→HQ
  mapping later, this path should load the catalog to enrich materials.
- **(optional, DH-side)** The demo's Data Hub instance hasn't deployed the `depth`/`is_shallow`
  echo (commit a8a3816) — CO's client-side fallback covers it, but deploying it server-side
  offloads the shallow filter to DH. CO is correct either way; no CO change needed when it lands.
- **Local working tree:** `AGENTS.md` (screenshot date-prefix convention) + the two
  `.ai/api-requests/2026-06-05-bom-picker-shallow-profile-filter*.md` artifacts + the handoff
  docs are uncommitted (the code fix `72cc10d` IS committed + pushed).

## Pointers
- Commits this session: `66fe311` (fold), `3e9f508` (UI), `72cc10d` (BOM picker depth) — all
  on `tinsu/main`, deployed.
- DH request artifacts: `.ai/api-requests/2026-06-05-bom-picker-shallow-profile-filter.md`
  (+ `-dh-prompt.md`). DH shipped `depth=full` + `is_shallow` (their commit a8a3816).
- Memories written: `co-stock-folded-remaining-model`, `test-env-filemode-vs-datahub`,
  `screenshot-folder-date-prefix`.
- Screenshots: `.ai/screenshots/2026-06-04-co-stock-history/` (history modal, overclaim
  badge, prod origin recalc, VGM BOM switch).
- Prod data recipe used throughout: `ssh tinsu 'docker exec -i co-app-1 python' < script.py`
  and `docker exec -i co-db-1 psql -U co -d barry_co`.
