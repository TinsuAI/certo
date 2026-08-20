# 2026-08-20 — UI redesign on branches, plus the bảng kê state bugs it uncovered

**Where the work is.** Two git worktrees, neither pushed, `main` untouched in both repos:

| | Worktree | Branch | Commits |
|---|---|---|---|
| CO | `../barry-CO-redesign` | `redesign/2026-08-ui` | 26 |
| Data Hub | `../data-hub-redesign` | `redesign/2026-08-ui` | 14 |

Dev servers ran from `/tmp/.../scratchpad/serve_co.py` and `serve_dh.py` — plain python
wrappers whose command line contains neither "uvicorn" nor the port, because sub-agents kept
killing the servers with `pkill -f uvicorn`.

## What Was Done

**1. UI redesign, both apps.** Ported the visual system from `custom-kie/design/hifi` (an
Audit-HQ / GOV.UK derivative). The leverage point: both apps were already ~100% `var()`-driven
off one `body[data-theme]` block (1,164 and 524 call sites), so remapping those values
reskinned every page at once. Top-nav-plus-nested-`<details>` became a 52px navy header plus a
228px grouped sidebar; dense tables with tabular numerics; a `/design` component gallery in
each app. Contract in `.ai/features/2026-08-20-ui-redesign/DESIGN.md`, followed by 12 parallel
agents on disjoint file sets.

**2. Real bugs found and fixed** (all in CO, all the same family — state that travels one way
through a form round-trip):

- `f42ecb5` + `97334a0` — **client config reset by a partial POST.** Every CO-owned field was
  read with `form.get(name, default)`, so absence was indistinguishable from "operator chose
  the default". A POST of just `legal_name` reset `allocation_code_strategy`, which on
  growatt-vn takes BOM matching from 2,145/2,236 to 101/2,236. Presence-gated field by field;
  the checkbox gets an explicit `features_section` marker because an unchecked box is
  legitimately absent.
- `fe4fd22` — **deleted rows reappeared on the bảng kê still labelled as removed.**
  `data_status_label` had a hidden input and a parser entry; `deleted` had neither. A save kept
  the label and dropped the flag the fold reads. The badge now derives from the same flag the
  fold uses, so the two cannot disagree. Same commit: the literal string `"None"` that had been
  rendered into a hidden input, posted back and stored as data; and a 49-char warning squeezed
  into the 20px left in a 7.2rem column, wrapping one character per line (~500px row).
- `61e1247` — **any form submit wiped `material_overrides` on every sheet.** `case_from_form`
  builds the case with a hardcoded `origin_sheet_states: {}` and no form field carries the
  override maps. The BOM version picker submits that form, so changing one sheet's version
  discarded every substitution in the case and the next Tính tất cả rebuilt the originals with
  no trace. Restores the sheet states from the persisted record, as `load-bom` already did.
- `cf08192` — **sheet state read on two axes.** `origin_sheet_status` mixed progress, an action
  result and a verdict in one badge, and `bom_loaded` covered both "chưa tính" and "đã tính
  nhưng bị chặn". Split into progress (Chưa tính → Đã tính → Đã chốt, driven by the
  has-been-calculated bit) and condition (Cần tính lại → Cần xử lý: <lý do> → Sẵn sàng chốt).
- `e084b27` — **`calc_seq`**, a deterministic per-case counter bumped wherever a sheet's numbers
  are recomputed, so "was recalculated" is a positive signal rather than an inference from
  unchanged bytes.

**3. Data repair on a live case.** johnson-vn `co-case-e0b390ead3b0`: 80 rows across three
sheets had the removed label without the flag. Repaired through `POST /origin/sheet/{code}/save`
with `deletes` so each sheet carries one undo step. LVC did not move (those rows carried no
value); the bảng kê did — 23/24/35 exported rows instead of 44/59/59. Recorded in
`ROUND-STATE.md`.

