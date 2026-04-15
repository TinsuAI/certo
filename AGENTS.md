# Project: barry-CO

## Session Start
Read `.ai/STATUS.md` and last 2-3 session summaries in `.ai/sessions/` before doing anything.

## Overview
Future webapp for agency staff who prepare and submit certificate of origin (CO) dossiers. The current repo is still in discovery: the immediate goal is to understand the supplied archives, workflow documents, and spreadsheet-driven process before choosing app architecture.

## Tech Stack
- Current tooling: Node.js script for archive extraction
- Application stack: not chosen yet
- Database: not chosen yet
- Deployment target: not chosen yet
- Auth: not chosen yet

## Preflight
Decisions that are expensive to change later. Settle these before building.
If this is an existing project, fill these in from what's already in place.
- Deployment target: undecided
- Database: undecided; first confirm whether the app owns structured data or mainly orchestrates documents
- Auth: undecided
- API style: undecided
- High-risk areas: archive ingestion, spreadsheet parsing, customs declaration normalization, CO calculation parity with the existing macro workbook

## Architecture
Key directories and their purposes.
- `docs/` — shared project docs for business logic, workflow, and analysis
- `scripts/` — local data preparation utilities such as RAR extraction
- `data/` — local-only agency source material and extracted working files
- `.ai/` — project state, decisions, and discovery reports

## Build & Run
Commands to build, run dev server, run tests, lint.
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
- Prefer discovery reports over premature application scaffolding
- Use the archive folder names and status buckets as the starting domain vocabulary, but do not assume they are the final domain model
- Put project-facing business and analysis docs in `docs/`, not only in `.ai/`

## Deploy
How and where this app is deployed. Remove this section if not applicable yet.

## Context Files
- `.ai/STATUS.md` — Current progress and next steps
- `.ai/DECISIONS.md` — Architecture decisions and rationale
- `.ai/GLOSSARY.md` — Domain-specific terms
- `.ai/sessions/` — Dated session summaries and primary handoff artifacts
