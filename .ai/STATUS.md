# Project Status

## Current State
- Active branch: `main`.
- CO dev server is running at `http://127.0.0.1:8001`; latest health check returned `200`.
- Local Data Hub is running at `http://127.0.0.1:8754`.
- CO dev is now using Postgres, not local JSON, for workflow/case state and stock ledger:
  - local ignored `.env`: `BARRY_DATABASE_URL=postgresql:///barry_co?host=/var/run/postgresql`, `BARRY_DATABASE_SCHEMA=co`
  - imported state: `clients=3`, `co_cases=11`, `co_stock_rows=19370`, `co_stock_claims=3`
  - source indexes were rebuilt for `growatt`, `johnson`, and `do-thanh`
- Full Python suite passes: `uv run pytest` -> `216 passed, 1 skipped, 7 warnings`.
- `npm test` still has pre-existing legal lookup failures around missing `raw-binary` source links; this is outside the CO bảng kê flow.
- Untracked screenshot directories and `.ai/sister-app-prompts/` are local artifacts and should stay out of commits unless explicitly requested.

## Recent Changes
- Hardened Bảng kê C/O workbook persistence:
  - compact JSON payload now carries workbook order, BOM artifact choices, all products, and all sheet states
  - sheet save merges workbook snapshot before persisting current-sheet NVL edits
  - current sheet edits are stored as sparse `material_overrides`, recomputed server-side, and later sheets are marked stale
- Added client-side sheet history and dirty-state workflow:
  - `Lùi` / `Tiến` history for current sheet edits
  - batched `Lưu bảng kê` for replace/add/delete/norm edits
  - guard for double-click/in-flight saves
- Fixed replacement/recompute behavior:
  - replacing NVL recomputes child stock rows for the new code
  - norm edit/add/delete rebuild affected allocation child rows client-side
  - saved replacement no longer reloads old NVL details after refresh
- Fixed Load BOM and save UX:
  - Load BOM shows persistent sheet-level loading until shell replacement completes
  - POST actions no longer replace browser URL with `/origin/sheet/.../calculate`
  - save now redirects back to canonical `/origin`, preventing `GET /calculate` -> `405 Method Not Allowed`
- Fixed allocation row toggle after AJAX shell replacement:
  - `data-allocation-toggle` binding now reinitializes via `refreshCaseShellInteractions()`
- Switched local CO dev to DB-backed state:
  - added ignored `.env` for local DB
  - updated `npm run co:serve` to load `.env` if present
  - ran migrations/imports/rebuilds against `barry_co`
- Added regression coverage for compact origin payloads, workbook state persistence, sheet save recompute, allocation toggle initialization, local material search, and save URL guards.

## Next Steps
1. Browser-test cross-case stock ledger end-to-end with DB enabled: lock sheet in case A, confirm case B sees reduced `remaining_qty`, reopen and confirm restoration.
2. Verify the Data Hub `bcct/by-codes` provider endpoint before relying on narrow substitute-stock lookup for Johnson-scale clients.
3. Fix remaining Data Hub material catalog 500s if still present for `growatt-vn`/`johnson-vn`; CO has fallbacks, but full catalog search depends on Data Hub.
4. Review and remove now-unused client-side replacement allocation helper code if it remains unused after the live allocator changes.
5. Resolve unrelated `npm test` legal lookup failures around `raw-binary` links before treating Node tests as a release gate.
6. Continue backlog item: NVL origin classification config / Data Hub evidence source.

## Blockers
- Data Hub provider contract for `bcct/by-codes` still needs verification before Johnson-scale performance can be considered final.
- `Form&PSR` remains W.I.P.; rule/evidence engine is not implemented beyond current form/criteria guidance.
- Node legal tests are failing independently of CO workflow changes.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User is sensitive to slow UX and loading without progress. Keep async actions visibly loading and avoid page-level blocking unless necessary.
- User expects CO dev to use Postgres. Do not add new JSON persistence for workbook/ledger state.
- `npm run co:serve` now loads `.env` manually because `uv run` does not load `.env` by default.
- Default `uv run pytest` still runs without `.env`; DB-specific checks should use `uv run --env-file .env ...`.
- Current running CO server is a background `npm run co:serve` process writing logs to `/tmp/barry-co-8001.log`.
