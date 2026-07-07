# Session handoff — 2026-07-08

Batch auto-flow: "Tổng hợp NVL" became a real tab; substitute-allocation
correctness proven; then a design review of **BOM selection** + **substitute
search source** produced two agreed redesigns and one item deferred to next
session.

Branch: `feat/co-flow-guards` (NOT merged to main). Suite **729 pass / 15 skip**.
Server: `devctl` co on `127.0.0.1:8001` (auth restored `CO_AUTH_REQUIRED=1`).

---

## What shipped this session (commits — do not re-derive, read the messages)

`git log 840fb74..HEAD` on `feat/co-flow-guards`. Newest-first highlights:
- `2d6538f` — **"Tổng hợp NVL" as a first-class origin sub-view (tab)**. Aggregate is
  now a third origin view (`data-origin-view` = review/sheet/**aggregate**), nav
  button `[data-origin-aggregate-open]` + badge, wired into
  `applyOriginView`/`captureOriginView`/`replaceCaseShellFromResponse`. Variant A
  table + collapsible "Nhật ký thay đổi" (`substitutionLog`) + per-row `↩ Hoàn tác`
  (`revertSubstitution`). Modal candidate chip marked "(tạm tính)" in whole-lô mode.
  Browser-verified on `e2e-batch-real` (0 JS errors; screenshot under
  `.ai/screenshots/2026-07-07-tong-hop-tab/`).
- `6d6e199` — **`tests/test_substitute_shared_pool.py`** (5 tests): PROVES the
  whole-case shared per-material pool correctly makes a substitute's available stock
  account for that material consumed elsewhere in the lô (native or via other
  substitutions). No bug found. This closes the user's "A1 tiêu hao nơi khác" concern.
- `5851d19` — **`calculate-all` route** (batch "Tính tồn tất cả (SP)"): whole-case
  allocation + PERSIST each sheet's status (was a non-committing preview → child
  sheets stayed empty). Bypasses the per-sheet calc gate (one sequential pass).
- `54914ec` — reseed `e2e-batch-real` with **real DH product codes**
  (INV-5000/INV-10K/INV-3000). Root cause of earlier "no BOM": app resolves a sheet's
  BOM by product **`code`** (`co_case_bom_product_codes`), not `bom_product_code`.
- `b163233` — no-BOM sheets must not report "✓ Đủ tồn" (`case_shortfall_rollup` →
  `no_bom_products`). `b026328` — Load BOM must not falsely mark "Đã nạp BOM".
- Earlier: `392bfe3`/`3f52920`/`b23014e`/`1a9bc0f` — batch UI, M3 rollup, M2
  substitution planner, Slice-0 guards (DC3c hard-block, DC3a propose==bảng kê).

Design doc (living): `.ai/features/2026-07-06-auto-flow-batch-redesign.md`.
Prototype (throwaway, decision folded in): `.ai/prototypes/2026-07-07-tong-hop-sheet-tab.html`
→ Artifact https://claude.ai/code/artifact/59bb6c09-208a-4854-9530-f56c605a1aad
(verdict: **Variant A + undo-per-row + collapsible ledger**).

---

## NEXT SESSION — agreed design, ready to implement (`/tdd`)

Two review questions this session produced concrete, user-approved designs. Implement
in this order. **Full expert analysis is in the conversation; the agreed shape:**

### #1 — BOM selection for batch (correctness bug + UX)
- **BUG to fix first (affects calculations):** the muc6 client-default BOM layer is
  **shadowed**. `attach_case_bom_snapshot` (`app/bom_store.py:788`) runs first in every
  origin context build and pre-pins `product.bom_product_artifact_id =
  composition/latest`, **ignoring `client_defaults`** — so steps 5–6 (client default)
  of `selected_bom_rows_by_product` (`app/web/co_case_context.py:1585`) almost never
  fire. Effect: staff pin v1 as default, DH publishes v2 → sheet auto-calculates **v2**,
  UI shows "#2", ★ sits on unselected v1. Fix: teach `attach_case_bom_snapshot` the
  same `client_defaults` step (+ `bom_product_code` resolution), OR don't pre-pin when
  the pin came from the snapshot rather than an explicit user pick.
- **UX (user's ask):** batch "Tính tồn" should show a **BOM-selection table** — default
  per the (fixed) precedence, but user-editable. Recommendation: **enhance the Review
  dashboard** per-SP row with an inline BOM-version picker + a "why" label
  (*"#N · mặc định của khách"* / *"#N · mới nhất (chưa ghim)"* / *"user chọn"*). Chosen
  versions feed "Tính tồn tất cả". Pin = case override (`bom_product_artifact_overrides`)
  or client-default store.
- Precedence order (9 steps) confirmed in `selected_bom_rows_by_product`:
  per-SP pin → case override → **client default** → DH aggregate composition →
  `latest_usable_product_version`. No-default → DH latest published usable version
  (e.g. INV-3000 → artifact #2). Whole-case and per-sheet agree (no divergence).

### #2 — Substitute search source (blind spot)
- Today: "Khuyến nghị" = DH substitutes → DH catalog HS-heuristic → CO history;
  "Tìm kiếm" = DH catalog (`list_materials`) → this-dossier BOM rows. **Neither scans
  `co_stock_rows`.** Catalog ≠ stock universe (stock keys on
  `customs_item_code`+`allocation_code`, can carry codes absent from catalog). ⇒ an NVL
  **in stock but not in catalog cannot be found/substituted** (route:
  `co_case_origin_sheet_substitute_candidates`, `app/routers/co_case.py:2255`; feasibility
  `substitute-stock` :2482 already matches on stock keys but is never asked about such a code).
- **Agreed design (user's idea, refined):** flip discovery to **stock-first ⟕ catalog** —
  build candidates from `read_co_stock_rows_cached` (còn tồn, grouped by allocation/customs
  code) LEFT-JOIN the catalog for name/HS/customs_relevance ("fuller catalog on the fly").
  Rationale: for substitution, "có tồn" is the *relevant* universe anyway. Keep DH
  "Khuyến nghị" as the quality-ranked complement.

### #3 — DEFERRED TO NEXT SESSION (user's explicit ask): compliance nuance
- A **stock-only** substitute code lacks catalog metadata (name/**HS**/customs_relevance)
  → produces a `declarable_unmatched` material → **DC3c guards block lock/export**. So #2
  must NOT present stock-only codes as fully valid: **flag** them ("⚠ tồn có · chưa đăng
  ký catalog HQ — cần bổ sung ở Data Hub trước khi phát hành C/O") and consider a
  reverse "missing-material → Data Hub" flow (CO consumes DH; catalog fixes are DH-side,
  see CLAUDE.md "Data Hub API Requests"). **Review this nuance thoroughly before building
  #2's picker** — it shapes what a stock-only candidate is allowed to do.

---

## Environment / gotchas (this shared prod box — see ~/.claude/CLAUDE.md)
- **Never touch prod containers** (co-app-1:8755, data-hub-app-1:8754, nightly-*,
  audit-hq-mvp:8200); no broad docker prune/rm/stop. Pushing `main` triggers real prod CD.
- Commit/PR messages **English, no AI trailer/co-author** (user rule). Feature branches only.
- Dev servers via **`devctl {up|down|restart|status|logs} [co|all]`** — not hand-rolled uvicorn.
- **Browser e2e** needs `CO_AUTH_REQUIRED=0` in `.env.dev` (gitignored) + `devctl restart co`
  + `npm i puppeteer-core --no-save` (chromium at `/usr/bin/chromium-browser`, `--no-sandbox`).
  **Restore `=1` + restart + `npm uninstall puppeteer-core --no-save` when done** (was restored).
- **Test case `e2e-batch-real`** (growatt-vn): 3 SP INV-5000/INV-10K/INV-3000 (real DH
  BOMs), AL-100 shared → short 2/3 SP (cần 1700/tồn 1000/thiếu 700 kg). Seed:
  `.ai/scripts/e2e_batch_real_seed.py` (co_dev only, `--cleanup` marker-scoped to
  `transaction_key` prefix `e2e-batch-real`; NEVER writes data_hub_dev). BOM renders only
  for a **logged-in** user (DH pull needs the SSO session token; scripts have none).
- DH BOM data: INV-5000 (7 rows), INV-10K (6), INV-3000 (5, has artifact_no 1 AND 2 →
  "latest usable" = #2). Shared NVL across all 3: PE-001, AL-100, PCB-12, HEATSINK-A, CASE-INV.
- Uncommitted, safe to leave: `.ai/prototypes/2026-07-07-tong-hop-sheet-tab.html` (throwaway),
  pre-existing `AGENTS.md`/`uv.lock`/`dev.sh`/`docs/agents/` (not this session's).

## Suggested skills for next session
- `/codebase-design` — the #1 BOM-selection redesign (two selection functions with
  divergent precedence = a seam problem; unify the interface).
- `/tdd` — implement #1a (precedence fix) then #1b (picker) then #2, red→green, seams:
  `selected_bom_rows_by_product` / `attach_case_bom_snapshot` (BOM), the
  substitute-candidates route (search). Confirm seams before writing tests.
- `/domain-modeling` — pin the catalog-vs-stock-vs-declarability vocabulary in
  `.ai/GLOSSARY.md` before touching #2/#3.
- `/code-review` — review the finished branch (fixed point `840fb74`) before a PR to main.
- Session start: read `.ai/STATUS.md`, `.ai/DECISIONS.md`, this file + the last 3–5 in
  `.ai/sessions/` (per project CLAUDE.md).
