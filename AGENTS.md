# Project: barry-CO

## Session Start
Read `.ai/STATUS.md` and last 3-5 session summaries in `.ai/sessions/` before doing anything.
After the context refresh, start the development server **with live reload** by default so the workspace is ready for manual checks. The dev command is `npm run co:serve` (uvicorn `--reload`, watches `app/` for `*.py`/`*.html`/`*.css`) → `http://127.0.0.1:8001`. Reuse an already-running server when available; otherwise run it on the default port, or the next available port if the default is busy, and report the URL.

### Context Budget For Getting Up To Date
Getting up to date must be a low-context refresh, not a repository inventory.

- Default read set: `AGENTS.md`, `.ai/STATUS.md`, `.ai/DECISIONS.md`, and the latest 3-5 files in `.ai/sessions/`.
- Use targeted reads only. Read selected session summaries in full; read status/decision files in full unless they become unusually large.
- Do not run broad file inventories over `docs/legal/`, `data/`, generated corpora, extracted archives, or large local artifacts during session start.
- Do not run tests, browser checks, or dependency installs just to get up to date. Save verification for implementation or when the user asks.
- Do not spawn sub-agents for routine session start or "get up to date". Session refresh is not the same as codebase exploration.
- If more context is needed, state the specific question first, then read only the files needed to answer it.

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
- `npm test`
- `uv run pytest`
- `npm run co:serve`

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
- **Screenshot hygiene:** When UI/browser testing creates screenshots, save them under `.ai/screenshots/YYYY-MM-DD-<feature-slug>/`, where the date is when the work happens and `<feature-slug>` names the feature currently being developed. Do not dump screenshots directly into `.ai/screenshots/`, and do not omit the date prefix.

## Data Hub API Requests

CO is a consumer of Data Hub. Do not add, modify, or assume Data Hub API endpoints from this repo.

When CO needs new Data Hub data or behavior:
1. Check the existing `app/data_hub_client.py` adapter and current Data Hub contract first.
2. If the existing contract is insufficient, create a request artifact under `.ai/api-requests/YYYY-MM-DD-<slug>.md` using `.ai/templates/data-hub-api-request.md`.
3. The artifact must include the use case, existing endpoint gap, proposed request/response JSON, auth scope, client scoping rule, pagination, precision, idempotency, error cases, and required Data Hub provider tests.
4. Stop and ask for Data Hub-side contract approval. Do not implement CO behavior against an unapproved endpoint.
5. After Data Hub implements the endpoint and provider tests pass, consume it only through `app/data_hub_client.py`. Do not scatter raw `/v1/hub/*` HTTP calls across the app.
6. Mutating Data Hub behavior requires an explicit service-token scope (for example `hub:propose:bom`). Never rely on permissive bearer auth.

Guardrail: `tests/test_data_hub_policy.py` fails if raw `/v1/hub` endpoint strings appear outside `app/data_hub_client.py`.

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
