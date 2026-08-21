# Phase 0 — repo consolidation, what was done and what it proves

Date: 2026-08-21. Plan and decisions: `.ai/reference/2026-08-21-consolidation-assessment.md`
and the 2026-08-21 entry in `.ai/DECISIONS.md` (both carried over from `barry-CO-main`).

Phase 0 scope was deliberately narrow: **one repo, one database, both suites at pre-merge
parity, both halves booting on real data.** "Parity", not "green" — the Data Hub suite
carries 4 pre-existing failures that the merge neither caused nor fixed (see below). No adapter rewiring, no auth work, no UI work. CO still calls the Data
Hub half over HTTP exactly as before — that swap is phase 1.

## Result

| Check | Before (two repos) | After (this repo) |
|---|---|---|
| CO suite | 1181 passed / 21 skipped | **1181 passed / 21 skipped / 0 failed** |
| Data Hub suite (fresh DB) | 4 failed / 1685 passed / 18 skipped | **4 failed / 1684 passed / 19 skipped** |
| Both suites, one bare `pytest` | n/a — impossible | **4 failed / 2866 passed / 39 skipped** |
| `npm test` | 57 passed | **57 passed / 0 failed** |
| Databases | `barry_co` + `data_hub` | **`co_merged`** (schemas `co` + `hub`) |
| Venvs | two | **one** |
| Git history | 534 + 506 commits | **1041 commits, both preserved** |

The 4 Data Hub failures are **pre-existing and unrelated to the merge**: all four are in
`hub/tests/test_bcct_paging.py` and assert on page counts that need a populated BCCT table, so
they fail against any empty database. Verified by running the original `data-hub` repo against
a fresh `dh_probe` database — identical 4 failures. They pass only against a dev database that
already holds real rows.

The one remaining skip delta is `test_real_johnson_sample_passes_full_parse`, which needs
`data/source_inventory/` — 4.4 GB of gitignored local agency data. It is symlinked for local
dev (see below) but skips gracefully when absent.

## Repo layout

```
co/
  app/           CO, unchanged, package `app`
  tests/         CO tests, unchanged
  hub/           Data Hub, internal layout untouched, package `hub.app`
    app/ tests/ scripts/ db/ data/ keys/ ...
  db/migrations/ CO migrations (Data Hub's stay at hub/db/migrations)
```

Data Hub's directory layout was **not** flattened on purpose. Its modules derive paths from
`Path(__file__).resolve().parent.parent` (migrations root, seeds, keys, CHANGELOG, pyproject).
Keeping `hub/app/` one level below `hub/` keeps every one of those resolving to `hub/`, so the
move needed zero path edits in application code.

## The rewrites, and the three collisions they fixed

`app`, `scripts`, and `tests` are all top-level names that existed in **both** codebases. Each
was a silent-failure risk, not an ImportError: `app.database` exists on both sides and both
export `connect()`, so a missed rewrite would have bound Data Hub code to CO's connection
settings and — because Data Hub queries are schema-qualified — still appeared to work.

| Collision | Fix | Count | Verified |
|---|---|---|---|
| `app.*` imports | → `hub.app.*` | 1,241 subs / 311 files | `grep -rE '^\s*(from\|import) app\b' hub/` = 0 |
| `scripts.*`, `tests.*` imports | → `hub.scripts.*`, `hub.tests.*` | 14 subs / 9 files | same grep = 0 |
| CWD-relative `Path("tests/…")`, `Path("data/…")`, `Path("app/…")` | anchored to `Path(__file__)…parent.parent` | 12 files | no residual matches; suites confirm |

Six quoted `app.` strings were checked individually and deliberately **left alone** — they are
not module paths: `"app.brand"` (i18n key), `'app.user_id'` (a Postgres `set_config` session
variable), `logging.getLogger("app.…")` names, and `'app.parsers.bom_adapters'` stored as a
`source_table` provenance value in SQL.

`hub/pyproject.toml` kept its metadata (`hub/app/version.py` reads it) but lost its
`[tool.pytest.ini_options]` section, which was hijacking pytest's rootdir whenever a test under
`hub/` was run by path.

## Dependency pinning — read this before upgrading

The merged `pyproject.toml` unions both dependency sets. There were **no conflicting pins**.

But a fresh resolve pulled Starlette 1.0.0 → 1.6.0 and FastAPI 0.136.1 → 0.141.1, and two CO
tests started failing: `POST /settings/co-forms` returned 400 instead of 303. Cause is not the
merge — Starlette ≥1.1 caps the number of fields in a urlencoded form, and that settings form
posts **48,363 fields**. Both original repos ran Starlette 1.0.0 / FastAPI 0.136.1 / pytest
9.0.3, so the merged repo now pins those exact versions. The merge is therefore verified
against unchanged runtime behaviour.

**Two follow-ups this uncovered, neither a phase-0 concern:**
1. The C/O forms settings page posting 48k form fields is a real design problem in CO. It will
   block any FastAPI/Starlette upgrade until the form is restructured.
2. Unpinning is separate work with its own verification pass. Do not fold it into a phase.

## Database

`co_merged` was built by schema dump/restore, not by replaying migrations into empty tables:

