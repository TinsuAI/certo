# Project Status

**Date:** 2026-06-07 — **BOM ingest follow-ups shipped + deployed to
prod.** Closed the four genuinely-open items in backlog section B:
adapter `detect()`/match_score ranking (B.1.5), multi-role warning at
upload (B.2.5), friendly parse-error UX on the BOM upload path (B.3),
and pytest regression coverage (B.2.7). Feature folder:
`.ai/features/2026-06-07-bom-ingest-followups/brief.md` (+ 3 screenshots).

## Current State

**Branch:** `main`, HEAD `f161f12` (pushed + **deployed to prod via CI** —
run 27068091275 all green: Docker build / Test / Deploy to tinsu).
**Tests:** 1389 passed, 16 skipped (`uv run pytest -q`). **Migrations:**
latest **076** (unchanged this session — no schema change).

**This session's commit (on `main`, live on prod):**
- `f161f12` — `feat(bom)`: match_score ranking + multi-role upload
  warning + friendly parse-error + 8 regression tests. No migration.

**What the BOM-ingest changes do:**
- `parse_with_fallback` now ranks adapters by an optional
  `detect(blob, root_code) -> float|None`. Positive scores tried first;
  abstainers (`None`) keep registration order → **zero regression when no
  adapter implements detect**. `detect` lives on `sap_indented_walk`
  (0.95) + `sap_exploded_levels` (0.9) so a Level-column file is no longer
  grabbed + flattened by the permissive `manual_flat`.
- `app/stores/bom_multirole.py::compute_multirole_warnings` — advisory
  (non-blocking) panel in `bom_preview.html` flagging upload component
  codes already exported in BCCT.
- `bom.py::_render_parse_error` → `clients/bom_upload_error.html`: the 5
  parse-error 400s on upload now render friendly HTML, not raw JSON.

## Recent Changes
- 2026-06-07: BOM ingest follow-ups (B.1.5 / B.2.5 / B.3 / B.2.7) —
  shipped + deployed. No schema change.
- 2026-06-06: declarations merged-PDF (`download.pdf`) + render button +
  CRITICAL auth-leak fix (strict mode + no-store + CO token wiring) +
  regression tests + required public smoke gate + CI LibreOffice fix.
  All deployed. Session log:
  `.ai/sessions/2026-06-06-declarations-pdf-and-auth-leak.md`.

## Next Steps
1. **Sister-app cutover — BCQT remainder.** CO strict-auth is done +
   verified. `bcqt-prod` service token minted (in
   `/home/tinsu/sister_tokens_2026-06-06.json`, scopes `hub:read`) but
   NOT wired. Decide **revoke vs keep**, then wire when BCQT work happens.
2. **C.1.a soak test** — BCCT `by-codes` under real CO load (EXPLAIN
   ANALYZE, pagination boundary, `include_material_identity` on large
   slices). Awaiting CO consumer ship.
3. **Repo hygiene** — untracked pre-existing files NOT from any feature,
   commit when convenient: `docs/training/`,
   `scripts/generate_training_input_scenarios.py`,
   `scripts/uom_drift_report.py`, and the older `.ai/sessions/2026-05-*`
   + `2026-06-06-declarations-*.md` logs.
4. **Remaining BOM-ingest backlog (lower value):** B.3 for BQD/Catalog
   upload paths; browser-level Playwright E2E (only pytest + static
   screenshots today); add `detect` to more adapters if a new ambiguous
   shape appears. B.1 "extract scripts into adapter classes" deemed not
   worth it (2026-05-29).

## Notes for Next AI Session
- **Backlog lags HEAD.** `.ai/BACKLOG.md` last full audit 2026-05-13;
  most of section B was already shipped before that. Trust git + code,
  ground-truth before claiming an item is open. BACKLOG section B updated
  this session to mark B.1.5/B.2.5/B.3 shipped.
- **Adapter detect contract:** optional `detect(self, blob, *, root_code)
  -> float|None`. Return a positive score ONLY on unambiguous structural
  markers (high precision); abstain (`None`) otherwise. Mechanism in
  `app/parsers/bom_adapters/__init__.py` (`_safe_detect`,
  `_ranked_adapters`). Adding `detect` to an adapter changes fallback
  ordering only for files multiple adapters can parse.
- **multirole warning** matches on `customs_code` only — shares the A.5
  paren-code blind spot (Growatt NB codes in goods_name parens are
  invisible). Acceptable for an advisory.
- **Screenshots** repro: `uv run python -m
  scripts.screenshot_bom_ingest_followups` (drives live dev server :8754,
  seeds + tears down client `bomshot-vn`).
- **CRITICAL prod config (intentionally NOT in git):** DB setting
  `hub.app_settings.api_auth_strict=true` is THE enforcement switch;
  prod `.env` has `DATA_HUB_API_AUTH_DISABLED=0`. NEVER set it to 1 in
  prod. CO service token at `/var/lib/barry-co/runtime/data-hub-link.json`
  (docker volume `co_appdata`). Minted tokens at
  `/home/tinsu/sister_tokens_2026-06-06.json` (chmod 600 on box).
- **Box (`100.84.189.87` = tinsu-online-server):** prod DH `:8754` + CO
  `:8755` = Docker (`data-hub-app-1` / `co-app-1`). Edge = Cloudflare
  tunnel, `ttdatahub.tinsu.ai`. CI deploy = self-hosted runner on the box
  (`git reset --hard` + `docker compose up -d --build`). **Push to `main`
  = prod deploy.** `.env` gitignored so deploys don't clobber prod config.
- **Cloudflare caches `.pdf`/`.zip` by extension** unless origin sends
  `no-store` (middleware `_no_store_sensitive` in `app/main.py` covers
  `/v1/hub/*` + attachment downloads).
- **Regression guard:** `tests/test_v1_hub_auth_coverage.py` fails if a
  new `/v1/hub` route lacks auth. Deploy smoke required
  (`scripts/smoke_public_auth.py` — anon→401).
- **Admin user_id** `u_31151f0497094109` (admin@data-hub.local, role=dev)
  on dev+prod.
- Dev server: `--workers 1 --reload` on `:8754` (was already running this
  session; pick it up or restart with `--workers 4` for concurrency tests).