**4. Cross-route invariant harness** (`tests/test_case_state_invariants.py`) — an invariant
registry, a route × invariant matrix, and seeded random walks. See "What Didn't Work".

## Decisions Made

- **App identity split.** Data Hub = navy `#1d3557` (data plane), CO = indigo `#4338ca` (logic
  plane), both keeping navy `--primary` for actions. Taken from the reference system's own rule.
- **Redesign stays branch-only.** Both repos deploy prod on push to `main`.
- **`preserve_origin_products` stays `False` on `/evaluate`.** The version picker posts that
  form, and changing version must rebuild the sheet from the new BOM. The override loss was a
  separate cause; fixing it by flipping this flag would have broken the picker.
- **`calc_seq` is a counter, not a timestamp** — deterministic so tests reproduce, monotonic so
  "changed" is decidable. Lives in `origin_sheet_states`, which `update_case_record` persists
  and `origin_case_revision` deliberately does not hash, so stamping cannot cause a false 409.
- **Two test assertions were updated, not worked around**: QA issue #17's tabs-bar check now
  targets the sidebar that replaced it, and the customs FX page asserts the Vietnamese phrasing
  that replaced the English `app-level`.

## What Didn't Work

- **The invariant harness produced three findings; all three were wrong.** `bulk-substitute`
  "does not cascade" — measured with a `calc_seq` that `attach_origin_sheet_states` was
  stripping on every attach, because that function rebuilds each state from a fixed key list.
  `load-bom` "drops the other sheets" — only for an empty-form POST; the real button is a submit
  of the whole `#co-case` form. `/evaluate` — the one real bug, but found by reading code, not
  by the harness, which still cannot reproduce it in-process. **Every real bug this session came
  from reading code and probing by hand.** Two load-bom cells are `skip`ped with the full
  exclusion list rather than asserting a defect that could not be substantiated.
- **The harness polluted the shared demo client.** It uploaded a modified BOM and 12 BCCT rows
  to `growatt`, whose store lives in the app's real data directory, breaking
  `test_vn_origin_resolver` for every later run. Rolled back by hand (surgical edit of a 97MB
  `state.json`: 19,920 → 19,908 rows, `latest_version` back to v6). The BOM rewrite is gone; the
  module still writes BCCT rows to a shared client and needs its own client before CI.
- **A browser click on the last sheet's Load BOM could never be made to fire** across four
  puppeteer attempts (navigation destroying the execution context, wrong panel, `setTimeout`
  racing browser close). That gap is why the load-bom cells are skipped rather than resolved.
- **`pkill -f uvicorn` from a sub-agent** killed both dev servers repeatedly, and one instance
  started Data Hub from the main checkout instead of the worktree.

## Open Items

1. **Nothing is pushed.** Both branches need review, then a merge decision. The config fix
   (`f42ecb5`, `97334a0`) and the bảng kê fixes are independent of the reskin and cherry-pickable
   if you want them in prod before the visual round.
2. **Data Hub dark theme is untuned** — `CONTRAST-AUDIT.md` has computed WCAG failures and the
   replacement hex values.
3. **The invariant harness is a diagnostic tool, not a gate.** KNOWN GAPS in its docstring: it
   cannot reproduce `/evaluate` in-process, and its world is not isolated between runs.
4. **Flow proposals are unbuilt by design** — `FLOW-PROPOSAL.md` (CO 529 lines, DH 760). The CO
   one measures the origin step at 3,992,010 bytes with 15,414 hidden inputs and 274,908 bytes of
   inline JS shipped on all five case steps.
5. **Data Hub still has no issue references on its commits**, which its own `AGENTS.md:104`
   requires; and `uploads.html:51` links to a 404 (`bcct/parse-mapping/{uid}` vs
   `bcct/upload/mapping/{uid}`), and BCCT is the only ingest flow with no reject route.
6. **5,314 lines of inline JS in `co_case.html` have zero test coverage.** 32 e2e scripts exist
   under `.ai/scripts/` but none run in the suite, and they hardcode real client case IDs.
