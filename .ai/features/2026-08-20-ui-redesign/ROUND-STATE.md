# Redesign round state — 2026-08-20

## Where the work lives

| | Worktree | Branch | Live URL |
|---|---|---|---|
| CO | `/home/vp/workspace/client/barry-CO-redesign` | `redesign/2026-08-ui` | http://127.0.0.1:8001 |
| Data Hub | `/home/vp/workspace/client/data-hub-redesign` | `redesign/2026-08-ui` | http://127.0.0.1:8754 (`admin@data-hub.local` / `admin123`) |

Nothing was pushed. `main` is untouched in both repos and both main checkouts are
clean. CO reads the redesigned Data Hub, so the two run as one stack.

Component galleries: http://127.0.0.1:8001/design and http://127.0.0.1:8754/design.

Servers run from `scratchpad/serve_co.py` and `serve_dh.py` — plain python
wrappers whose command line contains neither "uvicorn" nor the port number, so a
sub-agent's `pkill -f uvicorn` cannot match them. They reload on `.py/.html/.css`.

## What landed

CO — 12 commits: navy 52px header with company switcher, 228px grouped sidebar,
token and font remap, case workspace rail + dense bảng kê grid, list and table
pages, forms and settings, `/design` gallery, and the client tabs bar removed
because the sidebar already carries every one of its destinations.

Data Hub — 12 commits: the same shell, one visual grammar across the six
upload → preview → commit flows, upload-preview outcome states (new / updated /
orphan), client workspace as a status board, admin and jobs pages, login screen,
`/design` gallery, one page bar per page instead of two.

## Documents in this folder

- `DESIGN.md` — the contract every agent followed: token remap table, typography,
  shell structure, component specs. Identical in both repos.
- `FLOW-PROPOSAL.md` — CO 529 lines, Data Hub 760 lines. Measured IA and flow
  analysis. Route-level changes are proposals; nothing structural was built.
- `COPY-AUDIT.md` — Vietnamese term table across both apps, buttons that name the
  mechanism instead of the result, error messages with no next step.
- `CONTRAST-AUDIT.md` — computed WCAG ratios for every foreground/background pair
  the new palette produces, light and dark, both apps.
- `ui_smoke.cjs` — read-only screenshot walk; writes to `screenshots/` beside it.

## Known open items

0. ~~**`/evaluate` wiped `material_overrides` on every sheet.**~~ **Fixed**
   (`61e1247`). This also closed the `origin_case_from_request` asymmetry logged
   below: `load-bom` and `/evaluate` are the only two routes on the form branch,
   and both now restore the sheet states the form cannot carry.

1. ~~**CO `save_client_config_route`** — a partial POST reset the CO-owned config
   from defaults.~~ **Fixed** (`f42ecb5`): presence-gated field by field, and a
   POST carrying no config field at all no longer saves or rebuilds the indexes.
   Three regression tests in `tests/test_config_partial_post_preserves.py`.
2. **CO origin step renders the whole case in one document** — 3,992,010 bytes for
   a real Johnson case, 15,414 hidden inputs, 274,908 bytes of inline JS shipped
   on all five case steps. `?sheet=` does not reduce it. Fixing it needs a route
   change, so it stayed a proposal.
3. **Data Hub dark theme is functional but untuned** — the ramps are a first pass;
   `CONTRAST-AUDIT.md` has the measured failures and the replacement values.
4. **`.rail` / `.rail-s` are styled but unused in Data Hub** — no template emits a
   pipeline yet; the stale `.rail { top: 72px }` rule is wrong for a 52px header.
5. **Data Hub `uploads.html:51` links to a 404** — `…/bcct/parse-mapping/{uid}`;
   the real route is `…/bcct/upload/mapping/{uid}` (`bcct.py:325`).
6. **BCCT is the only ingest flow with no reject route** — the other five have
   `…/preview/{id}/reject`; a wrong BCCT file survives until expiry.

## Sheet state, two axes (`cf08192`)

`origin_sheet_status` mixed progress, an action result and a verdict in one
badge, and `bom_loaded` covered both "chưa tính" and "đã tính nhưng bị chặn".
Split into `origin_sheet_progress` (Chưa tính → Đã tính → Đã chốt, driven by the
has-been-calculated bit, not the stored status) and `origin_sheet_condition`
(Cần tính lại → Cần xử lý: <lý do> → Sẵn sàng chốt). The two chips render side by
side; the verdict no longer replaces the progress badge. `locked`'s label became
`Đã chốt`. Presentation only — stored statuses and the lock/export gates are
untouched. 11 tests in `tests/test_origin_sheet_two_axis.py`.

## Data repair on a live case — johnson-vn `co-case-e0b390ead3b0`, 2026-08-20

80 material rows across three sheets carried the label "Đã xoá khỏi bảng kê"
while their `deleted` flag was gone, so they were rendering as ordinary numbered
rows and were still being exported. Cause: `case_from_form` rebuilds the case
with a hardcoded `origin_sheet_states: {}` and no form field carries the override
maps, so any form submit cleared `material_overrides` on every sheet. Fixed in
code by `61e1247`; the already-damaged rows were repaired by hand.

Repaired through the supported route (`POST /origin/sheet/{code}/save` with
`deletes`), never by writing to the store, so each sheet carries one undo step —
press ↶ on a sheet to revert it.

| Sheet | Rows restored | Exported rows after | LVC before | LVC after |
|---|---|---|---|---|
| MFW0520-17 | 21 | 23 | 37.40 | 37.40 |
| MFW0504-39 | 35 | 24 | 48.73 | 48.73 |
| MFW0502-39 | 24 | 35 | 60.56 | 60.56 |

LVC did not move: those rows carried no value (đơn giá 0, non-origin, empty
`material_value`), so they never contributed to VNM. The numbers were never
wrong. What changed is the bảng kê — 80 rows are excluded from the export again,
which is what the operator originally asked for.

MFW0525-39 was untouched: it was the one sheet that still held its overrides, and
the only one with no lost rows. That correspondence is what confirmed the cause.

## Tests

Two assertions were updated because the surface they named was removed, not
because they were failing on their own terms:

- `test_client_tabs_stay_visible_inside_co_workflow` — QA issue #17 requires Tồn
  CO / BCCT / NCC / config to stay one click from an open dossier. That moved
  from the tabs bar to the sidebar, so the assertion now checks the sidebar.
- The customs FX page asserted the English string `app-level`; the page now states
  the same scope in Vietnamese ("dùng chung cho mọi công ty").

Two real regressions from the reskin were found and fixed: the Data Hub page
counter lost its "Trang" label, and the BCCT advisory callout lost its "Lưu ý"
title.
