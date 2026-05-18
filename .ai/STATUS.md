# Project Status

**Date:** 2026-05-18 — Declaration file status API + bulk ZIP download shipped for CO (per CO request 2026-05-15). A.2 catalog conflicts page also shipped in the same session block.

## Current State

**Branch:** `main` at `21f3620`. 8 commits ahead of `origin/main`, not pushed.

Commit streak (most recent first):
- `21f3620` — **NEW:** declaration file status API (`/v1/hub/clients/{c}/declarations`) + bulk ZIP download (`/clients/{c}/declarations/download.zip`)
- `d4ea2d7` — catalog conflicts review queue (A.2)
- `b315eba` — UoM evidence audit brief; refactored overrides per-evidence
- `b4665f6` — Mẫu 16 ingest applies UoM conversion
- `10c2084` — bulk materialize applies UoM conversion + drift signals
- `bb0faf1` — stale-page prefill NVL code + refresh preserves bom_variant_id
- `3baea87` — stale-page tab UI + i18n + bulk-script ordering recovery
- `69b9da0` — Mẫu 16 customs-filed BOM ingest as manual_flat artifacts

**Tests:** 1130 passed, 15 skipped (+29 vs prior status from declaration tests).

**Migrations:** at mig 066. No new mig this session.

**Working tree:** dirty with the same pre-existing unrelated changes
as before (demo-company-feed/* PNG+xlsx, `app/routes/declarations.py` +
`tests/test_customs_declaration_files_store.py` carry a small unrelated
pre-existing M, plus `docs/training/`, `scripts/generate_training_input_scenarios.py`, two prior session notes untracked). None of this is from the current session and none is committed.

**Dev server:** `:8754` workers=4, detached via `setsid` (PID 318295 last seen — verify with `lsof -i :8754` at session start). Log `/tmp/dh_dev.log`.

**Demo box (`100.84.189.87:8754`):** still NOT updated. Backlog of pending deploys: mig 065/066 + M16 ingest + UoM overrides + A.2 conflicts page + declaration file status API + ZIP route. Single deploy will pick all of them up.

## Recent Changes

Two ships in this multi-day session:

### A.2 catalog conflicts page (commit `d4ea2d7`)

Already detailed in `.ai/sessions/2026-05-15-catalog-conflicts-page-ship.md`. Page at `/clients/{cid}/catalog/conflicts`, nav banner on catalog list, inline btp_sourcing dropdown with `return_to`. +8 tests.

### Declaration file status API + ZIP (commit `21f3620`)

Per CO API request `barry-CO-main/.ai/api-requests/2026-05-15-declaration-file-status.md`:

- **Bearer summary:** `GET /v1/hub/clients/{cid}/declarations` — per-declaration `(bcct_line_count, file_count, earliest_bcct_date)`. Filters: `direction`, `declaration_nos` (max 500, exact-match), `has_files`. Identity `(client_id, declaration_no, direction)` — same decl_no in both directions ships as 2 rows. Auth: user JWT or service token `hub:read` + whitelist.
- **Operator ZIP:** `GET /clients/{cid}/declarations/download.zip` — bundles every uploaded customs file at archive root + `DANH_SACH_TO_KHAI.txt` manifest. Duplicate filenames dedupe with `_1/_2/…` suffix. Empty match → archive still ships with manifest + `NO_FILES_FOUND.txt` marker. Cookie-session auth → 303 to `/login?next=…` when unauth. Filename param sanitized (no path traversal, `..` patterns refused).
- Store: extended `list/count_declarations_with_status` with `declaration_nos` filter + new `list_files_for_declarations` bulk helper.
- +29 tests across `tests/test_declarations_api_v1_hub.py` (17) and `tests/test_declarations_download_zip.py` (12). Full suite 1130 passed.
- Sister-app note `.ai/sister-app-notes/2026-05-15-declaration-file-status-available.md`. API contract + changelog updated.

## Next Steps

Priority order (carry-over from prior STATUS plus new follow-ups):

1. **Push 8 commits to `origin/main`** when ready.

2. **Deploy session changes to demo box** — single deploy bundles mig 065/066, M16 ingest, UoM overrides, A.2 conflicts page, declaration file status API + ZIP route.

3. **Wait for CO consumer PR** on the declaration file status endpoint. Per sister-app note: CO adds `list_declarations()` adapter in `app/data_hub_client.py`, wires `co_case_source_context()` to populate `declaration_file_counts`, surfaces ZIP download links in the TKX/TKN tab. Data Hub side complete — no further action until CO ships consumer + reports any contract gaps.

4. **Ask Johnson confirm factor for 58 unverified M16 codes** (list in `.ai/features/2026-05-15-m16-uom-analysis/unverified_codes.txt`). Default factor=1.0 + Tier-A drift signal.

5. **CO repo dropdown logic for dual_source 409**. Data Hub side ready; CO repo at `~/workspace/client/barry-CO-main` needs to handle the 409 + prefer `m16_2025` variant.

6. **Verify `1000454182` factor=2.0** with Johnson (n=2/3 small sample).

7. **70 sản phẩm XK 2026 thiếu BOM** — get from Johnson or document handling.

8. **Next backlog item if bandwidth.** Lined-up candidates from BACKLOG:
   - F.1 Growatt programmatic bulk re-ingest (~0.5-1d, mirror Johnson pattern).
   - A.4.2 Substitute XLSX bulk upload (~0.5d).
   - A.3 Catalog edit permission per-role (~1d, partially shipped).

## Blockers

- Johnson contact / customs broker for UoM factor confirmation (carry-over).
- CO repo dev availability for declaration consumer PR + dropdown logic (carry-over).

## Notes for Next AI Session

- **Dev server PID may have rolled.** Last known: PID 318295 with `setsid` so it survives Bash-tool shell churn. Verify with `lsof -i :8754 -P -n` before relying on it. Start fresh with `setsid nohup uv run uvicorn app.main:app --host 127.0.0.1 --port 8754 --workers 4 > /tmp/dh_dev.log 2>&1 < /dev/null &` if down.

- **FastAPI route registration order is load-bearing.** The ZIP download route had to be defined BEFORE `/{declaration_no}` detail or first-match-wins swallowed `download.zip` as a declaration_no. Caught only by tests. Inline comment in `app/routes/declarations.py` flags this — preserve it on edits.

- **Declaration_no exact-match on the API.** The new endpoint preserves case + format (declaration numbers are typically digits but we treat as opaque strings). If CO needs uppercasing or normalization, surface it as a CO-side concern — don't bake normalization into Data Hub.

- **Cookie-route vs Bearer-route split.** Pattern reused from substitute API (2026-05-13): operator-driven actions stay cookie-only (operator's browser already has the cookie); server-to-server stays Bearer-only (`/v1/hub/*`). The download ZIP is intentionally cookie-only — CO links the operator's browser to it; CO never fetches the bytes itself.

- **`_safe_archive_filename` rejects `..` patterns.** Path traversal hardening for clients that may save the suggested filename as a path. Test covers `../../etc/passwd` → falls back to default `declarations.zip`.

- **Existing cookie-only `/api/v1/clients/{c}/declarations` kept.** Still serves the in-app declarations index page. New `/v1/hub/...` endpoint is the parallel Bearer-aware mirror, not a replacement.

- **`feedback_api_routing_convention.md` memory** confirms the cookie/`/api/v1/*` vs Bearer/`/v1/hub/*` split. The mirror-don't-retrofit precedent (substitute 2026-05-13 commit `ae3373b`) was followed here.

- **Pre-existing dirty state** intentionally NOT committed. Same items as prior STATUS: demo-company-feed/* drift, two unrelated workdir mods on `declarations.py`/`test_customs_declaration_files_store.py` (Note: those files DID have my new content layered on top — but the diff between HEAD and workdir for those two specifically came from a prior session; confirmed by reading the workdir state pre-edit). The two M16-related artifacts (session note + training scripts) remain untracked.
