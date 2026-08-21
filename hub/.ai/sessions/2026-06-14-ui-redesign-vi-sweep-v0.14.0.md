# Session — UI redesign + Vietnamese sweep + v0.14.0 release

**Date:** 2026-06-14
**Outcome:** Shipped **v0.14.0** to prod (`https://ttdatahub.tinsu.ai`), tagged +
GitHub Release. Bundled two backlog items (G.1, G.2) + a clients/top-nav redesign
+ a Vietnamese UI sweep. Plus a significant correction to the team's understanding
of the CD pipeline.

## What was done

Started from "xem backlog xem nên làm gì". Picked **G.2 + G.1**, then the user
added four directives (changelog rule, clients-page redesign, top-nav redesign,
Vietnamese sweep). All landed in **PR #4** (`feat/ui-redesign-vi-sweep`, merged
`ec3f0ab`).

**G.2 — adapter-binding tree-adapter gap (fix).** A tree adapter
(`sap_indented_walk` / `multi_sheet_per_root`, `emits_intermediate_btp_versions=
False`) selected via the per-client default-adapter binding or the manual dropdown
took the explicit-profile path, which — unlike `auto` — lacked the raw-edges
reroute. Its walked leaves stashed as `manual_flat`/`not_applicable` and flatten
was silently skipped (MPL0100-39). Fix (option a): extracted
`_tree_adapter_needs_raw_edges()` in `app/routes/bom.py`, applied it on the
explicit path (reroute → `technical_raw` when a raw-edge parser also matches) and
refactored the `auto` block to share it. TDD: failing test first
(`tests/test_bom_ingest_followups.py`, +2). Commit `017c4ea`.

**G.1 — shared grouped admin sub-nav.** 6 divergent hand-rolled admin link rows →
one `app/templates/_admin_nav.html` with grouped `<details>` (Người dùng · Dữ
liệu tham chiếu · Adapter BOM · Hệ thống[dev-only]), self-highlighting from
`request.url.path` (no route change). Wired into all 8 admin pages; the orphaned
`/admin/settings/embedding` is now linked. +3 tests (`tests/test_admin_nav.py`).
Commit `8373cac`. Brief: `.ai/features/2026-06-14-nav-redesign/`.

**Clients page + top nav + Vietnamese sweep.** Commit `b446c1f`.
- Clients list: instant client-side search (name/code/MST), resolution-mode badge
  in Vietnamese, the 6-tile module grid condensed to a one-line chip legend.
- Top nav: reworked to global chrome + user menu — section links left (Khách hàng
  · Quản trị, active from `active_root`), theme toggle + avatar `<details>`
  dropdown right (name/role · language · logout). Breadcrumb dropped (client name
  is in the page header).
- Vietnamese sweep of high-visibility surfaces (`app/i18n.py` vi block + templates):
  tabs (Tổng quan / Tải lên / Đề xuất / Cấu hình), resolution/proposal modes,
  module metas, proposals copy, upload titles. Brief:
  `.ai/features/2026-06-14-clients-topnav-vi-sweep/`.

**Release 0.14.0.** `pyproject` 0.13.1 → 0.14.0; CHANGELOG `[0.14.0]` folds in
everything live-but-unreleased since 0.13.1 (PR #2 declarability mig 078/079, PR #3
adapter module-mgmt mig 080/081, this PR). Merged PR #4 (merge-commit) → main push
→ prod **Deploy** job green (compose up → /healthz → both auth smoke gates incl.
public `ttdatahub.tinsu.ai` → nightly demo refresh). Verified `/version` →
`0.14.0` / `ec3f0ab`. Tagged `v0.14.0` (annotated, on merge commit) + GitHub
Release from the CHANGELOG section. STATUS update committed with `[skip ci]`
(docs-only — avoided a pointless prod redeploy).

Suite throughout: **1480 passed / 16 skipped**.

## Decisions

- **G.2:** fix option (a) — reroute on the explicit path AND share with `auto`
  (makes any tree-adapter selection correct, not just the binding).
- **G.1:** grouped dropdowns (user pick over a flat tab bar) to mirror the
  per-client nav idiom.
- **Top nav:** "global chrome + user menu" direction. User first mis-tapped the
  "light polish" option, then re-picked this; redone accordingly.
