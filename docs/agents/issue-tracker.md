# Issue tracker: Local Markdown (in `.ai/`)

This repo tracks work as markdown under `.ai/`, not on a remote issue tracker. Skills like
`/to-issues`, `/to-prd`, `/triage`, and `/implement` read from and write to these files.

## Where things live

- **Feature specs / PRDs** — `.ai/features/YYYY-MM-DD-<feature-slug>.md` (single file), or a
  directory `.ai/features/YYYY-MM-DD-<feature-slug>/` when a feature needs multiple files
  (PRD + a per-issue breakdown). Both forms already exist in `.ai/features/`.
- **Implementation issues** (produced by `/to-issues`) — inside the feature directory:
  `.ai/features/YYYY-MM-DD-<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`.
- **Durable backlog** — `.ai/BACKLOG.md`. Captured-but-unscoped items live here; `.ai/STATUS.md`
  "Next Steps" is the prioritized slice.
- **Data Hub API requests** — `.ai/api-requests/YYYY-MM-DD-<slug>.md` (existing convention; see
  the "Data Hub API Requests" section in `AGENTS.md`).

Use today's date for the `YYYY-MM-DD` prefix — it matches the existing `.ai/features/` and
`.ai/sessions/` naming.

## Triage state

Record triage state as a `Status:` line near the top of each issue/feature file
(e.g. `Status: ready-for-agent`). Role strings are defined in `triage-labels.md`.

## When a skill says "publish to the issue tracker"

Create a new markdown file under `.ai/features/<feature-slug>/` (creating the directory if
needed). Add a one-line pointer to `.ai/BACKLOG.md` for anything durable that isn't being worked
on immediately.

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the feature slug
directly.

## Not used

No `gh` / `glab` CLI calls — this repo does not track issues on GitHub or GitLab Issues (`gh` is
not installed on this box). External PRs are **not** a triage surface.
