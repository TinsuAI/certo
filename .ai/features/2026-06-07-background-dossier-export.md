# Feature: Background-task dossier export

Rework the synchronous `POST /clients/{client_id}/co-case/{case_id}/export-dossier-zip`
(`app/routers/co_case.py:1126`) into an async in-process job so operators don't
stare at a frozen request and large imports don't risk timing out mid-request.

## Context (current behaviour)
- The endpoint builds the whole dossier inline and returns
  `StreamingResponse(iter([content]))` (`co_case.py:1195`) — the full ~25MB zip
  is materialised in memory first, then streamed. Measured ~43–45s wall-clock
  for case `co-case-ec000d03522e` (194 import declarations → 5668-page merged
  PDF). The 2026-06-07 fix (per-request 180s DH timeout + loud-failure warning)
  stopped the silent-TKN-drop, but the UX is still a multi-second frozen POST.
- Deploy runs `--workers 1` per stack (`Dockerfile:30`); two stacks (PROD :8755,
  DEMO :8765), each its own process. No redis/celery/broker in the stack.
- DH calls need the operator JWT from `CURRENT_DATA_HUB_TOKEN`, set per-request
  in `app/main.py:160` middleware from `user.access_token`. Off-request DH work
  already has an idiom: `ThreadPoolExecutor` + `copy_context().run`
  (`app/bom_service.py:217`).
- A per-case lock pattern already exists: `acquire_origin_calculation_lock` /
  `active_origin_calculation_lock` / `release_origin_calculation_lock`
  (`app/co_case_store.py:270`).
- Case artifacts persist on the filesystem under `data/local/co-cases/<client>/
  <case>/…` via `case_upload_root` / `case_root` (`co_case_store.py:1065`).

## Scope
**In:**
- Submit endpoint returns immediately (202 / redirect) after queuing the job;
  no blocking render in the request.
- In-process job runner: `ThreadPoolExecutor` (1–2 workers) + `copy_context().run`
  so the worker thread inherits the captured DH token. Build the zip
  (`create_dossier_zip`) off-request and write it to disk under the case dir.
- Job-status record persisted per case (`queued|running|done|failed`, timestamps,
  result path, error summary, the embed-failure warnings already produced by
  `_try_fetch_declaration_pdfs`).
- Review page (`app/templates/co_case.html:1737`) shows job state via an htmx
  poll fragment: `Đang tạo…` pill → `Tải về` button when `done`; surfaces the
  ⚠️ embed-failure warning if any direction was dropped. Status survives leaving
  and returning to the page (read from the persisted record).
- Download endpoint serves the persisted zip via `FileResponse`.
- Per-case export lock (reuse the origin-lock idiom) so a second submit while a
  job is running is a no-op that re-attaches to the in-flight job.

**Out:**
- No external broker / durable queue (redis/celery/arq) — decided below.
- No multi-worker scaling, no cross-stack job sharing.
- No global/cross-page notification surface — review-page poll only.
- No change to dossier *content* (already settled 2026-06-07).
- No push/email notification.

## Decisions
- **In-process thread, not a queue.** `--workers 1` + one heavy job/day makes a
  broker over-engineering. Reuse the proven `copy_context().run` idiom.
- **Token captured at submit.** Read `user.access_token` in the request handler
  and pass it into the job; the worker sets `set_current_data_hub_token(token)`
  inside its `copy_context().run` (the request-scoped contextvar is already gone
  by the time the thread runs). DH 401 mid-job ⇒ job `failed` with a clear "phiên
  đăng nhập hết hạn, đăng nhập lại rồi xuất lại" message.
- **Result on disk, status in the case store.** Write the zip to the case dir
  (overwrite latest; keep only the most recent export per case). Status record
  lives with the case so a page reload/return reflects true state — not in-memory
  only (in-memory dies on deploy).
