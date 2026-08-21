# Issue Tracker

Issues for this repo live in **GitHub Issues** on `TinsuAI/data-hub`, reached with the
`gh` CLI. This is the single ticket store. There is no second one.

```bash
gh issue list --state open
gh issue create --title "..." --body "..." --label ready-for-agent
gh issue view <n>
```

## PRs as a request surface

**No.** Pull requests are the review and merge vehicle, not a place where work is
requested. `/triage` does not read PRs. Open a PR only against an existing issue or a
branch you are already working.

## Relationship to `.ai/BACKLOG.md`

`.ai/BACKLOG.md` was the ticket store until 2026-07-10. Its **open** items were migrated
into GitHub Issues; its **shipped and deferred** entries stay in the file as the historical
record, the same way `.ai/DECISIONS.md` holds decision history.

Do not add new work items to `.ai/BACKLOG.md`. Do not re-open its shipped entries. If a
historical entry needs to come back, open an issue and link to the section.

## Relationship to `.ai/features/<slug>/brief.md`

A brief is the **spec**. Issues are the **tickets** cut from it. A multi-phase brief becomes
one issue per phase, each declaring its blocking edges, so any issue whose blockers are
closed can be picked up.

The brief stays the source of truth for *why* and *what*; the issue carries *do this next*
and its blocking edges.
