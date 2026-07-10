# 03 — Shortage three-belt guard

Status: ready-for-agent — tracked on GitHub: [TinsuAI/co#8](https://github.com/TinsuAI/co/issues/8) (tracker of record)

## Parent

`.ai/features/2026-07-11-vn-origin-materials/spec.md` (build-order ticket 3).
Ships independently — legal urgency; do not gate on any other ticket.

## What to build

A sheet whose consumed quantity exceeds its matched import lots (shortage), including
a material with no matched lot at all, can no longer be locked (chốt) or exported.
The shortfall has no lawful value on the bảng kê (no import declaration and no VAT
invoice backs it). The user sees a shortage-specific block reason naming the problem
and the remedy — supply the missing document (match the import declaration / enter
the VAT invoice) — never an estimated price. The fallback-price path that today
prices a no-lot material from BOM/catalog is removed.

## Acceptance criteria

- [ ] Belt 1: the calculated-sheet-status derivation flags shortage (partial
      shortfall and no-lot materials both count).
- [ ] Belt 2: the lock gate re-checks shortage at action time and returns a
      shortage-specific reason (not a generic "not calculated"), so the user is not
      looped through "press Tính → re-block".
- [ ] Belt 3: shortage appears in the export blockers.
- [ ] The save-route / bulk-substitute status hardcode cannot bypass the guard
      (tests mirror the existing `declarable_unmatched` guard tests, belt by belt).
- [ ] The fallback-price path for no-lot materials is removed; no value on the sheet
      exists without a citable document; RVC is never computed from a fallback price.
- [ ] HARD constraint honoured: the status-downgrade branches are untouched —
      `missing_price` enforcement still works (explicit test proving missing-price
      sheets remain blocked).
- [ ] UI copy for the block states the remedy (supply the document), not a price
      workaround.

## Blocked by

None — can start immediately.