- **Cache keyed by `co_cases.revision` — never serve a stale zip.** The export
  job records the case `revision` it was built from. Export is only allowed when
  the case is closed (409 gate, `co_case.py:1136`); editing the bảng kê requires
  **"Mở lại hồ sơ"** (`reopen-case`, `co_case.py:1320`), which is a mutation that
  bumps `revision` (every `save_case_record` bumps it — reopen, sheet lock,
  supporting-file change). When the current `revision` ≠ the export's recorded
  revision, the saved zip is **stale**: the button flips from `Tải về` to
  `Xuất lại` and a new job regenerates it. Lifecycle:
  `close → export → download (cached) → reopen [revision++] → edit → close →
  Xuất lại`. Using the revision integer (not a bespoke reopen flag) covers any
  dossier-affecting change, not just reopen.
- **Notify = htmx poll on review page.** Lightest fit; htmx already in use.

## Risks
- **Job lost on deploy/restart.** A `running` job whose process died must not spin
  forever. Mitigation: on submit, if the recorded job is `running` but older than
  a TTL (e.g. > render-timeout budget) and no live future exists in this process,
  treat it as stale → allow re-run. Consider marking orphaned `running` → `failed`
  on app startup.
- **JWT expiry during a long job** (render can run minutes). The captured token
  may expire before DH finishes. Accept for v1 (fail with re-login message);
  revisit only if it bites.
- **Memory: still builds the full ~25MB zip in RAM** before writing. Acceptable
  per job; just don't run many concurrently (cap pool at 1–2).
- **Double-submit / refresh storms.** The per-case lock + idempotent re-attach
  prevents duplicate renders.
- **Filesystem vs Postgres case store.** Status writes must go through the same
  store the case uses (`co_case_store` has both filesystem and a Postgres path) —
  don't bolt on a parallel store; extend the existing record/lock surface.

## Open Questions
- Where exactly to persist job status: extend the case record (a `dossier_export`
  sub-object) vs a small sibling jobs store? Lean: sub-object on the case record,
  guarded by the existing revision/lock machinery.
- Poll cadence + when to stop polling (done/failed, or a hard ceiling).
- Retention: "latest export only, overwrite" + revision-keyed staleness
  (confirmed with user 2026-06-07). One saved zip per case; regenerated when
  `revision` moves.
- Should the existing 180s DH timeout grow now that we're off-request (no HTTP
  client deadline pressure)? Probably keep 180s; the job wrapper enforces its own.

## Implemented 2026-06-07 (deviations from the plan above)
- `app/dossier_export_service.py` — generic in-process runner: `submit_dossier_export`
  / `dossier_export_status` / `dossier_export_result_path`. State under
  `state["dossier_exports"][case_id]`; zip written to
  `data/local/co-cases/clients/<cid>/dossier-exports/<case_id>/`.
- **Staleness key = a content hash, not `co_cases.revision`.** `co_cases.revision`
  is Postgres-only (None in file-mode/tests) and a bare reopen with no edit would
  needlessly bump it. Instead `dossier_content_revision(record)` (in
  `co_case_context`) hashes the dossier-relevant record fields (products, sheet
  states, chứng từ content hashes, shipment, close-state), excluding derived
  snapshots. Works in all modes; "reopen→reclose with no edit" stays valid.
- **Orphan detection = live Future check, not a TTL.** Single-worker deploy: a
  `running` entry with no live future in `_FUTURES` means the worker died on a
  restart/deploy → immediately re-runnable. (Found during live test: `--reload`
  killed a job and a TTL would have blocked re-export for 30 min.)
- **No htmx in this app** (the `hx-boost` attrs are inert) → the review page polls
  `…/export-dossier-zip/status` with a small vanilla-JS `fetch` loop; the
  fragment `_dossier_export_status.html` carries `data-export-status` to stop the
  poll. Routes: POST submit (303 → review), GET `/status` (fragment), GET
  `/download` (FileResponse, 409 if stale/unfinished).
- Token injected via `copy_context()` snapshot + explicit
  `set_current_data_hub_token` in the worker.
- Tests: `test_dossier_export_service.py`, `test_dossier_content_revision.py`;
  existing route tests updated to POST→download. Live-verified on
  `johnson-vn/co-case-ec000d03522e`.

## Suggested next step
TDD the job runner + status transitions (queue → running → done/failed, token
injection, stale-job re-run) with a fake slow `create_dossier_zip` and fake DH,
before wiring the htmx fragment. The lock/idempotency and token-capture paths are
the parts most worth a failing test first.
