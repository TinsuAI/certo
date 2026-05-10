# Project Status

**Date:** 2026-05-11 — Johnson onboarding shipped end-to-end (BCCT + TKX/TKN +
catalog AI + substitutes hybrid + embedding + background jobs framework).
BTP dedup bug found + fixed; UI ingest hooks wired and verified live.

5 commits on `main` ahead of `origin/main`, working tree clean.

## Current State

**Branch:** `main`, ahead of `origin/main` by **5**, working tree clean.
**Tests:** 1041 passed, 15 skipped, 0 fail (was 978 → +63 this session
including new tests + the previously-flaky Johnson BOM list test now
passing because Johnson has BOM data).
**Migrations:** at mig **062** applied (4 new this session: 059
customs_declaration_files, 060 material_substitutes + pg_trgm,
061 material_embedding + pgvector, 062 background_jobs).
**Dev server:** running on `:8754` (uvicorn auto-reload, bg task `bmobzw3ke`).

**Postgres extensions enabled:** `pg_trgm`, `pgvector` (0.6.0). Required
sudo install of `postgresql-16-pgvector` package + superuser
`CREATE EXTENSION vector` (vp role isn't superuser).

Feature brief: `.ai/features/2026-05-10-johnson-onboarding/brief.md`.
22 committed UI smoke screenshots in that folder.

## Recent Changes — this session

**5 commits:**
```
e7578bf fix(bom): wire post-ingest hooks for raw-edge parser names
cac2bcb fix(bom): dedup BTP slices across parent TPs + wire hooks for SAP exploded
04de10f docs: Johnson onboarding feature brief + 20 UI smoke screenshots
dcc6216 feat: Johnson onboarding ship — declarations, catalog AI, substitutes, jobs
11ea9bd feat(bcct): Johnson real-data ingest scripts + Phase 4 BOM fixup
```

**New code (high-level):**
- `app/embedding.py` — OpenRouter client + 2-tier config (global + per-client)
- `app/jobs.py` + `scripts/_job_runner.py` — background job framework
- `app/parsers/declaration_files.py` — TKX/TKN file parser (xls + xlsx + pdf)
- `app/stores/{customs_declaration_files,material_substitutes,catalog_bcct_analysis}.py`
- `app/routes/{declarations,jobs,substitutes}.py`
- `app/templates/{clients/declarations*,jobs/,admin/settings_embedding}.html`
- `db/migrations/059..062` (declaration files, substitutes+pg_trgm, embedding+pgvector, background_jobs)
- `scripts/{embed_materials,refresh_substitutes,import_declaration_archive,ingest_johnson_real,fixup_johnson_btp_sx_after_bom}.py`
- 5 new UI smoke scripts + 47 new tests

**Modified:**
- `app/main.py` — 3 new routers (declarations, substitutes, jobs)
- `app/data_promotion.py` — 2 new tables registered, 1 excluded (background_jobs)
- `app/routes/catalog.py` — BCCT analysis panel + AI panel context (per-client stats + ETA helper)
- `app/templates/clients/{catalog,catalog_detail}.html` — multiple new sections
- `app/parsers/bom_adapters/__init__.py` — `materialize_shapes` hook + raw-edge parser aliases
- `scripts/{derive_btp_shallows,materialize_shallow_and_full_flat,bootstrap_catalog_from_bcct}.py` — BTP dedup fix + helper extraction + mig 042 schema patch
- `app/static/css/app.css` — drift table + AI panel + job log styles
- `app/templates/base.html` — `head_extra` block for meta-refresh

## Johnson DB state (live)

```
BCCT:                  60,173 NK + 5,673 XK = 65,846 rows
Catalog (materials):   11,941 (8,660 nvl + 650 tp + 3,031 btp_sx via BOM fixup
                                + 416 nvl→btp_sx reclassified)
TK files:              2,351 TKN + 870 TKX = 3,221 (4 NK + 1 XK missing files,
                                                     accepted as legacy data)
BOM artifacts:         10,329 (106 TPs + 3,031 BTPs each with 3 shapes
                                — raw_graph + shallow + full_flat)
Material substitutes:  226,519 pairs (Johnson)
                       same_hs:   4,990
                       trigram: 103,215  (avg 0.62)
                       embedding: 118,314  (avg 0.95)
Embeddings:            11,925 / 11,925 (all populated, ~$0.018 cost)
```

## Architecture LOCKED this session (don't relitigate)

- **BTP raw_graph slices stored deduped, not per-parent-TP.** Same BTP under
  multiple parent TPs with identical edges = one artifact. `parent_artifact_id`
  is `None` on derived BTP slices; source TP recorded in `context.first_seen_via`.
  Re-deriving "which TPs use BTP-X" is a runtime query against `bom_edges`
  (memory `feedback_no_derived_in_source`).
- **Two parallel adapter name registries existed**: `bom_adapters._REGISTRY`
  (flat-rows path) vs `parse_raw_edges_with_fallback` returning its own names
  (`sap_indented_raw`, `growatt_factory_technical`). Bridged via `_LEGACY_ALIASES`
  so `run_post_ingest_hooks` resolves the same hooks regardless of upload path.
- **Auto-enable on first embed:** `embed_materials.py` flips
  `clients.substitute_rules.p5_embedding=true` when first run succeeds
  for that client. UX rule: if user populated vectors, they want them used.
- **Per-client embedding policy:** Johnson + Growatt have
  `auto_derive_shallow_from_raw='publish'` (was `draft_only`) so derived
  BTP raw_graphs ship as published — `materialize_shapes` then walks them.
- **Background jobs:** long-running ops (re-embed, refresh substitutes) spawn
  detached subprocess via `_job_runner.py` wrapper that updates
  `hub.background_jobs`. Web pages poll via meta-refresh while not terminal.
- **VNACCS hard cap = 50 lines/declaration.** Distribution cliff at 50 lines
  is normal, NOT export truncation. Memory `feedback_cliff_not_truncation`.

## Next Steps

1. **Push 5 commits to `origin`** — user discretion.
2. **Manual smoke through web UI** for the new flows so ops staff is
   familiar before sister-app cutover (TKX/TKN upload, catalog detail
   substitute panel + drift panel, AI panel buttons).
3. **Wire CO sister-app to read substitutes API** — `GET /api/v1/clients/
   {cid}/materials/{material_code}/substitutes`. Document in
   `.ai/sister-app-notes/`.
4. **A.4.2 backlog** — substitute XLSX bulk upload (P1 client_confirmed).
   Manual-add UI covers single-pair use. ~0.5 day.
5. **A.4.3 backlog** — smarter `goods_name` similarity (insignificant-diff
   folding via pg_trgm + embedding). Now unblocked since both are live.
6. **Nightly cron for embed + refresh** — currently only manual trigger.
   Add via `CronCreate` if/when reachable, or systemd timer on demo server.

## Blockers

None hard.

Soft (carry-over):
- Sister apps haven't adopted Phase 2 UoM schema (sister-app notes posted
  2026-05-12; consumer reads may produce different output until they update).
