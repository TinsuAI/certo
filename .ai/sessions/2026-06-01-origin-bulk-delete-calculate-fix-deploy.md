# Session 2026-06-01 — Origin bulk-delete, "Đang tính" fix, deploy, screenshot reorg

Continuation of client feedback batch 1. Started on #4(b)+#6, pivoted hard after
two wrong directions, then fixed the real "Đang tính" calculate bug, shipped UI
tweaks, deployed, and reorganised screenshots.

## What Was Done

**#6 bulk-delete NVL rows in the BẢNG KÊ (origin sheet)** — `13d0fcd`.
- Per-row checkbox in a **dedicated select column** (separate from STT), per-sheet
  select-all in thead, a **"Chọn dòng không có tồn/BCCT"** quick-select
  (`data-row-no-stock="1"` = `allocation_count == 0`), and a bulk-action bar.
- Delete reuses the existing **staged** path: extracted `stageRowDeletion()` (shared
  with the substitute modal's "Xoá dòng này") → marks rows struck + records
  `pendingOps.deletes`; persisted on the single "Lưu bảng kê". No new endpoint.

**fix: "Đang tính…" stuck forever (THE bug the client hit)** — `13d0fcd`.
- Root cause: a BOM-derived norm with >6 decimals (`3.351351351`) fails HTML5
  `step="0.000001"` (stepMismatch) → the whole origin form is `:invalid` → clicking
  "Load BOM" never fires submit/fetch. Button text "Đang tính…" is set by a separate
  click handler, so it looks stuck. Changed all 11 numeric inputs to `step="any"`.

**perf: decouple BCCT pull from /calculate** — `13d0fcd`.
- `_calculate_stock_rows_from_snapshot` now reads the materialized co_stock snapshot
  directly and kicks a **non-blocking background refresh thread**
  (`_schedule_background_co_stock_refresh`, per-client in-flight guard) when stale —
  instead of a synchronous full BCCT re-pull (~minutes for johnson's 60k rows).

**fix: recover stuck `calculating` status** — `13d0fcd`.
- `durable_sheet_status()` coerces the transient `calculating` → `stale` at both the
  merge boundary (`merge_origin_action_payload`) and normalization
  (`attach_origin_sheet_states`), so an interrupted calc never leaves a sheet
  silently un-lockable.

**UI tweaks** — `13d0fcd`.
- Select checkbox → own column. Sheet reorder → dedicated **confirm modal**
  (up/down list + Áp dụng/Huỷ + "cần tính lại" warning), replacing the
  misclick-prone inline `‹ ›` tab arrows (removed both old reorder handlers).

**Deploy** — `8fe944a` (this is the demo tip).
- Pushed to origin+tinsu. Deploy failed on `docker compose up --build`: the demo
  server times out reaching Docker Hub for `docker/dockerfile:1.7`. Removed the
  `# syntax=` directive (Dockerfile uses no 1.7 features) → built on cached base
  images → deploy green (tests + healthcheck + DH smoke all pass).

**Screenshot reorg** — `e777144` (local-only).
- Adopted Data Hub layout: `.ai/features/<slug>/{brief.md, screenshots/<run>/}`.
  11 briefs → `brief.md`; 56 previously-committed PNGs relocated into the now-ignored
  feature folders (removed from git HEAD, local-only); 15 doc refs updated;
  `.ai/features/README.md` + `.gitignore` (`.ai/features/*/screenshots/`).

Tests: **419 passed + 8 skipped** (new: step="any" guard, snapshot read x3,
calculating→stale x2, bulk-row markup, reorder modal markup).

## Decisions Made
- **#4(b) CO heuristic — dropped.** It only fires when DH has no precomputed
  substitute, and DH covers all real materials (the misses are HS-less junk). Reverted
  the prototype; the real lever is DH-side ranking (file a DH request with client
  examples). See memory `substitute-heuristic-dead-path`.
- **#6 target = bảng kê rows, not the dossier list.** First built on the dossier list
  (wrong) → reverted entirely. Data tables are read-only DH-delegated. See memory
  `bangke-bulk-row-delete`.
- **Screenshots local-only, not committed.** Repo has 200+ PNGs incl. debug; chose to
  keep the feature-folder structure but git-ignore `screenshots/` (briefs committed).
- **Deploy: remove `# syntax=` rather than touch server.** Repo-side, robust fix; the
  underlying server↔Docker Hub network issue is left to ops.

## What Didn't Work
- **First #6 on the dossier list** — wrong surface, fully reverted.
- **#4(b) heuristic improvement** — wrong investment (near-dead path), reverted.
- **Misdiagnosed "Đang tính" as server slowness.** Spent effort instrumenting
  `/calculate` (it's fast: ~4-6s). The request was never sent (HTML5 validation block).
  `waitForResponse('/calculate')` timing out was a measurement artifact, not a hang.
  Lesson: when a submit "hangs" with no network request, check `form.checkValidity()`.
- **Retrying the deploy** — failed identically; the Docker Hub timeout was persistent,
  not a blip. Fixed via the Dockerfile change instead.

## Open Items
- **#2 & #4 need client input** to close batch 1 (email drafted at
  `C:\temp\toss\barry-co-email-update-batch1.txt`). #4 → then file
  `.ai/api-requests/2026-06-01-substitute-ranking-quality.md`.
- **Reorg `e777144` is local-only** — push if remotes should carry the new layout.
- **Leftover tracked screenshots** `co-case-overview-lock` (11) + `data-hub-e2e` (5)
  still committed under `.ai/screenshots/`; remove for consistency if desired. ~9
  unsorted verification/audit folders also remain there (ignored).
- A few throwaway local dossiers (`CO-BULKUI-*`, `CO-VER-*`) created during local
  verification on growatt — harmless dev-DB rows.
