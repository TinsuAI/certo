# Project: barry-CO

## Session Start
Read `.ai/STATUS.md` and last 2-3 session summaries in `.ai/sessions/` before doing anything.

## Overview
Internal webapp for agency staff who prepare, review, and submit certificate of origin (CO) dossiers. The product starts from existing agency archives, process docs, and spreadsheet-driven workflows, then evolves into a structured case workbench.

## Tech Stack
- TypeScript
- Next.js 16 App Router
- React 19
- Local filesystem discovery for bootstrap phase
- Database: none yet
- Deployment target: not fixed yet

## Preflight
Decisions that are expensive to change later. Settle these before building.
If this is an existing project, fill these in from what's already in place.
- Deployment target: undecided; keep the app compatible with standard Node deployment until hosting is chosen
- Database: none for now; local files are the source of truth during discovery
- Auth: none for now
- API style: server components first, add route handlers only when UI workflows require mutations
- High-risk areas: archive ingestion, spreadsheet parsing, customs declaration normalization, CO calculation parity with the existing macro workbook

## Architecture
Key directories and their purposes.
- `src/app/` — Next.js app shell and current discovery dashboard
- `src/lib/` — server-side data inventory helpers over extracted agency files
- `scripts/` — local data preparation utilities such as RAR extraction
- `data/` — local-only agency source material and extracted working files
- `.ai/` — project state, decisions, and feature briefs

## Build & Run
Commands to build, run dev server, run tests, lint.
- `npm run dev`
- `npm run build`
- `npm run lint`
- `npm run extract:rars`

## How We Work
Scale rigor to the change — a quick fix needs less ceremony than a payments integration.

- **Risky changes** (auth, payments, API contracts, migrations): `/discover` first → `/tdd` → `/rev` → commit
- **Standard features**: write tests → implement → `/rev` → commit
- **Quick fixes**: implement → verify → commit
- **Bug investigation**: `/fix` for systematic root-cause analysis → regression test → fix
- **Session end**: `/handoff` to capture state for next session

### Principles
- **Progressive rigor:** Small change = lightweight. Risky change = thorough spec and review.
- **Assumptions mode:** On existing codebases, state assumptions from reading the code rather than asking many questions. User corrects what's wrong.
- **Verify before claiming done:** No "done" without running tests and confirming the change works. Evidence, not claims.

## Skills
- `/tdd` — test-driven development
- `/rev` — two-stage code review
- `/fix` — systematic debugging
- `/discover` — explore before building
- `/handoff` — session summary + STATUS.md update

## Conventions
Project-specific conventions beyond the global rules. Examples:
- Keep agency documents local; do not commit `data/`
- Prefer discovery utilities over hard-coded demo data
- Use the archive folder names and status buckets as the starting domain vocabulary

## Deploy
How and where this app is deployed. Remove this section if not applicable yet.

## Context Files
- `.ai/STATUS.md` — Current progress and next steps
- `.ai/DECISIONS.md` — Architecture decisions and rationale
- `.ai/GLOSSARY.md` — Domain-specific terms
- `.ai/sessions/` — Dated session summaries and primary handoff artifacts
