# Project Status

## Current State
- Active branch: `main`. A focused handoff/implementation commit was requested after the substitute-modal search fix.
- CO dev server is running at `http://127.0.0.1:8001`; latest health check returned `200`.
- Local Data Hub is expected at `http://127.0.0.1:8754`. During this session, Data Hub still returned `500` for `GET /v1/hub/materials?client_id=growatt-vn`, while products, BCCT, and source-summary endpoints returned `200`.
- Postgres `barry_co` remains the intended local database via Unix socket (`postgresql:///barry_co?host=/var/run/postgresql`) for stock ledger work.
- Case workflow tabs remain: Lô hàng / Chứng từ / Form&PSR (W.I.P) / Bảng kê C/O / TKX-TKN / Review-Xuất.
- Untracked screenshot directories and `.ai/sister-app-prompts/` are local artifacts and were intentionally not part of the requested commit unless the user explicitly asks to preserve them in git.

## Recent Changes
- Fixed the NVL substitute modal `Tìm kiếm` tab when Data Hub material catalog search fails or returns empty:
  - `substitute-candidates` now falls back to matching materials already present in the current CO dossier.
  - duplicate material codes are de-duped between catalog results and dossier fallback.
  - frontend search empty-state now says no match or shows the backend fallback message, instead of leaving the stale "Nhập từ khóa" prompt after a completed search.
  - lazy `/substitute-stock` now returns empty stock summaries instead of `500` if the stock fallback path hits the broken Data Hub materials endpoint.
- Added regression coverage for fallback search when `portfolio_service.search_materials()` raises.
- Verification:
  - `uv run pytest tests/test_co_demo.py::test_origin_sheet_substitute_candidates_endpoint_returns_search_and_recommended tests/test_co_demo.py::test_origin_sheet_substitute_search_falls_back_to_case_materials_when_catalog_fails` passed.
  - Full `uv run pytest` passed: `211 passed, 1 skipped, 7 warnings in 77.63s`.
  - Browser smoke on auth-disabled `http://127.0.0.1:8002` confirmed searching `012.0002700` rendered one result and `/substitute-stock` returned `200`.
  - `git diff --check -- app/main.py app/templates/co_case.html tests/test_co_demo.py` passed.

## Next Steps
1. Fix Data Hub-side `/v1/hub/materials` and `/v1/hub/materials/{code}` 500s for `growatt-vn`/`johnson-vn`; CO's fallback keeps the modal usable but full cross-catalog search depends on Data Hub.
2. Browser-test cross-case stock ledger end-to-end: lock sheet in case A, confirm case B substitute modal shows reduced `remaining_qty`, reopen and confirm restoration, test concurrent locks and overclaim flag.
3. Verify Data Hub `/v1/hub/clients/{c}/bcct/by-codes` availability before relying on narrow substitute-stock lookup for Johnson-scale clients.
4. Decide whether `/sheet/{code}/lock` should read persisted sheet state instead of trusting form-rebuilt state, because form submits can strip `materials[*].allocation_lines`.
5. Continue backlog item #9: NVL origin classification config / Data Hub evidence source.

## Blockers
- Data Hub material catalog endpoints returning `500` block complete manual search across the full catalog. CO currently falls back only to dossier materials.
- Substitute-stock first open on very large clients can still be slow until the Data Hub `bcct/by-codes` provider endpoint is available and verified.
- `Form&PSR` remains W.I.P.; rule/evidence engine is not implemented beyond current form/criteria guidance.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User is sensitive to slow UX and loading without progress. Page must stay interactive during async; only the clicked control should show a busy spinner, with a global top progress bar as signal.
- User explicitly said production uses Postgres; do not add JSON fallback for new persistence. Ledger may no-op when `BARRY_DATABASE_URL` is unset for tests, but do not write ledger state to JSON.
- Default `uv run pytest` intentionally runs without `BARRY_DATABASE_URL`; one ledger test is skipped in that mode. Running with DB env can expose pre-existing JSON-store assumptions in unrelated tests.
- Data Hub `uom` migration reference: commits `6a1b47a`, `42decc7`, `f64b500` in the Data Hub repo. Hub still emits deprecated `unit` alias for a grace window, but CO should not depend on it for material/product rows.
- For Johnson substitute modal smoke data, use invoice `VNG26050001` or `VNG25120047`. Material `018.0645001` returns no Data Hub substitutes because it is not in Johnson catalog; CO heuristic fallback should kick in.
