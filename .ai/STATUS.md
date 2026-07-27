# Project Status

**Date:** 2026-07-27 — **everything through #58 is shipped, released as
`v0.22.0`, and live.** `main == origin/main == prod` at `9e2b4f7`. Prod schema
unchanged (**095**; this release is UI-only — no migrations). CI Test job green
on the release commit (isolated-DB full suite); not re-run locally this session
— targeted slices were **45 passed** across the touched BCCT/BOM/drift files.
No unpushed work, no pending migration.

`v0.22.0` (2026-07-27) snapshots the `[Unreleased]` backlog **#47–#58** into a
dated CHANGELOG section. It shipped in two moves: PR **#59** merged the #56/#58
code (auto-deployed at v0.21.0 on push-to-main), then `chore(release): 0.22.0`
(`9e2b4f7`) re-baked the image so `/version` and the footer badge read 0.22.0.
`[Unreleased]` is now empty.

## Current State

- **Prod `v0.22.0` / `git_sha=9e2b4f7`**, built `2026-07-27T07:25:59Z`,
  `/healthz` 200. Same commit as local `main` and tag `v0.22.0`. Verified live
  through Cloudflare 2026-07-27.
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
- **#56 / #58 SHIPPED (v0.22.0), closed.** The BCCT upload-preview "Apply
  confirmed changes" button is disabled by the cross-family UoM ack gate with no
  cue — operators ticked the 51-row confirm box and read the grey button as
  broken. #56 adds a locked-state hint above the button (explains the lock,
  jumps to + focuses the ack checkbox, states that `confirm_diffs` does not
  unlock and per-row factors are optional; hidden-by-default, JS-revealed). #58
  (spun off during the fix) makes the shared drift banner mirror the ack's
  restored state on reload instead of hard-locking. Shared banner touched →
  verified on BCCT + BOM. Proof: `.ai/features/2026-07-27-bcct-apply-gate-hint/`.
  **#57 filed, deferred** — `upload_preview_confirm` (`app/routes/bcct.py:975`)
  never reads `ack_uom_drift`, so the cross-family gate is client-JS-only (same
  "gate not enforced server-side" family as #26).
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

- `app/templates/clients/bcct_upload_preview.html` — locked-state Apply-gate
  hint + jump-link script (hidden-by-default, JS-revealed). #56.
- `app/templates/clients/_uom_drift_banner.html` — `DOMContentLoaded` now
  mirrors the ack checkbox's current state instead of hard-locking the confirm
  button. #58.
- `tests/test_uom_ingest_drift.py` — regression test for the hint;
  `_stash_bcct_pending_with_drift` parameterized with `diff=`.
- `.ai/features/2026-07-27-bcct-apply-gate-hint/` — brief, `ui_smoke.py`
  (load → confirm_diffs → ack states + a `[restore]` #58 scenario), screenshots.
- `pyproject.toml` → `0.22.0`; `CHANGELOG.md` — #56/#58 entries, then the whole
  `[Unreleased]` block rolled into `## [0.22.0] — 2026-07-27`.
- Git: PR #59 merged (auto-deployed the code at v0.21.0); `chore(release):
  0.22.0` (`9e2b4f7`) re-baked prod to 0.22.0; tag `v0.22.0` on origin.

## Next Steps

1. **#26 / S1 — `/v1/hub` fails OPEN on a fresh or restored DB. Still the #1
   real risk.** Prod is strict only because someone set the
   `hub.app_settings.api_auth_strict` row by hand. No migration seeds it,
   `_strict_mode()` in `app/routes/api.py:53` defaults **false**, and the
   permissive fallback branch is still in `_require_token`. A restore, a new
   tier, or a rebuilt DB serves the API open. Now documented in
   `docs/release-engineering.md`, which does not fix it.
2. **#57 — cross-family UoM gate is client-side only.** `upload_preview_confirm`
   (`app/routes/bcct.py:975`) never reads `ack_uom_drift`; the gate is enforced
   only by banner JS, so a JS-off or scripted POST bypasses it. Same "gate not
   enforced server-side" family as #26 above. Filed, deferred. (Release cut is
   no longer pending — `v0.22.0` shipped 2026-07-27.)
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

- **Read this + `.ai/features/2026-07-27-bcct-apply-gate-hint/brief.md` +
  `2026-07-18-catalog-selection-modal.md` +
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
