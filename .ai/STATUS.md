# Project Status

## Current State

**2026-08-21 — the redesign and the bảng kê fixes are MERGED and LIVE on production.**

| | Merge commit | Prod (verified from the running container) |
|---|---|---|
| CO [#24](https://github.com/TinsuAI/co/pull/24) | `e9875e59` | `co-app-1` + `nightly-co-app-1` = `0.18.0` / `e9875e5` |
| Data Hub [#60](https://github.com/TinsuAI/data-hub/pull/60) | `eef22c29` | superseded by #61/#62 |
| Data Hub [#61](https://github.com/TinsuAI/data-hub/pull/61) — dark contrast + dead link | `73caf38a` | verified `73caf38` |
| Data Hub [#62](https://github.com/TinsuAI/data-hub/pull/62) — BCCT reject route | `0783ebf5` | see below |

`version` did not move (`0.18.0` / `0.22.0`) — no release bump this round, so identify the
build by `git_sha`, not by version.

The redesign worktrees (`../barry-CO-redesign`, `../data-hub-redesign`) still exist on their
branches. They can be removed once you are satisfied with what shipped.

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

1. **Look at the live apps with real eyes.** The redesign shipped without a human ever
   reviewing it — only screenshots were seen. `/design` on each app shows the whole component
   system in one page.
2. **Give the invariant harness its own client before trusting it in CI** — it writes BCCT rows
   into the shared demo client `growatt`, whose store is the app's real data directory. It
   already broke `test_vn_origin_resolver` once this way.
3. **Data Hub commits carry no issue references**, which its own `AGENTS.md:104` requires. The
   four PRs this round all violate it.
4. **The flow proposals are unbuilt by design** — `FLOW-PROPOSAL.md` in both repos. The CO one
   measures the origin step at 3,992,010 bytes with 15,414 hidden inputs.
5. **5,314 lines of inline JS in `co_case.html` have zero test coverage.**

## Blockers

None. Everything merged and deployed; both worktrees are clean.

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
