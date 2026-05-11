# Project Status

**Date:** 2026-05-11 — Shipped `GET /v1/hub/clients/{c}/bcct/by-codes`
per CO API request 2026-05-13. Provider tests + contract docs landed.
CO consumer not yet shipped; awaiting their PR.

1 commit pending (not yet pushed). Test suite green: 1072 passed, 15 skipped.

## Current State

**Branch:** `main`. Working tree has the BCCT by-codes commit ready.
**Tests:** 1072 passed, 15 skipped (was 1052/15 before this session — net
+20: 19 new in `test_bcct_by_codes_api.py` + 1 previously-flaky
`test_technical_raw_upload_confirm_materializes_edges` now passing in
full-suite runs; intermittent on this box).
**Migrations:** at mig 062 (unchanged — no schema work this session).
**Dev server:** running on `:8754` with 4 workers (no `--reload`), bg
task `bwbuquhaf`. Restart required after code edits.
**Memory updates:** none this session.

**New endpoint live state:**
- `GET /v1/hub/clients/{client_id}/bcct/by-codes?codes=A,B,C` —
  Bearer-aware (`hub:read` scope), filters BCCT by `customs_code` IN
  (codes) case-insensitive, max 100 codes/request, row shape mirrors
  `/v1/hub/bcct`.
- Smoke against Johnson: `005365-00,005048-AB` returned 5 rows in
  ~30ms (vs ~30s to paginate full 65k for the same answer).

## Recent Changes — this session

Single pending commit (not yet pushed):

```
feat(api): bcct/by-codes endpoint for CO substitute-stock derivation
```

**Files:**
- `app/routes/api.py` — `api_list_bcct_by_codes` + `_parse_codes_param`
  helper. Validation order: token → can_view_client → candidate_limit →
  codes shape → client exists → page args.
- `tests/test_bcct_by_codes_api.py` (new) — 19 provider tests.
- `docs/API_CONTRACT.md` — endpoint entry under BCCT section.
- `docs/API_CHANGELOG.md` — additive entry dated 2026-05-13.
- `.ai/BACKLOG.md` — C.1.a opened (soak test pending) +
  "Shipped — kept for context" entry added.

## Next Steps

1. **Push the commit** to `origin/main` when ready (not auto-pushed).
2. **Wait for CO consumer PR** — they'll consume the new endpoint in
   `co_case_origin_sheet_substitute_stock` and remove the `/origin`
   warm-up cache path. Ping-back expected in
   `.ai/sister-app-notes/2026-05-XX-co-bcct-by-codes-consumer-shipped.md`.
3. **Soak test once CO is live** — see backlog C.1.a:
   - Real-load latency under concurrent CO requests.
   - Pagination with codes that have long import history.
   - `include_material_identity=true` cost on ~100-row slices.
   - `EXPLAIN ANALYZE` on Johnson to confirm index usage with
     `upper(customs_code) = any(...)`.
4. **Existing carryover items from prior STATUS.md** (unchanged):
   refresh-substitutes pipeline for Johnson newly-accepted NVL; A.1
   roles[] + manual fields (2-3d); A.5 design still deferred; F.1
   Growatt re-ingest (~0.5-1d); audit remaining cookie-only
   `/api/v1/...` routes for CO Bearer compatibility.

## Notes for Next AI Session

- **Endpoint not yet validated under real-load.** Provider tests cover
  the contract; CO consumer not shipped. Treat as "shipped pending
  soak test" — see C.1.a in BACKLOG. If latency or correctness
  issues appear once CO lands, fold the fix into that backlog entry.
- **Validation ordering:** for `/v1/hub/clients/.../bcct/by-codes`,
  codes-shape 400 fires before client-not-found 404. Intentional —
  saves a DB lookup on malformed requests. Mirror this when adding
  similar code-filter endpoints.
- **Test pollution caveat:** my new test fixture inserts a
  `hub.bom_artifacts` row with `product_code='PV01.0117500'` and
  cleans up via `client_id`. One full-suite run earlier failed
  `test_technical_raw_upload_confirm_materializes_edges` with a
  state-leak symptom; a re-run was green. If the failure recurs,
  inspect the resolver cache / `bom_artifacts` interactions before
  blaming the by-codes fixture.
- **Live verify pattern for new endpoints (unchanged from prior
  session):** mint service token via
  `app.jwt_issuer.make_service_token` + curl with `Authorization:
  Bearer ...`. For dev with `api_auth_strict=false` (default), any
  non-empty bearer string is accepted.
- **CO contract dates run forward of calendar date.** Today is
  2026-05-11 per `date(1)` but CO API artifacts (and now our
  changelog entry) use 2026-05-13. Match the contract date in
  API_CHANGELOG / API_CONTRACT; use real today's date for session
  log filenames.
