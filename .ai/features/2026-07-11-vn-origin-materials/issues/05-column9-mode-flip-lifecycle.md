# 05 — Column-9 mode flip lifecycle

Status: ready-for-agent — tracked on GitHub: [TinsuAI/co#10](https://github.com/TinsuAI/co/issues/10) (tracker of record)

## Parent

`.ai/features/2026-07-11-vn-origin-materials/spec.md` (build-order ticket 4, second
half — split out so ticket 04 stays one context window).

## What to build

The per-case column-9 mode override gets its control surface (precedent: the
per-case currency-mode override), and flipping the mode — client default or per-case
— can never leave a dossier silently mixing two conventions. Flipping marks
mismatched `calculated` sheets stale (which already disables lock and blocks export);
`draft`/`bom_loaded` sheets are untouched; locked sheets are never touched — they
show a mismatch chip and a warning listing them instead, because their snapshot is
what was filed.

## Acceptance criteria

- [ ] Per-case mode override can be set and cleared from the case; the ticket 04
      resolver precedence (case override > client default > code default) is honoured
      end-to-end.
- [ ] Flipping the mode marks every mismatched `calculated` sheet stale; re-Tính
      picks up the new mode and clears the staleness.
- [ ] `draft`/`bom_loaded` sheets unaffected by a flip.
- [ ] Locked sheets are never modified or blocker-ized by a flip: mismatch chip on
      the sheet + a warning listing all mismatched locked sheets.
- [ ] A three-belt re-check (status derivation, lock gate, export blockers) covers
      the save-route status hardcode — a stale mismatched sheet cannot be locked or
      exported through the bypass.
- [ ] The flip surface states the consequence before confirming (N calculated sheets
      will go stale, M locked sheets will show a mismatch).

## Blocked by

- 04 — Column (9)/(12)/(13) materialization: modes, normalization, unknown label
