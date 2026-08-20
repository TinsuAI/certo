# Redesign round state — 2026-08-20, ~00:36

## Where the work lives

| | Worktree | Branch | Live URL |
|---|---|---|---|
| CO | `/home/vp/workspace/client/barry-CO-redesign` | `redesign/2026-08-ui` | http://127.0.0.1:8001 |
| Data Hub | `/home/vp/workspace/client/data-hub-redesign` | `redesign/2026-08-ui` | http://127.0.0.1:8754 (`admin@data-hub.local` / `admin123`) |

Nothing was pushed. `main` is untouched in both repos, and both main checkouts are clean.

Servers run from `/tmp/.../scratchpad/serve_co.py` and `serve_dh.py` — plain
python wrappers whose command line contains neither "uvicorn" nor the port, so a
sub-agent's `pkill -f uvicorn` cannot kill them. They reload on `.py/.html/.css`
edits. CO reads the redesigned Data Hub, so the two together are one stack.

## Landed

- CO: 5 commits — shell (navy header + 228px grouped sidebar), token/font remap,
  case workspace rail + dense bảng kê grid, list/table pages, forms and settings.
- Data Hub: 4 commits — shell, one visual grammar across the upload flows,
  upload-preview outcome states, commit bar and callouts.
- `/design` component gallery live in CO (and being built in Data Hub).
- Screenshots in each repo's `.ai/features/2026-08-20-ui-redesign/screenshots/`,
  written by `ui_smoke.cjs` in the same folder.

## Documents produced this round

- `DESIGN.md` — the contract every agent followed (token remap table, typography,
  shell structure, component specs). Identical in both repos.
- `FLOW-PROPOSAL.md` — CO 529 lines, Data Hub 760 lines. Measured IA and flow
  analysis; route-level changes are proposals, nothing structural was built.
- `COPY-AUDIT.md`, `CONTRAST-AUDIT.md` — in progress at the time of writing.

## Open at the cut

1. Both apps still render two client navigations at once: the new sidebar plus
   the surviving `.page-bar` + `.tabs` dropdowns from `_client_nav.html`.
2. Uncommitted edits remain in both worktrees from agents that were still running
   (CO 6 paths, Data Hub 50). Review with `git status` before committing.
3. `uv run pytest` has not been run to completion on the merged state of either
   branch. Do that before any merge to `main` — a push to `main` deploys prod.
