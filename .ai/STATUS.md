# Project Status

**Date:** 2026-07-17 (fourth session) — **#53's backfill is LIVE on prod (data
only); #54's code is merged to LOCAL `main`, NOT pushed, deployed nowhere.** The catalog
approval queue went **2,704 → 111 shown** on both instances. Full context:
`.ai/sessions/2026-07-17-nb-backfill-and-catalog-filter-defects.md`. Merged-tree
suite: **1680 passed, 16 skipped, 0 failed** (serial).

Today's other logs: the codebase audit + BOM `:batch` fix
(`2026-07-17-codebase-audit-and-bom-batch-fix.md`, still **untracked**) and the
`under_review` removal + PDF page selection
(`2026-07-17-under-review-removal-and-pdf-page-selection.md`). The #52 BCCT
derive-gap session (`02377c6`, `2992623`) **left no log**.

> ⚠️ **`main` is 19 commits ahead of `origin/main`**, carrying migs **094 + 095**.
> Pushing auto-deploys PROD and applies them at boot. `fix/nb-two-source-backfill`
> is **merged into local `main`** (`ccb8e33`); merged-tree suite re-run serially:
> **1680 passed, 16 skipped, 0 failed**.
>
> ⚠️ **Prod's data is ahead of its migration table.** `schema_migrations` reads
> **093**, but `customs_code_placeholders` already contains `'..'` — mig 095 was
> hand-applied without being recorded, and #53's 2,594 material rows were
> script-applied. 095 is guarded idempotent (`and not ('..' = any(...))`), so the
> next deploy is safe **by luck, not design**. 094 is also still pending there.

## Current State

- **Prod healthy on `v0.21.0` / `git_sha=4b958ef`**, `/healthz` 200. It has #52's
  and #53's *data* but none of #49/#50/#53/#54's *code*.
- **#53 SHIPPED (local + prod).** 2,593 local / 2,594 prod corroborated NB codes
  accepted, 0 skipped. Both instances now identical: **3,443 materials, 318
  pending (111 shown + 207 machinery)**. Growatt BOM codes with no catalog row:
  2,109 → **74** of 2,236. `johnson-vn` has no NB side — nothing to backfill.
  Undo handle: audit event `ops:backfill-nb-two-source-53`, `details->'codes'`
  (2,593/2,594 entries). Undo = bulk `tombstoned`, never DELETE.
- **#54 MERGED to local `main`, NOT PUSHED.** Filter chips now count in the state their own
  click produces; one owner (`_filter_params` + `_filter_url_builder`) builds
  every chip / clear-link / form target. Proof:
  `.ai/features/2026-07-17-catalog-filter-state/`.
- **The standing derive rule is DEFERRED, not rejected.** Inflow is **zero**: all
  39,203 growatt `bcct_rows` were indexed on one day (2026-05-27,
  `distinct_days=1`), last BOM artifact 2026-05-29, last BQD 2026-05-05, newest
  declaration 2026-05-20, and Tier P is not stood up. **Revisit on an event, not
  a date** — the next real ingest, or a second dual-code client. The residue this
  backfill leaves *is* the rule's residue, so inflow becomes measurable then.
  Needs an ADR-0001 amendment if adopted.
- **Dev login is `admin@data-hub.local / admin123`** — the docs said
  `local_test_password` and were **wrong since 2026-05-05**. Nothing in `app/`
  imports dotenv, so `.env` never reaches `app/main.py:112`'s default. Fixed in
  CLAUDE.md / AGENTS.md / README.md. (CLAUDE.md and AGENTS.md are mirrored — edit
  one, both change.)

## Recent Changes

- `scripts/backfill_nb_two_source.py` — new. Predicate `>=2 of bcct/bom/bqd` +
  not machinery + category derivable. Dry-run default, `--commit` applies.
- `app/routes/catalog_discovery.py` — `_filter_params`, `_filter_url_builder`,
  `_facet_rows`; facet-aware counts; `base_total = len(kind_base)`.
- `app/templates/clients/catalog_candidates.html` — chips/forms rebuild from
  `filter_params`; hidden inputs emitted by loop, not hand-listed.
- `tests/test_catalog_candidates_filter_state.py` — new, 6 tests.
- `.ai/features/2026-07-17-catalog-filter-state/` — `brief.md` + `ui_smoke.py` +
  3 committed screenshots.
- `CHANGELOG.md` — #53 + #54 entries (VN). The #53 entry's three-source
  overclaim was caught in review and corrected.
- `CLAUDE.md` / `AGENTS.md` / `README.md` — dev login + `.env`-not-loaded.
- Issues **#53**, **#54** filed; **#54 amended** with the «Tất cả» decision.

## Next Steps

