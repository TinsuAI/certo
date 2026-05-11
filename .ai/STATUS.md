# Project Status

**Date:** 2026-05-11 — Session focused on backlog A.7 ship, A.5 defer
after design survey, F.1 cleanup, and an unscheduled CO blocker fix
(Bearer-aware substitute API mirror).

3 new commits on `main` this session, all pushed to `origin/main`.

## Current State

**Branch:** `main`, sync with `origin/main`, working tree clean
(after this handoff commit).
**Tests:** 1052 passed, 15 skipped, 1 pre-existing fail
(`test_technical_raw_upload_confirm_materializes_edges` — verified
pre-existing via git stash this session; not from these changes).
**Migrations:** at mig 062 (unchanged this session).
**Dev server:** running `:8754` bg task `bo3q2ts3n`.
**Memory updated this session:** `project_reingest_pending.md` reframed
(Johnson shipped, Growatt still pending). Memory index entry tightened.
New memory candidate considered (sister-app routing convention) —
skipped as a follow-up, see "Notes" below.

## Recent Changes — this session

**3 commits ahead of session start (`e7578bf`):**
```
ae3373b feat(api): mirror substitute lookup at /v1/hub/* (Bearer-aware for CO)
9c687da feat(bom): A.7 — extract Object description from SAP-indented BOM
0989237 docs(handoff): Johnson onboarding ship + F.1 backlog cleanup
```

**Substantive changes:**
- `app/parsers/bom_adapters/sap_indented_walk.py` —
  `_DESCRIPTION_ALIASES` constant (EN + VI + ZH); leaf row payload
  now carries description.
- `app/parsers/bom_edges.py` — raw SAP-indented parser stores
  description into `bom_edges.payload->>'description'` (jsonb, no
  schema mig).
- `app/stores/catalog_candidates.py` —
  `_backfill_sample_from_bom` fallback after BCCT backfill;
  BOM-only candidates pick most-recent alive artifact's description.
- `app/routes/api.py` — new
  `GET /v1/hub/clients/{c}/materials/{m}/substitutes` endpoint,
  Bearer-aware via existing `_require_token`. Cookie route at
  `/api/v1/...` preserved.
- `.ai/sister-app-notes/2026-05-13-substitute-api-bearer-available.md`
  — sister-app note.
- `.ai/sister-app-notes/2026-05-13-co-substitutes-bearer-consumer-shipped.md`
  — back-note from CO confirming migration complete; verified
  end-to-end against Johnson MFW0502-39.
- `docs/API_CONTRACT.md` — Substitutes section added under `/v1/hub/*`.
- 5 + 7 = 12 new tests.

**Tests added:**
- `tests/test_bom_raw_edges.py` — 3 tests (description extraction,
  no-column doesn't break, leaf adapter propagation).
- `tests/test_catalog_candidates_refresh.py` — 2 tests (BOM
  description backfills `sample_text`, BCCT precedence preserved).
- `tests/test_substitute_api_v1.py` — 7 tests (no-auth/empty bearer,
  service token happy path, scope, whitelist, min_score).

## Next Steps

In priority order (sequence from earlier this session was A.7 → A.6
→ A.5 → A.1, with A.5 deferred and A.6 reordered after A.5):

1. **Decide A.5 design** (deferred this session) — pick option B
   (stored column + trigger), C (separate derived table), or D
   (runtime Python supplement). See A.5 entry in BACKLOG for the
   design-survey notes. Conflicts with `feedback_no_derived_in_source`
   memory — that's the crux. Until A.5 decided, A.6 stays deferred
   (would be wasted Python rewrite that A.5 obsoletes).
2. **A.1** — `roles[]` + manual fields. 2-3d cross-cut refactor.
   Independent of A.5.
3. **Johnson BOM re-ingest backfill** — A.7's parser fix only
   affects newly-ingested edges. Existing 27,848 Johnson edges have
   `payload->>'description' = null`. Re-ingest all 106 Johnson SAP
   XLSX to populate (CLI run, not browser). Then `refresh_candidates`
   for johnson-vn will populate `sample_text` for 3711+ BOM-only
   candidates.
4. **CO Bearer cutover audit** — CO has migrated for substitutes
   (back-note confirmed). Check if other CO consumers still hit
   cookie-only `/api/v1/...` routes; mirror them under `/v1/hub/*`
   on demand. BACKLOG C.1 partially unblocked.
5. **F.1 Growatt re-ingest** — mirror Johnson's 4-script chain.
   ~0.5-1d.

## Notes for Next AI Session

- **Dev server:** Background task `bo3q2ts3n` runs uvicorn on `:8754`.
  May still be alive at session-resume; check before re-starting.
- **`/tmp/backlog_with_both.md`:** scratch file from the F.1 split
  commit earlier — already removed at end of A.7 work.
- **Browser test for A.7** was prepped but not executed by AI:
  Johnson `MFW0502-39.XLSX` copied to
  `C:\Users\vuong\Downloads\MFW0502-39.XLSX` for user to upload
  manually. Verify after re-ingest.
- **Sister-app routing convention** (learned this session, worth
  capturing as memory next time if it recurs): cookie-only routes
  under `/api/v1/*` are UI surfaces; sister-app server-to-server
  callers must use `/v1/hub/*` (Bearer auth via `_require_token`).
  When a new endpoint serves both UI + sister-app, mirror — don't
  retrofit dual-auth onto the cookie route.
- **A.5 design memo to revisit:** the 3 options (B stored column /
  C separate derived table / D runtime supplement) live in BACKLOG
  A.5 body now. When user re-engages, that section has the comparison.
- **CO back-note pattern:** sister apps drop their own notes into
  `.ai/sister-app-notes/` when they migrate to a new Data Hub contract
  (see `2026-05-13-co-substitutes-bearer-consumer-shipped.md`).
  Treat them as inbound communication — read before assuming a
  sister-app is still on the old API.