- **Clients page:** rows + search (user pick over a card grid).
- **Language policy (user-chosen):** keep customs acronyms (BCCT/BOM/HS/MST/NVL/
  TP/BTP/ĐVT/DNCX/CO/BCQT) **and** admin-technical terms (Adapter, Parser, Service
  token, Preset, UoM); translate feature names + raw enum values + casual English.
  Kept the role-name set (Dev/Admin/Manager/**Staff**) English for set-consistency.
- **Version:** 0.14.0 (minor — new features). Changelog folds in PR #2/#3, which
  had deployed to prod un-changelogged.
- **New standing rule (→ memory `feedback_changelog_on_prod_push`):** every prod
  push must update `CHANGELOG.md` (and `API_CHANGELOG.md` if the `/v1/hub` surface
  changed).

## What didn't work / corrections

- **I was wrong about the CD target.** I told the user the CI Deploy job only
  touched the demo box (misled by the `runs-on: data-hub-demo` runner label). User
  pushed back ("CD có cả prod mà"). On re-check: the Deploy job fires on **every
  push to `main`**, rebuilds `/home/tinsu/data-hub` = **prod** (`ttdatahub.tinsu.ai`,
  `release-engineering.md:84`), and `app/main.py:89` runs `apply_migrations()` at
  boot → **each merge auto-deploys prod and applies pending migrations**. The
  runner label is just a name, not the target; the demo (`tinsu-deploy`, :8764) is
  a secondary best-effort refresh step.
- **STATUS.md was stale/wrong:** it claimed mig 078/079 were "gated, not yet on
  prod". In fact PR #2 and PR #3 merges (2026-06-13) both ran `Deploy: success`, so
  **prod already had mig 078–081**. Declarability is live on prod with
  `exclude_non_declarable` **default-OFF** (zero user impact); the separate
  backfill script has NOT run. STATUS.md reconciled this session.
- **CSS specificity:** `.client-filter { width }` lost to the global
  `input[type="search"] { width:100% }` (0,1,1 beats 0,1,0) → search box blew up.
  Fixed with `.zone-head .client-filter` (0,2,0).
- **Client-side filter:** `r.hidden = true` did nothing because `.rowitem
  { display:flex }` overrides the UA `[hidden]` rule → switched to
  `r.style.display`; the empty-state `<p>` switched from `hidden` attr to inline
  `display:none` so toggling `style.display=''` actually shows it.

## Open items

1. **Declarability backfill decision** (schema already on prod, default-OFF):
   whether/when to run `scripts/backfill_johnson_material_group.py --apply` on prod
   (idempotent, import-aware; post-check: rows with `excluded_at is not null and
   customs_relevance='declarable'` must be 0). Then CO adoption (swap
   `is_bom_technical_noise` → DH `customs_relevance`), then flip
   `exclude_non_declarable` for johnson-vn.
2. **Language follow-up (deferred):** deep BOM-flatten vocabulary
   (flatten/materialize/shallow/unresolved/decision, `bom.upload_profile`) +
   admin-staff sentences (`admin.staff_assign.*`). Noted in the clients-topnav brief.
3. **Dead CSS sweep:** `.topnav-breadcrumb` / `.breadcrumb-*` / `.topnav-user` are
   now unused after the top-nav rework.
4. **CI: Node 20 actions deprecation** — GitHub forces Node 24 from 2026-06-16; bump
   `actions/checkout`, `docker/*`, `astral-sh/setup-uv` versions.
5. **G.2 minor (deferred):** the per-client binding is a UI pre-select only —
   `upload_submit` server default stays `manual_flat`; programmatic/API ingest
   ignores the binding.
6. **Outage ops:** after ~20/06 confirm pre-fix appfiles tars pruned via GFS
   (`~/logs/verify-old-tars.log`).

## Pointers

- Branch `main` = `447edf9` (STATUS update; `ec3f0ab` = v0.14.0 merge). Tag
  `v0.14.0`. Release: github.com/TinsuAI/data-hub/releases/tag/v0.14.0.
- Commits this session: `017c4ea` (G.2), `8373cac` (G.1), `b446c1f` (clients/topnav/
  i18n), `8c7d516` (docs), `a1494a6` (release 0.14.0), `4cd8d67` (STATUS reconcile),
  `447edf9` (STATUS released).
