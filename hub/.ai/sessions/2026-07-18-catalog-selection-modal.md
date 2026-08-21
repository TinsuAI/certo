# 2026-07-18 — Catalog candidates: per-row selection + accept modal (#55), then push to prod

**Written retroactively on 2026-07-19.** The session itself left no log; this is
reconstructed from the four commits, `.ai/features/2026-07-18-catalog-selection-modal/`,
and the live prod state verified on 2026-07-19. Anything not derivable from those
is marked as such.

## What was done

### #55 — per-row selection + single-row accept in a modal

Two shapes on the candidate page didn't fit how it is used:

1. **No subset.** "The filter IS the rule" (#35) meant the bulk button approved
   the *whole* filtered set. You could not approve 5 codes and skip the 6th.
   The server deliberately re-applied the filter and ignored any client-sent
   code list — ADR-0001's "no trusted client list".
2. **A form inside a table cell.** Per-row «Duyệt» was a
   `<details><summary class="btn-primary">` expanding 5 fields into the cell.

**Selection is two-tier and pagination-aware.** A checkbox per row, `name="codes"`,
bound to the approve form via `form="bulk-form"` so the table keeps its own reject
forms un-nested. A header checkbox takes the visible page (indeterminate when
partial). Once the page is fully checked and more remains beyond it, a banner
offers «Chọn tất cả N mã khớp bộ lọc», which sets a hidden `select_all_matching`
flag. The approve button tracks the selection: disabled at zero → «Duyệt N mã đã
chọn» → «Duyệt toàn bộ N mã khớp bộ lọc».

**The server does not trust the list — it intersects.** `bulk_accept` now takes
`codes[]` or `select_all_matching`. For an explicit list it recomputes
`_filter_pending(...)` and accepts only `selected ∩ filtered-pending`. A code that
is stale, already a material, machinery, or outside the active filter is dropped;
a code that was never pending cannot be forced in through the POST. The filter
stays the outer bound — it can only shrink the writable set, never grow it.
`select_all_matching=1` reproduces the old whole-filter path. Empty submit is now
a no-op, not "approve all". **ADR-0001 was amended** to record this: the
"no trusted client list" property is preserved by intersection rather than by
refusing to read the list.

**The modal is the repo's first `<dialog>`.** Row «Duyệt» is a `<button>` carrying
the row's `data-*`; JS fills one shared native `<dialog>` and `showModal()`s it,
posting to the unchanged `/accept` route. `data-category` mirrors the bulk path's
derivation (`suggested_category`, else flattened-BOM leaf → `nvl`) so the dropdown
prefills correctly instead of defaulting to the first option — a wrong-category
footgun the old inline form also had. A `<noscript>` link to the detail page keeps
the flow usable without JS.

### Review pass (`3bff7d8`) — one finding was a comment asserting something false

Both axes of the two-axis review flagged the same thing: a submit handler that
unchecked row boxes when `select_all_matching` was active, carrying a comment
claiming it stopped the server from "intersecting them and shrinking the set".
That is not what the server does — `bulk_accept` takes `if select_all_matching:
matching = filtered` and never reads `codes` in that branch. The handler prevented
a condition that cannot occur. Removed; the server is robust either way.

Also: `bulk_accept` built its 303 redirect twice (no-match early return + tail),
collapsed to one with `accepted`/`skipped` set to 0 in the no-match branch. The
CHANGELOG entry moved from `### Sửa` to a new `### Thêm` — per-row selection plus
a modal is Added under Keep-a-Changelog, not a fix.

### Proof (`d89869c`) — the smoke actually writes, and is cleaned up

`ui_smoke.py` photographs states without submitting. `e2e_smoke.py` drives the
real approvals: it seeds a small pending queue on a **throwaway** client whose id
ends in `-<8hex>` (so the conftest sweep reclaims it if the run dies), then in a
browser checks two rows and approves (bulk), and opens the modal and accepts
(single), screenshotting before and after each. Verified against the DB: queue
8 → 6 → 5, materials 0 → 2 → 3. The throwaway client is deleted in a `finally`;
`growatt-vn` is never touched.

### The push

`main` (+19 at the start of the day, +23 after #55) was pushed. CI/CD on the
self-hosted runner deployed it. This carried migs **094** and **095**, and closed
out the three warnings the previous STATUS.md carried.

## Verified state (checked 2026-07-19, not on the day)

- Prod runs `git_sha=ebd7bdc`, `version=0.21.0`, `build_time=2026-07-18T05:48:05Z`
  — the same commit as local `main`. `main == origin/main`.
- Prod `hub.schema_migrations`: max `095_growatt_double_dot_placeholder.sql`,
  93 rows, and a filename-by-filename diff against `db/migrations/*.sql` shows
  **nothing missing**. The "prod data is ahead of its migration table" hazard the
  old STATUS flagged is gone — 094 and 095 are applied *and* recorded.
- Suite on the merged tree, serial: **1686 passed, 16 skipped, 0 failed**
  (was 1680; +6 from `test_catalog_candidate_selection.py`).
- Prod auth: `hub.app_settings.api_auth_strict = true`,
  container env `DATA_HUB_API_AUTH_DISABLED=0`.

## Decisions

- **Client-sent selection is accepted, but only as a *restriction*.** The
  alternative — keep refusing the list and add server-side rule syntax — was
  what ADR-0001 ruled out in the first place. Intersection gives the subset
  without a DSL and without trusting the client. Amended into ADR-0001 rather
  than filed as a new ADR, because it revises that ADR's own contract.
- **`select_all_matching` is a separate flag, not an empty list.** "Empty means
  all" was the old implicit behaviour and it is now a no-op; the destructive
  reading of an empty submit is gone.

## What didn't work / was corrected

- The uncheck-on-submit handler (above) — written against a server behaviour
  that does not exist, caught by review, removed.
- The CHANGELOG entry was filed under the wrong Keep-a-Changelog heading and
  moved.

## Open items left by this session

- **Issues #52, #53, #54 stayed open** after the deploy: their commits said
  `Refs #NN`, not `Closes`. Only #55 auto-closed. *(Closed by hand 2026-07-19.)*
- **No STATUS.md update and no session log** — STATUS still described 19
  unpushed commits and pending migrations for a day after they had shipped.
  *(Both fixed 2026-07-19.)*
- **`docs/release-engineering.md` claimed Tier D runs
  `DATA_HUB_API_AUTH_DISABLED=1`.** The live instance has it at `0` with
  `api_auth_strict=true`. This was the "Tier D/P contradiction — needs a human"
  item in STATUS; it resolves against the doc. *(Corrected 2026-07-19, with the
  #26 caveat written in: `api_auth_strict` is a hand-set row that no migration
  seeds, so a restore drops it and `_strict_mode()` defaults false.)*
- **Scoped out of #55, unfiled:** the "Đề xuất" column's four meanings; the
  detail page's own inline accept form (same `<details>` pattern). Reject stays
  a one-click confirm.
- **Release cut still pending** — seven `[Unreleased]` entries (#47, #49, #50,
  #52, #53, #54, #55), version still `0.21.0`.
