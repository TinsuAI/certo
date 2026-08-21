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
| CO suite, live store | 1183 passed / 19 skipped, **8m13s, 2.0 GB peak** | same set, at parity |
| CO suite, one store-heavy file | 186 passed / 7 skipped, 32.77s, 429 MB | **186 passed / 7 skipped, 28.68s, 432 MB** |
| Data Hub suite (fresh DB) | 4 failed / 1685 passed / 18 skipped | **4 failed / 1684 passed / 19 skipped** |
| Both suites, one bare `pytest` | n/a — impossible | **4 failed / 2866 passed / 39 skipped, 10m44s, 2.2 GB peak** |
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

## A near-miss on live data, and the two things that actually protected it

While diagnosing the Starlette 400, a reproduction script called `save_co_form_config()`
directly, which wrote a test market preset ("Bharat") into
`data/local/runtime/co-form-index.json`.

**It did not reach live data.** `data/` in `barry-CO-main` is a symlink to the live app data
directory, but the symlink is gitignored, so `git clone` never created it here — the write
landed in a 3.7 MB stub directory this repo created for itself. Confirmed afterwards: the live
`co-form-index.json` still carries its original mtime of **2026-05-03**, and nothing under the
live runtime store was modified on 2026-08-21. The stub was removed and `data` is now the same
symlink the old repo uses.

Two real defects came out of it:

1. **The committed ignore pattern never covered the symlink.** `.gitignore` had `/data/` — a
   trailing slash matches only directories, never a symlink named `data`. That is why
   `barry-CO-main` needed a local `.git/info/exclude` entry, which does not clone. Fixed here by
   committing `/data` without the slash, so the next clone cannot repeat this.
2. **A diagnostic script that touches a store must point that store's root env var at a temp
   path first** (`CO_FORM_CONFIG_PATH` in this case). Getting away with it because a symlink
   happened to be missing is luck, not a safeguard.

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

## Addendum 2 — the fourth collision, which reached live data

`hub/app/storage/__init__.py` and `hub/app/data_promotion.py` resolved their file root as
`Path(os.environ.get("DATA_HUB_FILES_ROOT", "data/files"))` — **relative to the working
directory**. In the `data-hub` repo that meant `data-hub/data/files`. From this repo's root it
resolves through the gitignored `data -> ../barry-CO-bom-data` symlink, so a full test run
created a `files/` tree inside CO's **live app data directory** and wrote 16 Data Hub upload
artifacts into it (`test-bulk-zip-vn`, `raw_bom_test_client`).

Nothing existing was overwritten — the `files/` tree had never existed in the live store, and CO
code never reads it. It was backed up and removed; the live store is back to
`derived/ extracted/ local/ seed/ source/`, with its most recent write predating this work.

Both call sites now derive the default from `__file__`. Re-verified with a full combined run:
**0 files written anywhere under the live store.**

Why the earlier sweep missed it: the search covered path literals inside `Path(...)` and only
under `hub/tests` and `hub/scripts`. This one is a default argument inside `os.environ.get()`,
in `hub/app`. Both shapes have now been swept across all of `hub/`; no others remain.

The generalisable lesson for phases 1–6: **every CWD-relative path in the Data Hub half is a
live-data hazard in this repo**, because the merged root has CO's `data` symlink in it. The four
collisions found so far — `app`, `scripts`/`tests`, `Path("…")` literals, and env-var defaults —
were each silent rather than an error.

## Timing, and what it says about the architecture

| Suite | Time | Peak RSS |
|---|---|---|
| CO alone, `barry-CO-main`, live store | 8m13s | 2.0 GB |
| CO + Data Hub, this repo, live store | 10m44s | 2.2 GB |

The merge costs about 2.5 minutes, which is the Data Hub suite's own runtime. There is no
regression: CO's portion is unchanged.

The 8-minute, 2 GB figure is worth keeping for a different reason. It is the same defect as the
app's latency, measured through the test suite — parsing 93 MB JSON store files and recomputing
derived state on every read. Cause #2 in the assessment, the one phase 4 targets. When phase 4
lands, this number should move.