1. **Decide the push.** `main` +19 → auto-deploys PROD + migs 094/095 at boot.
   This is now the only gate left; everything is merged and green on the merged
   tree. Consider `/security-review` first — #50 added a `/v1/hub` surface.
   Nothing forces urgency; #50 is inert until CO adopts it. Pushing also closes
   #49/#50/#52/#53/#54 via their commit refs.
2. **Resolve the Tier D/P contradiction — needs a human.**
   `docs/release-engineering.md:116` says Tier P is **not stood up** and lists
   `DATA_HUB_API_AUTH_DISABLED=1` for the tier serving `ttdatahub.tinsu.ai`;
   memory `project_prod_auth_enforcement` says never set that in prod and that
   `/v1/hub` is strict there. **One is wrong**, and we wrote to that instance
   today.
3. **Decide the release cut.** Five `[Unreleased]` entries now (#47, #49, #50,
   #53, #54); version still `0.21.0`.
4. **The shared dev DB drifts from prod *inside real clients*.** Three found
   today: `PV01.0105200` (a #49 UI test's material), `TEST_TP_DRIFT` (a fixture
   code in `growatt-vn`), and the admin password. The conftest sweep only catches
   suffixed **clients**, not artifacts inside real ones. Local numbers ≠ prod
   numbers — verify against prod before quoting figures.
5. **#54's scoped-out UI items** (recorded in `brief.md`, unfiled): row «Duyệt»
   is a `<details><summary>` fake button opening a 5-field form in a table cell;
   "Duyệt" names two different operations side by side; "Đề xuất" carries four
   unrelated meanings in one cell.
6. **#51** — Danh Mục upload with a status column raises CheckViolation.
   `STATUS_MAP` emits `pending`/`discontinued`, illegal since mig 042. Needs a
   decision on which legal status each label maps to.
7. **Still open from the audit session:** unfiled findings **C3**
   (`/v1/hub/products` 50-row truncation), **S2** (no rate limit on `/login` +
   `/v1/auth/token`), **S3** (parser-rule stored SQLi), **C8** (preset-create
   500). Ranked work: **#26/S1** `/v1/hub` fails OPEN on fresh/restored DB
   (**still the #1 real risk**) → **C3** → **#46** by-codes index (CONCURRENTLY,
   out-of-band — NOT a boot migration) → **S2/S3**.
8. **Comprehension thread** — 4 of ~5 load-bearing seams remain for guided
   walkthroughs: `/v1/hub` auth gate, migrate-at-boot pipeline, staleness
   triggers, ingest/hash path.

## Notes for Next AI Session

- **Read this + `2026-07-17-nb-backfill-and-catalog-filter-defects.md`.** Do not
  re-derive the inflow analysis — it is zero; evidence in that log's §1.
- **Run the suite serially** (`-p no:randomly`, one session at a time). The suite
  hits the **shared** dev DB, so concurrent runs invent phantom failures, and a
  migration on one branch reds every other branch including `main` —
  deterministic, survives a re-run, looks exactly like real breakage. A worktree
  isolates files, **not** the DB. Baseline **1680 passed, 16 skipped**.
- **Dev login `admin@data-hub.local / admin123`.** `.env` is not auto-loaded.
  ~20 committed scripts hardcode `admin123`; they 401 against any DB seeded from
  a shell that *does* export `DATA_HUB_SEED_PASSWORD` (CO's server does exactly
  that: `set -a; . ./.env; set +a`).
- **HTML-level assertions are not browser-level assertions.** Jinja escapes `&`
  to `&amp;` in hrefs (correct HTML); `TestClient.get(href)` then parses
  `?q=X&amp;kind=nb` as a param named `amp;kind`, silently dropping everything
  after the first — a test can pass by coincidence. `html.unescape` the href.
- **The audit's "verified CLEAN" list still stands** — don't re-audit migration
  chains, JWT/SSO, the SQLi surface, `customs_relevance` parity.
- **Advisor agent must run on model `fable`** (memory `feedback_advisor_runs_fable`).
- **Prod:** `/mnt/c/Windows/System32/OpenSSH/ssh.exe tinsu@100.84.189.87` (WSL ssh
  is broken; the host does **not** resolve by name), then
  `docker exec data-hub-db-1 psql -U hub -d data_hub`. Prod runs Docker, not
  systemd. Docs-only commits use `[skip ci]`.
- **User is time-constrained** — delegates, but wants the mechanism briefed, no
  black box. Does NOT want to code by hand. He corrects framing errors directly:
  this session he caught the data analysis being used to answer a UX question.
- Dev server on :8754 was left running (`nohup setsid uv run uvicorn … --workers 4`).
  No `--reload` — restart it before any manual UI check.
