# BCCT upload preview — make the Apply gate discoverable

**Issue:** #56 · **Related finding:** #57 (server-side ack enforcement, deferred)
**Date:** 2026-07-27

## Problem

Johnson VN uploaded a new BCCT and got stuck on "Xác nhận thay đổi BCCT". They
ticked "Xác nhận ghi đè tất cả 51 dòng đã đổi" (`confirm_diffs`) but the
"Apply confirmed changes" button stayed grey, so the import never ran.

## Root cause (not a logic bug)

The button is disabled by JS whenever `uom_drift_blocks_confirm` is true and
re-enabled **only** by the `ack_uom_drift` checkbox, which lives in a separate
panel (the ⚠ UoM-drift banner) at the top of the page:

- `app/templates/clients/_uom_drift_banner.html:127` — disables `btn-primary` on `DOMContentLoaded`.
- `_uom_drift_banner.html:104-109` — re-enables only on `ack_uom_drift` change.
- `app/templates/clients/bcct_upload_preview.html` — `confirm_diffs` is wired to nothing that touches the button.

The gate is intended (staff must acknowledge cross-family UoM drift). The defect
is discoverability: the ack checkbox is far from the button, the disabled button
gives no reason, and the 604 "khác họ" rows each with a "+ hệ số" link imply the
operator must resolve all 604 — they do not. Ticking ack alone unlocks Apply.

## Yellow vs blue (customer question)

- **VÀNG "khác họ"** = different UoM family, no confirmed conversion factor
  ("thiếu hệ số" blocks; "1 (mặc định)" is an unconfirmed 1:1 default).
- **XANH "khác họ ✓"** = different family but an explicit factor exists
  (client_specific = 1.0) → convertible, does not block.

## Change

`bcct_upload_preview.html` only (shared banner partial untouched):

1. A locked-state caption above the button, shown when `uom_drift_blocks_confirm`:
   says the button is locked, links to + focuses the ack checkbox, and corrects
   the two misconceptions (`confirm_diffs` does not unlock; per-row factors are
   optional). Hidden when ack is ticked.
2. A small inline script wiring the jump-link scroll/focus and the hint's
   hide-on-ack. Guards for element absence; no change to button enable/disable
   ownership (still the banner's).

Copy is neutral Vietnamese, no personal pronouns.

## How to Apply (answer for the customer)

Tick the ack checkbox in the ⚠ "Đơn vị tính khác họ — cần xác nhận" banner:
☑ "Tôi đã xem và xác nhận drift khác họ này dù không thể tự quy đổi." — this is
what unlocks the button. Also tick "51 dòng đã đổi" to write the invoice_date
changes. No need to add "+ hệ số" to the 604 rows.

## Tests / proof

- `tests/test_uom_ingest_drift.py::test_bcct_preview_apply_gate_hint_when_blocking_drift`
  — route-level: blocking drift + diff row → preview HTML carries the hint,
  jump link, and the factor-optional clarification. RED before, GREEN after.
  Full drift file: 16 passed.
- `ui_smoke.py` (real page on :8754): load → button disabled + hint visible;
  tick ack → button enabled + hint hidden. See `screenshots/01-locked.png`,
  `screenshots/02-unlocked.png`.

## No-JS behaviour

The button lock is JS-driven (the banner disables it on `DOMContentLoaded`).
So the hint is `hidden` by default and revealed by the same script — without
JS the button is not actually disabled, and showing a "locked" claim there
would be false.

## Deferred / observed (pre-existing, not introduced here)

- **#57** — `upload_preview_confirm` (`app/routes/bcct.py:975-977`) reads only
  `confirm_diffs`/`confirm_orphans`, never `ack_uom_drift` — the gate is
  client-side JS only. Filed separately to keep this diff focused.
- **#58 (FIXED here)** — form-restore desync. On a reload where the browser
  restores `ack.checked=true` without firing `change`, the banner
  (`_uom_drift_banner.html`) used to force-disable the button on
  `DOMContentLoaded` and never re-enable it. Now the handler mirrors the ack's
  current state. Deterministic repro added to `ui_smoke.py` (`[restore]`
  scenario), red before / green after. Touches the shared banner, so verified
  on both BCCT and BOM banner route tests.