- 4 NK + 1 XK Johnson declarations have no per-TK file attached (legacy
  data; agency can supplement later — UI shows "Thiếu TK" badge).

## Notes for Next AI Session

**Read first (in order):**
1. This `STATUS.md`
2. `.ai/sessions/2026-05-11-johnson-onboarding-ship.md` (this session)
3. `.ai/features/2026-05-10-johnson-onboarding/brief.md` (full design doc)
4. Memory `feedback_no_pronouns_in_ui.md` (don't leak chat pronouns into
   templates / API errors)
5. Memory `feedback_dev_server_at_session_start.md` (start uvicorn :8754
   in background near start of every session)
6. Memory `feedback_cliff_not_truncation.md` (don't claim truncation from
   distribution shape; verify against primary source)

**UI smoke harnesses** — re-runnable:
- `scripts/smoke_declarations.py` — TKX/TKN list/filter/detail + upload
- `scripts/smoke_catalog_bcct_panel.py` — BCCT analysis panel (drift +
  no-drift)
- `scripts/smoke_substitutes.py` — substitute panel + JSON API check
- `/tmp/smoke_ui_bom_upload.py` — UI BOM upload flow (technical_raw,
  ack_uom_drift, confirm). Lives in /tmp; promote to scripts/ if needed.

**Auth fixture for smokes:** `admin@data-hub.local` / `admin123` (role=dev).

**OpenRouter API key** is in `hub.app_settings` keyed
`embedding.openrouter_api_key` (set by user via web UI). Don't echo
to logs.

**User preferences captured this session:**
- "test bằng UI đi" — drive features through Playwright smokes, capture
  screenshots, don't rely on tests alone.
- Vietnamese UI copy must be neutral/passive — no `ông/mày/tao/tôi`
  pronouns leaking from chat into templates or API errors. `bạn` OK.
- Bundle commits: 1 broad feature ship is fine when subcommits would
  share too many files. Used 3-commit pattern for Johnson onboarding
  ship + 2 fix commits after.
- `Cap review at 2 passes` (memory) — bundle minor fixes, defer non-blockers.
- Hard-DELETE acceptable for one-shot bug-noise cleanup if data is draft +
  derived + never published. Override of `project_bom_immutable_principle`.

**Demo server (tinsu)** — NOT updated this session. All 5 commits on `main`
local only. Per memory `reference_demo_server.md`, demo at
`http://100.84.189.87:8754`, clone `/home/tinsu/data-hub`, repo
`TinsuAI/data-hub`. Sister apps: BCQT runs on 8000.

**Migration state:** at mig 062 applied (63 total). 4 new this session.
