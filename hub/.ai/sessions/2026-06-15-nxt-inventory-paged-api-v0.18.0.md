# Session — NXT + inventory paged read API (v0.18.0) + Growatt drive-download triage

**Date:** 2026-06-15
**Outcome:** (1) Built, reviewed-inline, **merged (PR #10, `7fc84a8`), released
`v0.18.0`, deployed to prod** the paged/filtered line read API for the NXT +
year-end-inventory tier. (2) Investigated a 645MB Growatt drive-download and
concluded **nothing new to onboard** (no DB change).

## What Was Done

### 1. NXT + inventory paged read API → v0.18.0
User ask: "triển khai vụ api cho nxt và tồn kho trong backlog". The read API
(`/v1/hub` list/get/period-end-link, Bearer) already existed (v0.16/0.17), so the
backlog item (STATUS next-step #1) had 3 candidate scopes. User delegated the
choice ("mày recommend đi"); I picked **(a) richer/paged read** — lowest
architectural risk (write/ingest is blocked on BCQT's read-only role; cookie-UI
mirror is YAGNI), real consumer need (BCQT pages NXT lines for Mẫu 15/15a), and
the `get_artifact` GET returns ALL lines in one payload (Johnson MB5B ~20k).

Implemented (commit `37818f6`):
- **`app/routes/api.py`** — 2 new endpoints `…/nxt/{aid}/lines` and
  `…/inventory-snapshots/{sid}/lines`; `period_year`/`year` filters on the two
  list endpoints. Reused `_page_args` offset-cursor; exact `total`, `next_cursor`,
  `server_time`; `404` on unknown/cross-client via `get_artifact_meta`/
  `get_snapshot_meta`.
- **`app/stores/nxt.py`** + **`app/stores/inventory_snapshots.py`** — `count_lines`
  + `code`/`role` (nxt) / `code`/`warehouse` (inv) filters on `list_lines`;
  `period_year` on `list_artifacts`; `year` on `list_snapshots`. Filter fragments
  built via a private `_line_filter_sql` helper (values stay bound — f-string only
  injects the literal WHERE fragment).
- **`tests/test_nxt_inventory_api.py`** — 13 provider tests (pagination round-trip
  no-dup/complete, each filter, bad cursor 400, unknown + cross-client 404,
  derived closing_implied/variance present). Modeled on `test_bcct_by_codes_api.py`
  (auth-disabled fixture).
- Docs: `API_CONTRACT.md` + `API_CHANGELOG.md` (Additive 2026-06-14).

Release (`c91186b`): pyproject 0.17.0→0.18.0, `CHANGELOG.md` [0.18.0] (VN). PR #10
→ CI green (Test + Docker build) → `gh pr merge --merge` (no --delete-branch) →
ff-only local main → tag `v0.18.0` + GitHub release → main CD green → prod
verified `/version`=0.18.0 (`git_sha=7fc84a8`), `/healthz` 200, new endpoint
returns 401 (strict auth on, correct). Full suite **1544 passed, 16 skipped**.

### 2. Growatt drive-download triage (no DB change)
User: "xem … growatt có gì thì onboard … move qua prod" pointing at
`P:\Downloads\drive-download-20260614T161834Z-3-001.zip` (645MB). Extracted to a
gitignored scratch dir, diffed every file `(declaration_no, sha256)` against the
DB, then cleaned up the extraction. Findings:
- **`BaoCaoHangChiTiet NK/XK (20.05.2026).xls`** — md5 byte-identical to the
  onboarded 2026-05-27 set → BCCT already current (39,203 rows). Nothing new.
- **`TKX.rar`** (500 export TK forms) — all 500 already in DB. 0 new.
- **`TKN.zip`** (3541 import TK forms) — 3538 already in DB; the 3 "new"
  (`107030121660`, `107237070360`, `107666871320`) are the 3541-vs-3538 gap and
  are **known-bad**: two have content from a *different* (already-onboarded)
  declaration; one has a blank declaration-number cell. Content-validation
  rejects all 3 (status mismatch/parse_error).
- **`trừ lùi CO … SXXK 2025 .xlsm`** — Barry/CO-System's settlement input
  (user-confirmed mid-task), out of Data Hub scope. Not touched.

Net: package is a re-download of the same 20.05.2026 ECUS export already
ingested; nothing valid to onboard, nothing to move to prod.

## Decisions Made

- **API scope = paged read (a)**, not write/ingest or cookie-UI mirror. Rationale
  in STATUS / above. Additive only — kept the full-artifact GETs unchanged so no
  consumer breaks and the changelog stays "Additive".
- **Exact `total`** (per-store `count_lines`) rather than `total_estimate: null` —
  cheap for a single artifact's lines and what a paging consumer needs.
- **Declined to force-import the 3 bad TKN files.** `validate_content=True` exists
  precisely to stop a wrong/blank form being attached to a declaration. The 3 are
  legit-but-unusable exports; the fix is re-exporting from ECUS, not bypassing
  validation.

## What Didn't Work

- **First `rarfile` attempt** failed (`ModuleNotFoundError`) — installed via
  `uv pip install rarfile` (venv-only, ephemeral). It then drove the system `7z`
  backend and extracted all 500 TKX members correctly (the 491-vs-500 "gap" was
  just 9 `.xlsx` members, not the RAR5 only-file-#1 truncation bug). `.xls`/`.xlsx`
  are both supported by the declaration parser.
- **The 3 "new" TKN files looked like genuine deltas** until the dry-run parse —
  `parse_staged_files` flagged 2 as `mismatch` (filename decl ≠ content decl) and
  1 as `parse_error` (blank Số tờ khai). Confirmed they were already skipped on
  2026-05-27 (same filenames present there). Lesson reinforced: verify
  `(key, sha256)` + content before treating re-download files as new.

## Open Items

- Cross-link BCQT to consume `/v1/hub` incl. the new `…/lines` endpoints +
  `period_year`/`year` filters (write a sister-app note).
- I2 code-join resolver (NXT/inventory code ↔ catalog) so cross-links +
  period_end_link fire on real data.
- Dev DB cleanup: ~30 `nxt-api-*` test clients created by the new test file's
  non-cleaning fixtures (+ leftover `nxt-*`/`inv-det-*` from prior session). Add
  fixture teardown or drop them.
- Carry-overs: UoM review P4 (CO allocation guard); declarability prod rollout +
  CO adoption; outage tar-prune confirm after ~20/06.
- Pre-existing dirty tree (`uv.lock`, `.ai/BACKLOG.md`, untracked `.ai/sessions/*`)
  left uncommitted, as before — NOT from this session.
