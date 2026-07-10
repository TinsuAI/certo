# Issue tracker: GitHub Issues (`TinsuAI/co`) + local specs in `.ai/`

Since 2026-07-11, **implementation issues/tickets are tracked on GitHub Issues**
(`TinsuAI/co`, via the `gh` CLI). Feature specs, backlog, and session state stay as
local markdown under `.ai/`. Skills like `/to-issues`, `/to-tickets`, `/to-prd`,
`/triage`, and `/implement` read from and write to these locations.

## Where things live

- **Feature specs / PRDs** — `.ai/features/YYYY-MM-DD-<feature-slug>.md` (single file), or a
  directory `.ai/features/YYYY-MM-DD-<feature-slug>/` when a feature needs multiple files.
  Unchanged: specs are repo docs, not tracker items.
- **Implementation issues/tickets** (produced by `/to-issues` / `/to-tickets`) — **GitHub
  Issues on `TinsuAI/co`**. Publish one issue per ticket **in dependency order** (blockers
  first) so each issue's "Blocked by" section can reference real `#N` numbers. Reference the
  parent spec's repo path in the issue body. Apply the `ready-for-agent` label unless
  instructed otherwise. Archive copies may also be written under
  `.ai/features/<feature-slug>/issues/<NN>-<slug>.md` with a `Status:` line pointing at the
  GitHub issue — GitHub is the source of truth when they disagree.
- **Durable backlog** — `.ai/BACKLOG.md`. Captured-but-unscoped items live here; `.ai/STATUS.md`
  "Next Steps" is the prioritized slice.
- **Data Hub API requests** — `.ai/api-requests/YYYY-MM-DD-<slug>.md` (existing convention; see
  the "Data Hub API Requests" section in `AGENTS.md`).

Use today's date for the `YYYY-MM-DD` prefix — it matches the existing `.ai/features/` and
`.ai/sessions/` naming.

## Triage state

Triage roles are **GitHub labels** on `TinsuAI/co` (created 2026-07-11): `needs-triage`,
`needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. Role definitions in
`triage-labels.md`. Local archive/spec files may additionally carry a `Status:` line.

## When a skill says "publish to the issue tracker"

`gh issue create` on `TinsuAI/co`, one issue per ticket, in dependency order, with the
appropriate triage label. No AI attribution or trailers in issue bodies (same rule as
commit messages).

## When a skill says "fetch the relevant ticket"

`gh issue view <number> --comments`. The user will normally pass the issue number, a URL,
or a feature slug.

## History

Before 2026-07-11 this repo tracked issues as local markdown only (`.ai/features/<slug>/issues/`).
Those files remain as archives. The first GitHub batch is #6–#13 (VN-origin feature,
spec `.ai/features/2026-07-11-vn-origin-materials/spec.md`).
