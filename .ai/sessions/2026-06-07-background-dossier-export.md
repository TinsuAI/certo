# Session 2026-06-07 — Background dossier export (+ missing TKN PDF fix)

Commit: `dc1b582` (committed, **not pushed/deployed**). Brief:
`.ai/features/2026-06-07-background-dossier-export.md`.

## What Was Done
Started from a user report: the dossier `.zip` only had the export tờ khai (TKX),
not the import one (TKN). Fixed that, then reworked the whole export into a
background job, then polished the UI.

1. **Missing-TKN root cause + fix.** Local repro showed both PDFs present, but the
   import merge is huge (25MB / 5668 pages for 194 declarations). DH render
   exceeded the 20s client timeout → `httpx` timeout swallowed by `_fetch`'s
   `except` → TKN silently dropped while the tiny TKX made it.
   - `data_hub_client.MERGED_DECLARATIONS_PDF_TIMEOUT_SECONDS = 180`, passed only
     on the `download.pdf` `.get()`.
   - `_try_fetch_declaration_pdfs` returns `(pdfs, failures)`; a direction that
     had declarations but raised is recorded and surfaced as a ⚠️ warning in
     README/MANIFEST instead of shipping a quietly-incomplete zip.
   - Embedded PDFs renamed to the zip/bảng-kê convention:
     `{case_code}-to-khai-xuat.pdf` / `-to-khai-nhap.pdf`.

2. **Background export.** `/discover` brief → `/tdd`.
   - New `app/dossier_export_service.py`: in-process `ThreadPoolExecutor` runner,
     operator JWT carried via `copy_context()` + explicit re-set in the worker,
     status + zip persisted per case under `state["dossier_exports"]` (side-state
     like `origin_calculation_lock`, doesn't bump the case revision). Zip written
     to `data/local/co-cases/clients/<cid>/dossier-exports/<case_id>/`.
   - Routes in `co_case.py`: POST submit (303→review), GET `/status` (fragment),
     GET `/download` (`FileResponse`, 409 if stale/unfinished). Heavy build moved
     to `_build_dossier_zip` (runs in worker).
   - `dossier_content_revision(record)` in `co_case_context` — staleness key.
   - `_dossier_export_status.html` fragment + vanilla-JS poll in `co_case.html`.

3. **UI polish.** Fixed a broken flex layout on the download `<a>` (icon/text
   overlap), an invisible spinner (reused the wrong `.workflow-step-spinner`), and
   a low-contrast download-button subtext (opacity-muted white on the blue fill).

4. **Removed the "Đang tải trạng thái…" placeholder.** The review page now
   server-renders the current export state inline (`co_case_step` adds
   `context["export"]` for `step=="review"`); the JS polls only when the state is
   `running`. Kills the placeholder + initial round-trip the user reported hanging.

5. Screenshots: `.ai/screenshots/2026-06-07-background-dossier-export/`
   (01 all states harness, 02 in-page done, 03 in-page running).

## Decisions Made
- **Staleness = content hash, NOT `co_cases.revision`.** The revision integer is
  Postgres-only (None in file-mode/tests) and a bare reopen with no edit would
  needlessly bump it. `dossier_content_revision` hashes dossier-relevant record
  fields (products, sheet states, chứng-từ content hashes, shipment, close-state),
  excluding derived snapshots. Reopen→reclose with no edit keeps the saved zip
  valid; an actual bảng-kê/chứng-từ change marks it stale.
- **Orphan detection = live Future in `_FUTURES`, not a TTL.** Single-worker
  deploy: a `running` entry with no live future = worker died on restart/deploy →
  immediately re-runnable. (A TTL would block re-export for minutes after every
  deploy — hit this live when `--reload` killed a job mid-run.)
- **In-process thread, not a queue** (no redis/celery; `--workers 1`; one heavy
  job/day). Reuses the `copy_context().run` idiom from `bom_service`.
- **De-emphasis via color token, never opacity** (memory `css-no-opacity-muted-text`).
- **Server-render state** so the page is correct even if the poll JS never fires.

## What Didn't Work / Ruled Out
- **GIL-starvation hypothesis** for the "slow status" complaint — disproved by
  measurement: status endpoint is ~0.2s even mid-render (the heavy part is httpx
  I/O for the 25MB PDF, which releases the GIL). The real fragility was the
  client-side placeholder depending on a JS round-trip → fixed by server-render.
- Could not reproduce the exact placeholder "hang" in Playwright (it worked), but
  the server-render fix removes the failure mode regardless of cause.

## Open Items
- **Push + deploy `dc1b582`**, then smoke "Xuất hồ sơ" on prod.
- **⚠️ A large pre-existing uncommitted work stream (~900 lines) is still in the
  tree** — NOT dossier (clients/workspace/pages/bom/client_context + most of
  app.css + some test_co_demo hunks + untracked `_source_stats.html`,
  `2026-06-07-products-total-count.md`, trừ-lùi audit/session). `dc1b582` was split
  cleanly out of it via per-hunk `git apply --cached`. Its owner should review/commit
  it separately. STATUS.md + this session log are also unstaged.
- Minor race: if the worker finishes before `submit` stores the Future, a done
  Future lingers in `_FUTURES` (harmless — `_is_running` treats done as not-running).
- Pre-existing `test_data_hub_policy` failure is `app/routers/bom.py` (that other
  stream), not dossier.
