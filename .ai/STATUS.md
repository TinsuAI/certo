# Project Status

> **Read this first: the work is NOT on `main`.** This file lives on branch
> `redesign/2026-08-ui` in the worktree `../barry-CO-redesign`. A session started in
> `barry-CO-main` will see the older `main` copy of this file. Nothing was pushed.

## Current State

**2026-08-20 — UI redesign of CO + Data Hub, on branches, plus five bảng kê state bugs fixed
along the way.**

| | Worktree | Branch | Commits | Suite |
|---|---|---|---|---|
| CO | `../barry-CO-redesign` | `redesign/2026-08-ui` | 26 | 1180 pass / 19 skip / 2 xfail |
| Data Hub | `../data-hub-redesign` | `redesign/2026-08-ui` | 14 | 1687 pass / 16 skip |

`main` is untouched in both repos and both main checkouts are clean, so prod (`0.18.0`,
`d51581f`) is unaffected. Both branches are review-ready; nothing is pushed.

The redesign is a token remap plus a shell replacement: both apps were already ~100%
`var()`-driven off one `body[data-theme]` block, so redefining those values reskinned every
page. Top-nav-plus-nested-`<details>` became a 52px navy header + 228px grouped sidebar. Design
contract, flow proposals, copy audit and contrast audit are in
`.ai/features/2026-08-20-ui-redesign/`.

**The five bugs are independent of the reskin and cherry-pickable**: `f42ecb5` + `97334a0`
(partial config POST reset CO-owned config), `fe4fd22` (deleted rows reappeared on the bảng kê;
literal `"None"` stored as data; a warning wrapping one character per line), `61e1247` (any form
submit wiped `material_overrides` on every sheet — the BOM version picker submits that form),
`cf08192` (sheet state split into progress + condition).

## Recent Changes

- Reskin of both apps; `/design` component gallery in each.
- CO: client tabs bar removed (the sidebar carries every destination); DH: one page bar per page.
- `calc_seq` — a deterministic per-case counter stamped wherever a sheet's numbers are
  recomputed, carried through `attach_origin_sheet_states` (which rebuilds states from a fixed
  key list and drops anything not carried explicitly).
- Data repair on johnson-vn `co-case-e0b390ead3b0`: 80 rows across three sheets had the
  "Đã xoá khỏi bảng kê" label without the flag. Repaired via the supported `/save` route so each
  sheet has one undo step. LVC unchanged; exported rows now 23/24/35 instead of 44/59/59.

## Next Steps

1. **Review both branches and decide on merge.** Start the servers (below) and click through;
   `/design` on each app is the fastest way to judge the visual system.
2. **If prod needs the logic fixes before the visual round**, cherry-pick `f42ecb5`, `97334a0`,
   `fe4fd22`, `61e1247`, `cf08192` — none of them depend on the reskin.
3. **Data Hub dark theme is untuned.** `CONTRAST-AUDIT.md` lists computed WCAG failures with
   replacement hex values.
4. **Give the invariant harness its own client before trusting it in CI** — it writes BCCT rows
   into the shared demo client `growatt`, whose store is the app's real data directory.
5. **Data Hub commits carry no issue references**, which its own `AGENTS.md:104` requires.

## Blockers

None technical. The only gate is your review of the two branches.

## Notes for Next AI Session

- **Dev servers**: CO `:8001`, Data Hub `:8754`, both from the redesign worktrees, started via
  `scratchpad/serve_co.py` / `serve_dh.py`. Those wrappers exist because sub-agents kept running
  `pkill -f uvicorn`; their command lines contain neither "uvicorn" nor the port. Port 8754 is
  pinned — CO's JWT issuer validation expects exactly that origin.
- **The bug family of this session**: state that travels one way through a form round-trip. A
  field with a hidden input but no parser entry (or the reverse) silently diverges. When
  something "reappears after saving", look for the missing half of the round-trip first.
- **`attach_origin_sheet_states` rebuilds each sheet state from an explicit key list.** Anything
  you add to a sheet state must be carried there or it is stripped on the next attach — this
  cost a full round of wrong conclusions before it was found.
- **The invariant harness produced three findings and all three were wrong**; every real bug this
  session came from reading code and probing by hand. Treat its output as a prompt to
  investigate, not as evidence. Its KNOWN GAPS are in the module docstring.
- **Do not exercise a route with a payload the real client never sends.** Three wrong verdicts
  came from exactly that — an empty form POST, and measuring with a stamp that was not persisting.
- **5,314 lines of inline JS in `co_case.html` have zero test coverage.** The 32 e2e scripts in
  `.ai/scripts/` are manual, need a live server, and hardcode real client case IDs.