```
pg_dump --no-owner --no-privileges -n co   barry_co | psql -d co_merged
pg_dump --no-owner --no-privileges -n hub  data_hub | psql -d co_merged
```

`vector` and `pg_trgm` are created in the target **before** the `hub` restore — `hub` tables use
the `vector` type and the restore fails without it.

Row parity was verified table by table, not in aggregate:

- `co`: 38 tables, **731,733 rows** — exact match
- `hub`: 52 tables, **1,630,164 rows** — exact match
- zero errors in either restore log

Deliberately **excluded**, and not to be "restored" later by mistake:
- `barry_co.public` — 29 tables of stale legacy data that looks plausible
- `data_hub.co` — 32 empty tables left over from an earlier experiment

Migration ledgers came across intact (`hub.schema_migrations` 94 rows, `co.schema_migrations`
23), so both halves' `apply_migrations()` are no-ops on boot.

**`barry_co` and `data_hub` were not modified and are still live.** The old stack keeps running
until cutover (phase 6).

## Local dev

```
createdb co_test    # empty; the Data Hub suite bootstraps it via its conftest
BARRY_DATABASE_URL     → co_merged   (in .env)
DATA_HUB_DATABASE_URL  → co_merged   (in .env)
DATA_HUB_DATABASE_URL  → co_test     (must be set when running hub/tests)
```

Run the halves from the repo root:

```
.venv/bin/python -m uvicorn hub.app.main:app --port 8754
.venv/bin/python -m uvicorn app.main:app     --port 8001
```

Gitignored local assets, symlinked to the old repos rather than copied (8.6 GB):
`hub/data/files`, `hub/data/source_inventory`, `hub/data/screenshots`, plus `hub/keys/` (dev
JWT signing keys copied in, not symlinked).

**When running `hub/tests`, always set `DATA_HUB_DATABASE_URL` to `co_test`.** Data Hub's
`connect()` defaults to `postgresql:///data_hub` and its conftest applies migrations, seeds
demo clients, resets the admin password, and deletes clients matching `-[0-9a-f]{8}$`. Left
unset it writes into the original live database. Verified after every suite run that
`co_merged.hub` still holds exactly 1,630,164 rows.

## Measured baseline through the merged stack

CO on `:8001` talking HTTP to the Data Hub half on `:8754`, both against `co_merged`:

| Route | Time |
|---|---|
| `/clients` | 0.88s |
| `/clients/growatt-vn/co-case` | 2.02s (5.24s cold) |
| `/clients/johnson-vn/co-case` | 0.91s |

These are the numbers phase 1 has to beat. They are unchanged from the two-repo setup by
design — nothing about the request path has moved yet.

## One live-data incident, and the lesson

While diagnosing the Starlette 400, a reproduction script called `save_co_form_config()`
directly and wrote a test market preset ("Bharat") into
`data/local/runtime/co-form-index.json` — a **live shared file**, since `data/` is a symlink to
the live app data directory. It was reverted immediately (`market_presets` 9 → 8, no "Bharat"
remaining), but the correct move was to point `CO_FORM_CONFIG_PATH` at a temp file first.
Diagnostic scripts touching a store must set that store's root env var before running.

## Not done in phase 0 (by design)

- CO still reaches the Data Hub half over HTTP through `app/data_hub_client.py`. Phase 1 swaps
  the body for direct `hub.app.stores` calls.
- Both `Dockerfile`s, both `docker-compose.yml`s and both CI configs are untouched and still
  describe two services. Phase 6.
- `hub/AGENTS.md`, `hub/README.md`, `hub/CHANGELOG.md` and `hub/.github/` are carried as-is.
  They document Data Hub as a standalone service and will be wrong until phases 1–3 land.

## Addendum — two problems only a combined run could show

Running the suites separately hid both of these. They were found by running one bare `pytest`
at the repo root, which is the documented project command.

**1. `sys.modules['tests']` poisoned by colliding basenames.** Two CO tests failed with
`ModuleNotFoundError: No module named 'tests.test_co_demo'`. CO's `tests/` had no `__init__.py`
(namespace package) while `hub/tests/` has one, and four basenames exist in both trees —
`conftest.py`, `test_app_version.py`, `test_changelog_parser.py`, `test_whats_new_page.py`.
Combined collection left `sys.modules['tests']` holding `None`, Python's failed-import sentinel,
so every later `from tests.X import Y` raised. Fixed by adding `tests/__init__.py`, giving the
two trees distinct dotted names (`tests.test_app_version` vs `hub.tests.test_app_version`).
Removing `hub/tests/__init__.py` instead would have produced import-file-mismatch errors on
those same four basenames.

**2. A bare `pytest` wrote into the live `data_hub` database.** `testpaths` now includes
`hub/tests`, and Data Hub's `connect()` defaults to `postgresql:///data_hub` — the live local dev
database. Its conftest applies migrations, seeds demo clients, resets the admin password and
deletes clients matching `-[0-9a-f]{8}$`. Documenting the hazard was not enough. `hub/tests/conftest.py`
now calls `os.environ.setdefault("DATA_HUB_DATABASE_URL", …co_test)` before the first `connect()`.
CI sets the variable explicitly, so it is unaffected. Verified by recording
`select count(*) from hub.clients` on the live database before and after a full bare run: 7 → 7.
