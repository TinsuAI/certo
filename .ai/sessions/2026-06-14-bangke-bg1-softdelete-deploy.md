# Session: BG1 bảng kê data-loss fix + edit-flow UX + release 0.14.0 deploy

Date: 2026-06-14. Branch `feat/rd3-bangke-split` → merged to `main`, deployed to PROD (0.14.0, `79edb05`).
Follows the RD3 redesign session. This session = BG1 fix (P0) + delete/Tính/Load-BOM UX (P1-P3) + release.

## What Was Done

**Investigation → brief → /tdd.** Ran 3 parallel investigation agents (client JS, server save/recalc/fold,
Load-BOM/Tính flow). They **disagreed** on the crux, so I read the code directly to arbitrate. Wrote
`.ai/features/2026-06-14-bangke-edit-recalc-redesign/brief.md`.

**Root cause (BG1).** Material overrides are keyed by **positional row index** (`loop.index0`), but
`recalculate_origin_sheet_edits` → `sheet_edit_bom_rows` did `continue` on deleted rows ⇒ **shrank**
`product.materials` on every save and **persisted the shrunken list while keeping index-keyed overrides
(no remap)**. The template (`co_case.html:1430`) was designed the opposite way — it folds deleted rows
*in place*, assuming they stay in `materials`. So after the first delete, the stale `{"i":deleted}` key
landed on the **adjacent (shifted) row** → lost real rows + pinned the "đã xoá" count. Confirmed by
reading `attach_origin_sheet_states` (only attaches metadata, doesn't rebuild materials).

**P0 fix — soft delete (commit `60e55a1`).** `sheet_edit_bom_rows` now KEEPS deleted rows (flagged
`deleted`) so `materials` length is stable → index never shifts. `origin_material_from_bom_row` returns a
neutral deleted row; `origin_product_from_invoice_match` computes VNM/LVC/missing over
`active_materials = [m for m in materials if not m.get("deleted")]`; `build_bom_proposal_rows` skips
flagged-deleted. Template folds on `material.deleted`; CSS `.origin-row-deleted-folded` = strikethrough+dim.
Tests: `tests/test_bangke_soft_delete.py` (unit + `/save` round-trip proving no extra-row loss + count accum).

**P1-P3 (commit `1e089e9`).**
- **P1 unify delete:** both paths already share `stageRowDeletion`; removed the single-row confirm in the
  substitute modal (`removeRow`) — single delete is soft + Ctrl+Z recoverable; kept/clarified the bulk confirm.
- **P2 contextual "Tính bảng kê":** `origin_can_calculate` now true only for `draft/bom_loaded/stale`;
  `calculated` (not stale) disables with "Đã tính — sửa bảng kê sẽ tự tính lại"; label = "Tính lại" when stale.
  Rationale: edits auto-recalc via `/save`, so re-pressing Tính was a no-op. Tests: `test_bangke_calculate_contextual.py`.
- **P3 Load BOM overwrite warning:** confirm in the delegated submit listener when the sheet has rows/edits
  (load-bom wipes `material_overrides` server-side).

**Release 0.14.0 (commit `97dca73`).** CHANGELOG entry (Vietnamese) + `pyproject`/`uv.lock` bump 0.13.0→0.14.0.

**Backlog captures (commits `cad2890`, `79edb05`):** CS1 (tồn lot-history modal confusing + suspected
duplicate system rows), CS2 (trừ-lùi review + the existing `convert_co_stock.py` + dependency sweep;
strategy **DECOUPLE**), XX1 (NVL có xuất xứ/phụ lục X → origin bucket → LVC/RVC), LK1 (review "Chốt"
lock-able logic).

**Verify + deploy.** file-mode suite **576 passed**; DB recalc/fold/parity (the area P0 touches) **45 passed**
with `.env`; e2e `bangke_split` 24/24 + new `bangke_bg1_fix` 9/9 with screenshot eval. ff-merged 10 commits
to `main`, pushed `origin main`, watched CI to success, confirmed prod `/version` = 0.14.0.

## Decisions Made
- **Soft delete (keep row, fold + gạch mờ)** over hard delete — restores the template's original design,
  index-stable, recoverable. (User chose this.)
- **Delete warning only on bulk**, not single (single is soft + Ctrl+Z). (User chose.)
- **"Tính bảng kê" contextual, keep 2-step** (not auto-calc-on-Load-BOM, not full-auto) — preserves operator
  control over shared-tồn allocation order. (User chose.)
- **trừ-lùi → DECOUPLE** (vs audit/harden) — make it one-time converted data, remove embedded fold. Big,
  parked to CS2 with `/discover`. (User chose.)
- **Index-keyed overrides kept** (now safe because materials no longer shrinks); stable-ID keying noted as
  a future hardening for the added-row-delete edge, not done now.
- **Hunk-split commits via `git apply --cached`** (env has no `git add -p`) to keep P0 vs P1-P3 clean across
  the two shared files (`co_case.html`, `co_case_context.py`).

## What Didn't Work / Gotchas
- **Investigation agents disagreed** on whether deleted rows stay in `materials` — had to read code myself.
  Lesson: for a subtle off-by-one/data-flow bug, arbitrate agent findings against the source.
- **CHANGELOG parser truncates wrapped bullets.** `app/changelog.py` only matches `^[-*] ` lines; indented
  continuations are dropped. First draft had multi-line bullets → web showed only the first line. Fixed by
  writing each bullet on ONE line. (Existing older entries are also silently truncated — left as-is.)
- **Local `/version` shows 0.13.0** even after bump — the dev server's `.env` sets `CO_VERSION=0.13.0`,
  overriding the pyproject dev fallback. Not a bug; prod bakes from pyproject (0.14.0) at build.
- **Stale `tinsu/main` tracking ref** reported "69 commits ahead" — misleading; after `git fetch` both
  `origin/main` and `tinsu/main` were `09509ae` and the real delta was 10. Always fetch before trusting ahead/behind.
- `/version` is JSON (monitoring); the human changelog page is `/whats-new` (auth-gated in prod).

## Open Items
- **Old corrupted cases don't auto-heal** (shrunken materials from old deletes). Fix-forward only (re-Load
  BOM / re-Tính). No migration. Repro case `growatt-vn/co-case-e44fe2065b62`.
- **Stable-ID override keys** (vs positional index) — robustness for deleting *added* rows; deferred.
- Backlog priorities for next session: CS2 (DECOUPLE, big), XX1, LK1, CS1, then B6/B7.
- `feat/rd3-bangke-split` fully merged — safe to delete.
