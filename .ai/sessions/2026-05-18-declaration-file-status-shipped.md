# 2026-05-18 — Declaration file status API + bulk ZIP download (CO request 2026-05-15)

Session continued after the A.2 catalog conflicts page ship
(`d4ea2d7`, session log `2026-05-15-catalog-conflicts-page-ship.md`).
User read the CO API request file
`barry-CO-main/.ai/api-requests/2026-05-15-declaration-file-status.md`
and asked to implement Data Hub side only.

Result: `21f3620 feat(api): declaration file status + bulk ZIP download for CO`.

## What Was Done

1. **Audit existing infra** — found:
   - `hub.customs_declaration_files` table (mig 059) is already source of truth for file presence; `(client_id, declaration_no, direction)` is the natural identity.
   - Existing cookie-only `GET /api/v1/clients/{c}/declarations` already returns the right shape but rejects Bearer callers with `401 login required`.
   - `list_declarations_with_status` / `count_declarations_with_status` store helpers already aggregate `bcct_rows` + file counts. Just needed extension for `declaration_nos` filter.
   - Sister-app routing convention `feedback_api_routing_convention.md`: cookie route stays at `/api/v1/*`; Bearer mirror goes to `/v1/hub/*` (precedent: substitute API 2026-05-13 commit `ae3373b`). Mirror, don't retrofit dual-auth.

2. **Store extensions** in `app/stores/customs_declaration_files.py`:
   - Added `declaration_nos: list[str] | None` param to `list_declarations_with_status` and `count_declarations_with_status`. SQL clause: `and declaration_no = any(%(decls)s)`.
   - New `list_files_for_declarations(client_id, declaration_nos, direction)` — bulk fetch of every DeclarationFile for the requested set. Returns empty list when nothing matches (ZIP caller produces the `NO_FILES_FOUND.txt` marker).

3. **Bearer route** in `app/routes/api.py`:
   - `GET /v1/hub/clients/{client_id}/declarations`.
   - Added `_parse_declaration_nos_param` helper (preserves case, dedupes, caps at 500 → `400 too many declaration_nos`).
   - Validates `direction` → `400 invalid_direction`; `has_files` → `400 invalid_has_files`. Standard `_require_token` + `_require_can_view_client` for 401/403; `get_client` lookup for 404.
   - When `declaration_nos` provided: single-page response (`next_cursor: null`), capped at `_DECLARATIONS_NOS_MAX=500`. Otherwise cursor pagination via existing `_page_args` + `_paged` helpers.

4. **Operator ZIP route** in `app/routes/declarations.py`:
   - `GET /clients/{client_id}/declarations/download.zip`.
   - Cookie auth via `auth.current_user` (not `require_user`) so unauthenticated callers receive `303` to `/login?next=<URL-encoded original>` instead of `401`.
   - Validates `direction` + `declaration_nos` (both required).
   - Archive layout: files at root (no subfolders), duplicate `original_filename` deduped with `_1`/`_2`/… suffix preserving the extension. `DANH_SACH_TO_KHAI.txt` manifest grouped by "Đã có file" / "Thiếu file" sections with per-file in-archive names. When zero files match: archive still ships with manifest + `NO_FILES_FOUND.txt` marker.
   - `_safe_archive_filename` sanitizes the optional `filename` param (strips path separators, control chars; refuses `..` patterns; falls back to `declarations.zip`).
   - `_safe_member_name` strips path separators + control chars so ZIP cannot zip-slip.
   - Backend `FileNotFoundError` during member write is swallowed (file metadata present, blob missing on disk) rather than 500-ing mid-archive.

5. **Tests:**
   - `tests/test_declarations_api_v1_hub.py` (17 tests) — default list, direction/has_files/declaration_nos filters, exact same-no in both directions, pagination cursor round-trip, invalid params (400), missing/garbage Bearer (401 in strict mode), service token without `hub:read` scope (403), client-whitelist enforcement (403), unknown client (404).
   - `tests/test_declarations_download_zip.py` (12 tests) — login bounce (303), missing direction/declaration_nos (400), invalid direction (400), unknown client, root-level files, duplicate-filename dedupe, manifest counts (present + missing sections), `NO_FILES_FOUND.txt` marker when no files match, direction identity (DEC003 import has 0 files but DEC003 export has 1), filename param honored, filename sanitization rejects `..`.
   - Used `monkeypatch.setenv("DATA_HUB_FILES_ROOT", tmp_path)` + reset module-level `_BACKEND` so FileBackend writes land in `tmp_path` and don't bleed across tests.
   - All 29 new tests pass; full suite 1130 passed, 15 skipped (no regression).

