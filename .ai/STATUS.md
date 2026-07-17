# Project Status

**Date:** 2026-07-17 (second session) — **Two features merged to LOCAL `main`,
NOT pushed.** #49 removed `materials.status='under_review'` entirely (mig 094);
#50 added page-selective declarations PDF export for CO dossiers. Merged suite:
**1670 passed, 16 skipped, 0 failed** (serial). Full context:
`.ai/sessions/2026-07-17-under-review-removal-and-pdf-page-selection.md`.
Earlier today's codebase audit: `.ai/sessions/2026-07-17-codebase-audit-and-bom-batch-fix.md`.

> ⚠️ **`main` is 10 commits ahead of `origin/main`** (8 feature/doc + 2 merges).
> Every merge to `main` auto-deploys PROD **and applies pending migrations at
> boot** — pushing runs **migration 094** against production. Decide
> deliberately; see Next Steps 1.

## Current State

- **Prod is healthy on `v0.21.0` / `git_sha=4b958ef`** — last session's deploy
  verified (`/version` matched, `/healthz` 200). Prod does **not** have #49/#50.
- **Local `main` = `9e0332a`**, 10 commits ahead: `04715c2` `66d88cc` `3395e58`
  `fb0c014` (#49) · `a821a47` `31d11cb` (#50) · `2ad2292` `6e02593` (merges) ·
  `88c94d2` (AGENTS.md baseline) · `9e0332a` (this handoff).
- **#49 shipped locally.** Accepting a candidate now lands `active` — it landed
  `under_review` while the bulk button beside it landed `active`, and BCCT
  ingest (unreviewed) landed `active`, so the *unreviewed* path was the more
  trusted one. Mig 094: `active | deprecated | tombstoned | inactive`. Deleted
  `promote_material`, the `?status=under_review` chip, badges, and the
  resolver's `resolved_pending_review`. **Mig 094 is already applied to the
  shared dev DB.**
- **#50 shipped locally, UNUSED.** `POST /v1/hub/clients/{cid}/declarations/download.pdf`
  takes a per-declaration line map; prints framing pages + only cited goods
  pages. Measured 262 pages/978KB → 22 pages/326KB on a 5-declaration dossier.
  **CO has not adopted it** — still calls the GET, still gets all pages.
- **Version still `0.21.0`** — now three `[Unreleased]` entries (#47, #49, #50).
- **Sister-app impact of #49: none.** Zero `under_review` /
  `resolved_pending_review` consumers in CO or BCQT (grepped). CO's
  `data_hub_client.py:1118` holds a now-dead reference that still works.

## Recent Changes

- `db/migrations/094_drop_under_review_material_status.sql` — new.
- `app/routes/catalog_discovery.py`, `app/stores/catalog_discovery.py` — accept
  path hardcodes `'active'`; status form field + `VALID_STATUSES` gone.
- `app/routes/catalog.py` — `promote_material` deleted; `/edit` now 400s on
  `under_review` (would have been a **500 CheckViolation**); `EDITABLE_STATUSES`
  constant; dead `promoted_*` columns no longer selected.
- `app/resolvers/bcct_material_identity.py` — `resolved_pending_review` gone.
- `app/declarations_pdf.py`, `app/routes/declarations.py`, `app/routes/api.py` —
  page selection + POST route + `X-Lines-Missing-Nos`.
- `tests/test_declarations_download_pdf_lines.py` (new, 703 lines),
  `tests/test_materials_status_check.py` (new).
- `docs/API_CONTRACT.md` edited in place; `CHANGELOG.md` + `docs/API_CHANGELOG.md`
  got **new** entries (historical ones left as written — they were true then).
- `.ai/sister-app-notes/2026-07-17-under-review-removed.md` + INDEX row.
- `docs/adr/0001-*.md` — amendment: #49 executes the alternative it rejected.
- `AGENTS.md` — pytest baseline was `219 passed` (off ~7x), now dated
  `~1670 passed, 16 skipped (2026-07-17)`; documents the shared-DB hazard.
- Issues **#49**, **#50** closed by the merges. **#51** filed (see below).

## Next Steps

1. **Decide the push.** `main` +10 → auto-deploy PROD + **mig 094 at boot**.
   Migration flips rows before adding the constraint and was verified clean on a
   fresh DB. Consider `/security-review` first — #50 adds a new `/v1/hub`
   surface. Nothing forces urgency: #50 is inert until CO adopts it.
2. **Decide the release cut.** Three `[Unreleased]` entries now; bigger than the
   `v0.21.1` last session contemplated.
3. **CO adoption of #50** — one callsite,
   `barry-CO-main/app/routers/co_case.py:1500-1512`, stops discarding
   `lines[*].line_no` from `case_tkx_tkn_summary`. **No sister-app note written
   for #50 yet** (only #49 got one).
4. **#2 — candidates bulk-approve UI redesign. DEFERRED; premise changed.** #49
   removed half the incoherence. **Look at the page before redesigning.** Likely
   remaining complaint is the *model*: "the filter IS the rule" — no checkboxes,
   no per-row selection, so you cannot approve 5 and skip the 6th. Needs
   `/grill-with-docs` in a **fresh** context window (user-typed only).
5. **Still open from the audit session** (unchanged, see that log): file the
   unfiled findings **C3** `/v1/hub/products` 50-row truncation, **S2** no
   rate-limit on `/login`+`/v1/auth/token`, **S3** parser-rule stored SQLi,
   **C8** UI preset-create 500. Ranked work: **#26/S1** `/v1/hub` fails OPEN on
   fresh/restored DB → **C3** → **#46** by-codes index (CONCURRENTLY,
   out-of-band — NOT a boot migration) → **S2/S3**.
6. **#51** — Danh Mục upload with a status column raises CheckViolation.
   `STATUS_MAP` emits `pending`/`discontinued`, illegal since **mig 042** — 52
   migrations of latent breakage. Needs a decision on which legal status each
   label maps to.
7. **Comprehension thread** — 4 of ~5 load-bearing seams remain for guided
   walkthroughs: `/v1/hub` auth gate, migrate-at-boot pipeline, staleness
   triggers, ingest/hash path.

## Notes for Next AI Session

- **Read this + both 2026-07-17 session logs.** The audit log holds the ranked
  Tier 1-3 findings; the under_review/PDF log holds the #49/#50 decisions and
  the two mechanisms (`<NN>` marker; why NVL-code matching was rejected).
- **Run pytest serially** (`-p no:randomly`, one session at a time). The suite
  hits the **shared** dev DB, so (a) concurrent runs invent phantom failures and
  (b) **a migration on one branch reds every other branch including `main`** —
  deterministic, survives re-run, looks exactly like real breakage. A worktree
  isolates files, **not** the DB. Only the merged tree is a trustworthy gate.
  Memory: `feedback_test_db_shared_across_branches`.
- **Do not re-derive #50's mechanism.** The ECUS form prints `<01>`, `<02>` per
  goods page; a page with no marker is header/trailer (count **varies** — some
  declarations are `[1,2]`, others `[1,2,3,54]`) and is always kept. Matching
  NVL codes instead was tested and rejected: `IC` matched 24 of 52 pages.
- **The audit's "verified CLEAN" list still stands** — don't re-audit migration
  chains, JWT/SSO, SQLi surface, customs_relevance parity.
- **Advisor agent must run on model `fable`** (memory `feedback_advisor_runs_fable`).
- **User is time-constrained** — delegates, but wants the mechanism briefed, no
  black box. Does NOT want to code by hand. Keep him in the loop on load-bearing
  seams and on anything outward-facing.
- **Prod psql:** `docker exec data-hub-db-1 psql -U hub -d data_hub` (role
  `hub`). Prod runs Docker, not systemd. Docs-only commits use `[skip ci]`.
- Dev server on :8754 was left running; it holds **stale code** (no `--reload`)
  — restart it before any manual UI check.
