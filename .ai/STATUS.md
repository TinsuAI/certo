# Project Status

**Date:** 2026-07-19 — **everything through #55 is shipped, pushed, and live.**
`main == origin/main == prod` at `ebd7bdc`. Prod migration table reads **095**
with no files missing. Merged-tree suite, serial: **1686 passed, 16 skipped,
0 failed**. There is no unpushed work and no pending migration.

The three warnings the 2026-07-17 STATUS carried — 19 unpushed commits, migs
094/095 pending on prod, prod data ahead of its migration table — were all
resolved by the 2026-07-18 deploy. That session left no log; one was written
retroactively on 2026-07-19:
`.ai/sessions/2026-07-18-catalog-selection-modal.md`.

## Current State

- **Prod `v0.21.0` / `git_sha=ebd7bdc`**, built `2026-07-18T05:48:05Z`,
  `/healthz` 200. Same commit as local `main`. Verified 2026-07-19.
- **Prod schema is current.** `hub.schema_migrations` max
  `095_growatt_double_dot_placeholder.sql`, 93 rows; filename diff against
  `db/migrations/*.sql` is empty. (Local records 94 rows — one stale entry for
  a migration file that no longer exists. Harmless, not chased.)
- **Prod auth is strict:** `hub.app_settings.api_auth_strict = true`, container
  env `DATA_HUB_API_AUTH_DISABLED=0`. **But see #26** — that setting is a
  hand-set row, not seeded by any migration, and `_strict_mode()` defaults
  false when it is absent.
- **#55 SHIPPED.** Candidate page has per-row checkboxes, a select-all-on-page
  header box, a Gmail-style "select all N matching" banner, and a native
  `<dialog>` for single-row accept. The server accepts a client code list only
  as `selected ∩ filtered-pending` — a code that was never pending cannot be
  forced in through the POST. ADR-0001 amended. Proof:
  `.ai/features/2026-07-18-catalog-selection-modal/` (`brief.md`, `ui_smoke.py`
  for states, `e2e_smoke.py` for real writes on a throwaway client).
- **#52 / #53 / #54 SHIPPED and now closed.** They stayed open for a day after
  the deploy because their commits said `Refs #NN`, not `Closes`. Closed by
  hand 2026-07-19 with the shipping evidence in the comment.
- **Catalog queue on both instances: 3,443 materials, 318 pending** (111 shown
  + 207 machinery). Growatt BOM codes with no catalog row: 2,109 → **74** of
  2,236. Undo handle for #53: audit event `ops:backfill-nb-two-source-53`,
  `details->'codes'`. Undo = bulk `tombstoned`, never DELETE.
- **The standing derive rule is DEFERRED, not rejected.** Inflow is **zero**:
  all 39,203 growatt `bcct_rows` were indexed on one day (2026-05-27,
  `distinct_days=1`), last BOM artifact 2026-05-29, last BQD 2026-05-05, newest
  declaration 2026-05-20, Tier P not stood up. **Revisit on an event, not a
  date** — the next real ingest, or a second dual-code client. Needs an
  ADR-0001 amendment if adopted. Evidence in
  `2026-07-17-nb-backfill-and-catalog-filter-defects.md` §1; do not re-derive it.
- **Dev login is `admin@data-hub.local / admin123`.** Nothing in `app/` imports
  dotenv, so `.env` never reaches `app/main.py:112`'s default.

## Recent Changes (since the last STATUS)

- `app/routes/catalog_discovery.py` — `bulk_accept` takes `codes[]` or
  `select_all_matching` and intersects with the recomputed filtered-pending set.
- `app/templates/clients/catalog_candidates.html` — checkbox column, approve
  bar + select-all banner, `<dialog>`, row button carrying `data-*`.
- `app/static/js/catalog-candidates.js` — new: selection, banner, dialog fill.
- `app/static/css/app.css` — checkbox column, dialog, `.form-stack`.
- `docs/adr/0001-catalog-discovery-is-a-view-not-a-table.md` — amendment
  recording the client-selection contract.
- `tests/test_catalog_candidate_selection.py` — new, 6 tests; the 3 existing
  bulk-accept tests updated for the explicit-selection contract.
