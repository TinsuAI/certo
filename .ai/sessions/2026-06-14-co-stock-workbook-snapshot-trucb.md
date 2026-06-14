# Session: CO-stock workbook→snapshot import + Trục B BOM-match fix (2026-06-14)

Started from "review backlog" → went deep on CO-stock. Two shipped outcomes: (1) a
workbook→standalone-snapshot import tool (new page), and (2) the Trục B allocation_code
fix that makes Growatt BOM matching work (dev + prod).

## What Was Done

**1. Workbook → standard template converter + standalone snapshot import (commit `7874e21`, deployed).**
- `app/co_stock_workbook.py`: `parse_workbook` (agency NK2/Save → standard rows; `customs_code` = goods-name
  `"#&"` prefix via `matching_code`; remaining = opening−used + cross-check the workbook "Tồn" column →
  `summary.ton_mismatch`), `convert_to_standard_template` (→ standard .xlsx + preview, no DB),
  `stock_rows_from_standard(rows, config)` (bake remaining; `baseline_used = opening − remaining` so
  `apply_used_qty` honours remaining; `allocation_code` via `resolve_allocation_code`; eligibility active),
  `import_standard_snapshot` (materializer `fold=False`, full replace).
- `app/co_stock_template.py`: `+remaining_qty` column (optional, backward-compat).
- `app/co_stock_materializer.py`: `fold: bool` param; `is_workbook_sourced()` helper.
- `app/routers/co_stock.py`: `POST /co-stock/convert-workbook` (preview+b64), `POST /co-stock/import-snapshot`
  (standalone), `GET /co-stock/workbook-tool` (own page), refresh guard (skip workbook-sourced).
- `app/templates/co_stock_workbook_tool.html` (new standalone page); `co_stock.html` panel → link.
- `scripts/convert_co_stock.py` thinned to a CLI wrapper over `parse_workbook`.
- TDD: `tests/test_co_stock_workbook.py` — file-mode 596 pass + DB subset 53 pass; e2e 12/12.
  Verified literal end-to-end on real Growatt: convert → `/co-stock/import` → overlay remaining 10/10 (reverted).
- Pushed → CI `27500543989` success → prod git_sha `7874e21`.

**2. Trục B — Growatt BOM↔stock match fix (DEV + PROD, config+data, NOT in git).**
- Root cause: `growatt-vn` config `allocation_code.strategy = same_as_customs_code` → allocation = the
  category prefix ("DIOT") while Growatt BOM uses dotted codes ("940.x") → BOM matched only **4%** (16/335).
  Should be `description_regex` (extract the dotted code from the name parens).
- Fix (both envs): `save_client_config` → `description_regex` + re-materialize allocation_code in-place
  on 38287 rows (category→dotted, qty untouched). DEV: BOM 4%→99%, origin sheet "không tồn" 101→0 (e2e).
  PROD: applied via `ssh tinsu` → `docker exec co-app-1` + restart; verified persist (alloc dotted, 200).
  Backups: dev `config.json.bak-2026-06-14`, prod `config.json.bak-trucb-20260614`.

**3. Discovery + backlog.** Briefs `2026-06-14-co-stock-key-bom-matching-unification.md` (2-trục) +
`2026-06-14-co-stock-remaining-snapshot-import.md`. Backlog **CS3** (review 3 stock sources). Memories:
`co-stock-workbook-converter`, `growatt-allocation-strategy-bom-match`, updated
`co-stock-lock-orthogonal-overclaim-race` (Phase 1+2 done).

**4. Workspace cleanup.** Archived obsolete siblings → `../_archive/` (barry-CO-bom-builder, barry-google-app,
barry). AGENTS.md "Related sibling folders" note added.

## Decisions Made
- **Standalone remaining-based snapshot, NOT "Trục A" (lot-key refactor).** User's insight: the workbook
  already has "Tồn" per lot → bake remaining + set co_stock_rows directly → no key-match against BCCT →
  **Trục A becomes unnecessary**. Simpler + lower-risk than refactoring the core overlay key.
- **`customs_code` = name "#&" prefix** (= BCCT `customs_item_code` = the lot key), NOT the Mã NPL/SP column.
  Audited: trừ-lùi name-prefix == BCCT customs_item_code 1500/1500; Mã NPL/SP == BCCT 0/1500 (Growatt).
- **Per-company code logic lives ONLY in `resolve_allocation_code` (client_config).** Johnson unified
  (`same_as_customs_code`); Growatt needs `description_regex`. That's the one principled seam.
- **Trục B applied in-place (not full DH refresh):** surgical (allocation only, no qty change = no SAI TỒN),
  fast, avoids D1 refresh landmines, and delta-refresh wouldn't re-derive unchanged rows anyway.
- **Converter on its own page** (user: "đừng để lẫn trong CO stock").

## What Didn't Work / Reverted
- **Built standalone ingest → removed (user: "converter only, đừng đụng DB") → re-added** after the user
  reconsidered (the legacy overlay import still needs key-matching, which is the mess). Net: standalone is in.
- **Trục A (change overlay key triplet→(decl,line)) reviewed → DEFERRED.** Real but moderate risk in the
  SAI-TỒN core; moot once the remaining-based standalone model is used. Kept in CS2/CS3 for if-ever-needed.
- **Archived `barry-CO` → BROKE git** (it's the worktree PARENT of barry-CO-main). Restored it; do NOT
  archive worktree parents. Lesson learned.
- **e2e first reported "122/122 không tồn"** — measurement bug: counted after Load BOM but before "Tính"
  finished (bom_loaded state = 0 allocations). After Tính completes: 0/122. (User caught this.)

## Open Items
- growatt-vn PROD calculated sheets need **re-calc (Tính lại)** to reflect fixed allocation (fix-forward).
- **CS3**: review the 3 stock sources holistically (DH / workbook import / CO-case claims) — `/discover` first.
- **2 P0 fold bugs** (CS2 §A) still live for clients on the legacy DH-overlay import path.
- Minor /rev findings (source_row vs parse-key consistency; workbook client can't DH-refresh; converter
  broad except) — folded into CS3.
- Edge: ~43 Growatt rows with no "#&" in the name fall back to the Mã NPL/SP column (tiny).
