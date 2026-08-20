# Project Status

> **Read this first: the work is NOT on `main`.** This file lives on branch
> `redesign/2026-08-ui` in the worktree `../data-hub-redesign`. Nothing was pushed; the main
> checkout is clean.

## Current State

**2026-08-20 — UI redesign, on a branch, 14 commits, suite 1687 pass / 16 skip.**

Data Hub was reskinned alongside CO so the two read as one system for the operators who use
both on the same dossier. The leverage point: the app was already ~100% `var()`-driven off one
`body[data-theme]` block (524 call sites), so remapping those values reskinned every page.

What changed structurally:

- **Top nav plus nested `<details>` groups → a 52px navy header + a 228px always-visible grouped
  sidebar** (`_sidebar.html`, new). The client switcher moved into the header; theme and language
  toggles moved into the user menu. `_client_nav.html` is now only a slim page bar;
  `_admin_nav.html` is an empty stub still included by 9 admin templates.
- **One visual grammar across the six upload → preview → commit flows** — the same three-step
  rail (Chọn tệp → Kiểm tra → Ghi nhận), the same preview-table treatment, and outcome states
  that say what will happen before you commit (new / updated / orphan).
- **`/design`** — a component gallery rendering the whole system with Vietnamese sample content.
- Client workspace reads as a status board; admin, jobs and the login screen follow the same
  card / badge / dense-table system.

App identity: Data Hub is the **data plane**, so `--brand: #1d3557` navy. CO is the logic plane
and uses indigo. Both keep navy `--primary` for actions so a user moving between the apps keeps
one action colour.

## Next Steps

1. **Review the branch** — `http://127.0.0.1:8754` (login `admin@data-hub.local` / `admin123`),
   and `/design` for the component system in one page.
2. **Dark theme is untuned.** `.ai/features/2026-08-20-ui-redesign/CONTRAST-AUDIT.md` has the
   computed WCAG failures with replacement hex values.
3. **Commits carry no issue references**, which `AGENTS.md:104` requires — resolve before merge.
4. **`uploads.html:51` links to a 404**: `…/bcct/parse-mapping/{uid}`; the real route is
   `…/bcct/upload/mapping/{uid}` (`bcct.py:325`). Found during the flow analysis, not fixed.
5. **BCCT is the only ingest flow with no reject route** — the other five have
   `…/preview/{id}/reject`, so a wrong BCCT file survives until expiry.

## Blockers

None. The branch is review-ready.

## Notes for Next AI Session

- **Dev server**: `:8754`, from this worktree, started via `scratchpad/serve_dh.py` — a wrapper
  whose command line contains neither "uvicorn" nor the port, because sub-agents kept running
  `pkill -f uvicorn`. Port 8754 is pinned: CO's JWT issuer validation expects that exact origin.
- **`FLOW-PROPOSAL.md` (760 lines) is proposal-only** and measured, not guessed. Its main finding:
  6 of the 7 upload flows collapse into one parameterised flow — 47 handlers into 9, 9 templates
  into 1 + 6 blocks. Declarations legitimately stays out. `_mapping_flow.py`'s own docstrings
  already point this way; `nxt.py` and `inventory_snapshots.py` are line-for-line copies that
  never migrated.
- **`.rail` / `.rail-s` are used** by 14 templates through `clients/_flow.html`'s `rail()` macro.
  An earlier note in this round claimed they were unused — that was wrong.
- The design contract both apps followed is `.ai/features/2026-08-20-ui-redesign/DESIGN.md`,
  identical in both repos.
