# Project Status

## Current State

**2026-08-21 — this repo is the CO + Data Hub consolidation. Phase 0 is done: one repo, one
database, one venv. Phase 1 has not started.**

This is a **new repo**, created by merging `barry-CO-main` and `data-hub`. It is not a clone of
either. Read these two before anything else:

- `.ai/reference/2026-08-21-consolidation-assessment.md` — why the merge, what it fixes, what it
  does not fix, the seven phases, and the five decisions the user settled
- `.ai/reference/2026-08-21-phase0-merge-notes.md` — what phase 0 actually did, the three
  name collisions it resolved, the dependency pin, and the local dev setup

| | Result |
|---|---|
| `pytest` (both suites, one run) | **2866 passed, 39 skipped, 4 failed** |
| `npm test` | **57 passed, 0 failed** |
| Database | `co_merged` — schemas `co` (38 tables / 731,733 rows) + `hub` (52 / 1,630,164) |
| Git history | 1041 commits; both repos' histories preserved |
| GitHub remote | **none yet — the repo has not been named** |

The 4 failures are **pre-existing, not caused by the merge**: all four are in
`hub/tests/test_bcct_paging.py` and assert page counts that need a populated BCCT table, so they
fail against any empty database. The unmerged `data-hub` repo produces the identical 4 failures
when pointed at a fresh database. They will also fail in CI until either the tests seed their own
rows or CI restores a corpus.

## Layout

`app/` is CO unchanged. `hub/` is Data Hub with its internal layout untouched, importable as
`hub.app.*`. Data Hub's own tests live at `hub/tests/`, its migrations at `hub/db/migrations/`.

## Running it

```
.venv/bin/python -m uvicorn hub.app.main:app --port 8754   # Data Hub half
.venv/bin/python -m uvicorn app.main:app     --port 8001   # CO half
```

Both read `.env`, both point at `co_merged`. CO still calls the Data Hub half over **HTTP** —
that is phase 1's job to remove, and until it does the request path is unchanged from the
two-repo setup.

`hub/tests/conftest.py` defaults `DATA_HUB_DATABASE_URL` to `co_test` so a bare `pytest` cannot
write into a live database. Do not remove that guard.

## Next Steps

**Phase 1 — Data Hub stores, parsers, flatten, uploads and proposals in-process.** Keep
`app/data_hub_client.py`'s function surface and swap its body from HTTP pagination to direct
`hub.app.stores` calls, so both suites stay green while the adapter is deleted incrementally.
Mount Data Hub's web UI into the merged FastAPI app; expect route-prefix, static-path and
template-name collisions. The phase table is in the assessment doc.

Before phase 1 starts, two things need a decision:

1. **Name the GitHub repo.** `TinsuAI/co` is the old repo's remote. This repo has no `origin`
   and has never been pushed.
2. **CO's duplicate `source_*` / `bcct_rows` tables** were left in place. Deleting
   `PortfolioService` in phase 2 orphans them; raise it then.

## Known issues carried in

- **`POST /settings/co-forms` posts 48,363 form fields.** Starlette ≥1.1 caps urlencoded form
  fields, so this blocks any FastAPI/Starlette upgrade. `fastapi`, `starlette` and `pytest` are
  pinned to the versions both repos ran before the merge. Unpinning is separate work.
- **`hub/AGENTS.md`, `hub/README.md`, `hub/CHANGELOG.md`, `hub/.github/`, both `Dockerfile`s and
  both `docker-compose.yml`s** still describe two independent services. Correct at phase 6.
- The old `barry-CO-main` and `data-hub` repos and their `barry_co` / `data_hub` databases are
  **untouched and still live**. Nothing here has been deployed.