6. **Docs:**
   - `docs/API_CONTRACT.md` — new "Declarations" section before "Health".
   - `docs/API_CHANGELOG.md` — entry "2026-05-15 — Additive: `GET /v1/hub/clients/{c}/declarations`" covering both routes (Bearer summary + operator ZIP).
   - `.ai/sister-app-notes/2026-05-15-declaration-file-status-available.md` — full handoff for the CO consumer dev including adapter signature, suggested filename pattern, what NOT to do.

## Decisions Made

- **Bearer + cookie as two routes, not one.** Mirror precedent from substitute API. Keeps each route's auth path single-purpose, avoids the dual-auth retrofit anti-pattern. Cookie-only download is intentional — CO drives it via operator's browser, server-to-server never needs raw bytes.

- **`declaration_nos` is exact-match, no normalization.** Memory `feedback_no_derived_in_source` + CO request spec ("exact strings after Data Hub's existing declaration normalization"). Data Hub stores declaration_no as-supplied by BCCT ingest; normalization is a separate concern that lives in the ingest pipeline. If CO needs case folding, it normalizes its own input before sending.

- **No cursor when `declaration_nos` is provided.** Caller already names the finite set; pagination adds complexity without benefit. Cap at 500 matches the spec.

- **`limit` cap of 500 on the default list path too.** CO never paginates this endpoint without a `declaration_nos` filter, but the cap prevents accidental full-table scans. Standard `_page_args` would have allowed up to 1000; explicit `min(safe_limit, _DECLARATIONS_NOS_MAX)` caps at 500 for consistency.

- **ZIP `..` rejection over try-to-clean.** Even after stripping `/`, an input like `../../etc/passwd` left `....etcpasswd` (the test caught this). Path traversal hardening: if cleaned contains `..`, drop to fallback. Simpler than trying to make a "safe" version of a clearly hostile input.

- **`NO_FILES_FOUND.txt` marker plus full manifest** instead of empty-archive-or-error. Operator gets a well-formed ZIP even when zero files match — same UX as the happy path, plus the manifest still tells them exactly which declarations are missing files.

## What Didn't Work

- **First test of unauth bounce returned 401, not 303.** Cause: FastAPI route registration order is first-match-wins, and the `/{declaration_no}` detail route swallowed `download.zip` because I'd registered the ZIP route AFTER it (it came after the upload routes in the original layout). The detail route used `auth.require_user` which raises 401, defeating my redirect logic. Fixed by moving the ZIP route definition to immediately before `/{declaration_no}`. Inline comment in `declarations.py` flags this for future edits.

- **First archive-filename test failed.** `filename=../../etc/passwd` was sanitized down to `....etcpasswd.zip` (my filter stripped `/` but kept `.`). Fixed `_safe_archive_filename` to drop the result entirely when `..` is present in the cleaned string and fall back to the default name.

- **`settings_store.set` doesn't exist** — only `set_many`. Caught by the first test fixture run; pattern copied from `tests/test_substitute_api_v1.py` after correction.

## Open Items

- **CO consumer PR pending.** Per the API request spec, CO needs to add `list_declarations()` to `app/data_hub_client.py`, wire it into `DataHubPortfolioService.co_case_source_context()`, and surface ZIP download links in the TKX/TKN tab. Data Hub provider tests + changelog landed (matches CO `CLAUDE.md` rule); awaiting CO ping-back on consumer ship.

- **Push 8 commits to `origin/main`.** Carried over from prior STATUS. None yet pushed in this multi-day session.

- **Deploy bundle to demo box.** Single deploy will pick up everything since `fd793fc`: mig 065/066, M16 ingest, UoM overrides, A.2 conflicts page, declaration file status API + ZIP route.

- **Soak test mirroring `C.1.a`.** As with `bcct/by-codes`, the new endpoint hasn't been exercised under real CO substitute-modal load. CO consumer ship + a few days of live calls will tell whether the EXPLAIN plan + index usage holds up. Add a `C.1.a`-style backlog entry if needed after CO is live.

- **`limit` parameter naming convention.** Some `/v1/hub/*` endpoints cap at 1000 (default `_page_args`); this one caps at 500. Mostly fine but a future cleanup could centralize per-endpoint caps in a single registry. Defer until 3+ endpoints diverge.