- `docs/release-engineering.md` (2026-07-19) — Tier D auth row corrected from
  `DATA_HUB_API_AUTH_DISABLED=1` to the live values, plus a note that
  `api_auth_strict` is hand-set and a restore drops it (#26).
- `.ai/sessions/2026-07-18-catalog-selection-modal.md` — retroactive log.

## Next Steps

1. **#26 / S1 — `/v1/hub` fails OPEN on a fresh or restored DB. Still the #1
   real risk.** Prod is strict only because someone set the
   `hub.app_settings.api_auth_strict` row by hand. No migration seeds it,
   `_strict_mode()` in `app/routes/api.py:53` defaults **false**, and the
   permissive fallback branch is still in `_require_token`. A restore, a new
   tier, or a rebuilt DB serves the API open. Now documented in
   `docs/release-engineering.md`, which does not fix it.
2. **Decide the release cut.** Seven `[Unreleased]` entries (#47, #49, #50,
   #52, #53, #54, #55); version still `0.21.0`. Nothing forces a particular
   number — this is a judgement call about where the line goes.
3. **Unfiled findings from the audit session**, ranked after #26: **C3**
   (`/v1/hub/products` 50-row truncation) → **#46** by-codes index (must run
   `CONCURRENTLY`, out-of-band — **NOT** a boot migration) → **S2** (no rate
   limit on `/login` + `/v1/auth/token`) → **S3** (parser-rule stored SQLi) →
   **C8** (preset-create 500).
4. **#51** — Danh Mục upload with a status column raises CheckViolation.
   `STATUS_MAP` emits `pending`/`discontinued`, illegal since mig 042. Blocked
   on deciding which legal status each label maps to.
5. **UI items scoped out of #54 and #55, unfiled:** the "Đề xuất" column carries
   four unrelated meanings in one cell; "Duyệt" names two different operations
   side by side; the *detail* page still has the `<details>`-in-a-cell accept
   form that #55 replaced on the candidates page.
6. **The shared dev DB drifts from prod inside real clients.** Three known:
   `PV01.0105200` (a #49 UI test's material), `TEST_TP_DRIFT` (a fixture code
   in `growatt-vn`), and the admin password. The conftest sweep only reclaims
   suffixed **clients**, not artifacts inside real ones. Local numbers ≠ prod
   numbers — verify against prod before quoting figures.
7. **Comprehension thread** — 4 of ~5 load-bearing seams remain for guided
   walkthroughs: `/v1/hub` auth gate, migrate-at-boot pipeline, staleness
   triggers, ingest/hash path.

## Notes for Next AI Session

- **Read this + `2026-07-18-catalog-selection-modal.md` +
  `2026-07-17-nb-backfill-and-catalog-filter-defects.md`.**
- **Run the suite serially** (`-p no:randomly`, one session at a time). It hits
  the **shared** dev DB, so concurrent runs invent phantom failures, and a
  migration on one branch reds every other branch including `main` —
  deterministic, survives a re-run, looks exactly like real breakage. A
  worktree isolates files, **not** the DB. Baseline **1686 passed, 16 skipped**.
- **Reference the issue with `Closes #NN` when the commit finishes the issue.**
  `Refs #NN` does not close it, and three issues sat open for a day after
  shipping because of that. `Refs` is correct only for partial work.
- **Dev login `admin@data-hub.local / admin123`.** `.env` is not auto-loaded.
  ~20 committed scripts hardcode `admin123`; they 401 against any DB seeded
  from a shell that *does* export `DATA_HUB_SEED_PASSWORD` (CO's server does
  exactly that: `set -a; . ./.env; set +a`).
- **HTML-level assertions are not browser-level assertions.** Jinja escapes `&`
  to `&amp;` in hrefs (correct HTML); `TestClient.get(href)` then parses
  `?q=X&amp;kind=nb` as a param named `amp;kind`, silently dropping everything
  after the first — a test can pass by coincidence. `html.unescape` the href.
- **The audit's "verified CLEAN" list still stands** — don't re-audit migration
  chains, JWT/SSO, the SQLi surface, `customs_relevance` parity.
- **Advisor agent must run on model `fable`** (memory `feedback_advisor_runs_fable`).
- **Prod:** `/mnt/c/Windows/System32/OpenSSH/ssh.exe tinsu@100.84.189.87` (WSL
  ssh is broken; the host does **not** resolve by name), then
  `docker exec data-hub-db-1 psql -U hub -d data_hub`. Prod runs Docker, not
  systemd. The migrations table is `hub.schema_migrations` and its column is
  `filename`, not `version`. Docs-only commits use `[skip ci]`.
- **User is time-constrained** — delegates, but wants the mechanism briefed, no
  black box. Does NOT want to code by hand. He corrects framing errors directly.
- Dev server on :8754 was left running (`nohup setsid uv run uvicorn …
  --workers 4`). No `--reload` — restart it before any manual UI check.
