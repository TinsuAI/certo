# 2026-06-14 — Client nav redesign + upload detail + UoM review → v0.15.0

Follow-on session after the v0.14.0 release earlier today. Shipped a second
release (0.15.0) covering UI work + a system-wide UoM conversion review.

## What Was Done

**1. Client-workspace nav redesign (PR #5).** Replaced the single 6-item "Dữ
liệu" dropdown in `_client_nav.html` with **3 domain groups** (user-picked from
3 mockups): Danh mục (catalog · bqd), Hải quan (bcct · declarations), BOM (định
mức · Đề xuất · cần xử lý · hệ số quy đổi). **Đề xuất** now nests under BOM;
`uom-factors` moved from the Cấu hình group into BOM. Active-group highlight via
`active_tab`. New i18n keys `navgrp.*` + `tabs.declarations` (VI/EN parity).

**2. Upload detail + download + preview (PR #5).** `app/routes/uploads.py`: new
`detail_view` (`GET /clients/{id}/uploads/{uid}`) with full metadata (uploader
via `hub.users` join, SHA-256, MIME, bytes, rows, parse-result JSON),
`download_upload` (original blob, unicode-safe content-disposition), and
`_build_preview`/`_preview_for` rendering the first 50×25 cells via
`app/parsers/_excel.load_xlsx` (xlsx/xls) or `csv` — best-effort, never 500s.
New `clients/upload_detail.html`. Uploads list gained an uploader column,
filename→detail link, localized status badges (incl. real statuses
`mapping_pending`/`pending`/`pending_preview`).

**3. Whole-row click-to-detail (PR #5).** New `app/static/js/row-link.js` (click
`tr[data-row-href]`, ignores inner links/buttons/forms/summary; Enter / middle /
ctrl-cmd-shift = new tab), included globally in `base.html`. `data-row-href`
added to BCCT, Danh mục, BOM, Đề xuất, Tờ khai, Tải lên rows. CSS cursor/hover.
`test_bcct_paging.py` row-count proxy switched to `data-row-href` (one per `<tr>`).

**4. Screenshot convention codified.** After placing screenshots inconsistently
(`data/screenshots/nav_uploads/` scratch vs feature folders), moved this
session's UI proof into `.ai/features/2026-06-14-client-workspace-nav-uploads/`
(brief + `ui_smoke.py` writing to its own `screenshots/`) and documented the
**two-tier rule** in `AGENTS.md` (How We Work), global `~/dotfiles/ai/RULES.md`,
and memory `feedback_feature_folder_with_screenshots`.

**5. uom-preview empty-box fix (PR #6).** `.uom-preview{display:inline-block}`
overrode the browser-default `[hidden]{display:none}` → empty cyan box on
`/uom-factors` before any input. Fix: `.uom-preview[hidden]{display:none}`.

**6. UoM conversion-logic review (PR #7).** Two parallel audit subagents (Data
Hub call-sites; CO consumption) + direct verification. Verdict: **core math
correct & consistent; CO does no UoM math.** Findings → fixes:
- **P1** docs: rewrote the confusing `/uom-factors` hint + tooltip; fixed the
  **inverted** import-template sample (`EA→SETS factor=4` w/ note "1 SETS gồm 4
  EA" → `SETS→EA factor=4`) and added a direction definition to the Hướng dẫn
  sheet (`client_uom_overrides.py`).
- **P2** logic: `make_uom_lookup` now accepts a reverse-only client override by
  inverting it (parity with `classify_uom_relation`) — fixed the asymmetry where
  the panel/drift said "convertible" but flatten emitted `uom_conversion_missing`.
- **P3** guard: `materialize_shallow_and_full_flat.py` warns on multi-canonical
  leaves before the WALK `sum()+max(uom)` collapse (`_group_offenders` +
  `detect_multi_canonical_leaves`). Confirmed benign today (all 34 real
  multi-uom leaves are PCS/ST → `pcs`).
- **P4** (CO, deferred): sister-app-note
  `.ai/sister-app-notes/2026-06-14-co-allocation-unit-match-guard.md` with a
  warn-don't-convert spec. Not applied — CO `co_case_context.py` is mid-redesign.
- Tests: `tests/test_uom_factor_direction.py` (6) + `tests/test_uploads_detail.py` (8).

**7. Release 0.15.0.** Merged PRs #5/#6/#7 locally (merge commits, resolved
CHANGELOG `[Unreleased]` conflicts by combining), pushed once (1 deploy), deleted
branches. Then cut 0.15.0: `[Unreleased]`→`[0.15.0]`, `pyproject` 0.14.0→0.15.0,
`chore(release): 0.15.0`, tag `v0.15.0`, GitHub Release. Prod verified on 0.15.0.

## Decisions Made

- **Separate focused PRs** (nav/uploads, uom-preview, uom-factor) rather than
  one — but it caused localhost to flip to old-main UI when the working tree was
  on a main-based fix branch. User then chose to **merge all to main** (= deploy
  prod) to consolidate.
- **Merge locally + push once** instead of 3× `gh pr merge` → 1 CD deploy
  instead of 3; GitHub still marked all 3 PRs MERGED.
- **No version bump per-PR**; accumulate in `[Unreleased]`, cut a release after
  (matches how 0.14.0 folded PRs #2/#3/#4).
- **P2 implemented in `make_uom_lookup`, not `resolve_conversion`** — avoids
  touching cascade precedence and double-handling (classify already does its own
  reverse). Gated on override sources only (`_OVERRIDE_SOURCES`).
- **P3 flags distinct CANONICAL, not family** — g vs kg (same family, diff
  base_factor) must be flagged because the WALK sums raw before converting.
- **P4 not applied to CO** — `co_case_context.py` is in the user's active WIP on
  `feat/rd3-bangke-split`; captured as a non-disruptive sister-app-note instead.

## What Didn't Work

- `git pull --ff-only origin main` failed ("cannot pull with rebase: unstaged
  changes") due to the pre-existing `uv.lock` mod + user's `pull.rebase=true`.
  Didn't matter — origin/main hadn't advanced; proceeded with local merges.
- First write of `AGENTS.md` hit "Refusing to write through symlink" — `CLAUDE.md`
  → `AGENTS.md`; edited the real target (`AGENTS.md`) directly.
- Initial multi-uom diagnostic query used `client_id` on `hub.bom_edges` (no such
  column); it's keyed by `artifact_id` + `root_code`.

## Open Items

- **P4 CO allocation guard** — apply when `feat/rd3-bangke-split` lands.
- **Declarability rollout** — prod backfill + CO adoption + flag flip (carried).
- **Outage ops** — confirm old tars pruned after ~20/06.
- Backlog unblocked: B.0b `material_group`→`item_type_token`, A.0 RD07
  drawing auto-hide, D.2 staleness fingerprint (build on `classify_uom_relation`).
- Pre-existing latent (not in scope, flagged): uploads "Xem ánh xạ" link guards
  on `proposed_mapping` but real status is `mapping_pending` → link never shows.
