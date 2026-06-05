# Project Status

**Date:** 2026-06-06 — **BOM auto-detect tree-flat fix + honest signals +
self-service retraction, all shipped to prod.** `profile=auto` was storing
single-rooted explosion trees (`sap_indented_walk`/`multi_sheet_per_root`) as
flat `manual_flat`/`not_applicable` — no `raw_graph`, no shallow/full_flat
derived, yet `parse_status='done'` (the MPL0100-39 bug). Fixed routing; added a
preview destination banner + honest post-ingest toast (warns when a technical
upload produced NO flat shapes); added self-service tombstone of a BOM version
(cascades to derived shapes) + delete of failed uploads — so staff no longer
need dev SQL to clean bad data. Full feature:
`.ai/features/2026-06-05-bom-auto-tree-flat-fix/` (brief + 9 screenshots).

## Current State

**Branch:** `main`, last commit `be0da06` (code `7886efa`; all pushed +
**deployed to prod**). **Tests:** 1346 passed, 15 skipped (`uv run pytest -q`).
**Migrations:** none new (latest is **075**, `hub.client_column_aliases`).

**Both new write capabilities verified on the LIVE prod server** (httpx →
`127.0.0.1:8754` in-container, throwaway clients, self-cleaned): tombstone
(empty-reason→400, cascade raw+derived→0 active + 2 audit rows, real product
untouched) + upload delete (error→row+blob gone, done→400 kept, unknown→404).
ALL PASS.

**This session's commits (pushed to `main`, live on prod):**
- `7886efa` — self-service retract BOM version (cascade to derived shapes,
  reason+audit) + delete error/rejected uploads.
- `1105993` — flow-signal screenshots (7) + feature brief.
- `0bd85d2` — preview destination banner + honest upload toast.
- `90ba345` — auto-detect tree adapters land as raw_graph, not flat (core fix).

**Deploy (2026-06-06, prod `ttdatahub.tinsu.ai`):** 3 sequential
`git pull` + `docker compose up -d --build` (→ `90ba345` → `0bd85d2` →
`7886efa`). Verified live each time: healthz 200, public 200, new routes
registered (`/bom/artifact/{id}/tombstone`, `/uploads/{id}/delete`).

**Prod data remediation (johnson-vn):** tombstoned 2 stuck artifacts
(`MPL0100-39`, `MFW0537-39`); re-ingested via the fixed flow. `MPL0100-39` now
has raw + shallow + full_flat (published). `MFW0537-39` already had good shapes
(the 2026-06-04 re-upload was a byte-identical stray `manual_flat`); re-ingest
duplicates were tombstoned. **Gotcha found:** `create_raw_artifact` dedup keys on
`actor`, so an `erp_pipeline` raw and an `agency_staff` raw with identical edges
do NOT dedup (made a duplicate set on re-ingest). See memory
`project_bom_auto_tree_flat_bug`.

**LLM endpoint:** sgnai `codex-lb-demo.sgnai.dev` was **down** (Cloudflare 1033
tunnel error). Swapped `hub.app_settings` LLM config (dev + prod) to **OpenRouter
`openai/gpt-4o-mini`** (key borrowed from `growatt-item-master/.env`).
**Temporary** — restore sgnai when back, or get a dedicated key. Old config
backed up to gitignored `data/files/.{,prod_}llm_settings_backup.*`.

**Johnson "diff loạn" root cause:** a human manually mis-confirmed a cached
mapping that swapped the two đơn-giá columns; the preview correctly blocked the
corrupting re-ingest. Hotfixed the cache (dev); auto-map now prevents recurrence.

**Dev server:** default now `--workers 1 --reload` on `:8754` (user pref 2026-06-04;
auto-reload, no manual restart). Use `--workers 4` only to test real concurrency. Restart
gotcha: workers show as `python3`, so kill by port (`lsof -ti:8754 | xargs kill -9`).

**Box (`100.84.189.87` = `tinsu-online-server`):** prod DH `:8754` + CO `:8755` run as
**Docker** (`data-hub-app-1` / `co-app-1`), NOT systemd (repo's `deploy/systemd/*` is
stale). Nightly/demo stack is a separate compose project (`nightly-*`, `:8764`/`:8765`,
repo `tinsu-deploy`); CI auto-refreshes on merge to main. CO↔DH now talk over external
docker net `tinsu-shared` (DH alias `data-hub-app:8754`) for both data + JWKS; issuer +
browser SSO redirect stay public `https://ttdatahub.tinsu.ai`. **That networking feature
is fully closed (verified both sides 2026-06-01).**

## Recent Changes
- 2026-06-06: BOM `profile=auto` tree-flat fix (tree adapters → raw_graph →
  materialize, not flat manual_flat) + preview destination banner + honest
  post-ingest toast + self-service tombstone BOM version / delete failed uploads;
  prod data remediated (MPL0100-39 / MFW0537-39); **deployed to prod**.
- 2026-06-05: BCCT mapping-flow overhaul (auto-map, no-header positional + inference,
  per-client column aliases `mig 075`, LLM prompt, anomaly→advisory) + BOM `depth=full`
  + LLM→OpenRouter; **deployed to prod, real-data smoke PASS**.
- 2026-06-04: declaration-blob backfill (prod + nightly) + download.zip missing-blob
  hardening (see session log).
- 2026-06-01: BOM search component matching.

## Next Steps
0. **LLM is on a TEMPORARY OpenRouter key** (borrowed from `growatt-item-master/.env`).
   Restore sgnai `codex-lb-demo.sgnai.dev` when its Cloudflare tunnel is back, OR provision
   a dedicated data-hub OpenRouter key. Old config in `data/files/.prod_llm_settings_backup.tsv`.
0b. No-header value inference can't resolve bare-digit SAP customs codes (johnson `1000…`) —
    left for the operator. Possible follow-on: cross-column heuristic (customs_code = prefix
    of goods_name before `#&`) or a saved positional template per client.
1. ~~Backfill johnson-vn declaration blobs + harden download.zip~~ **DONE 2026-06-04**
   (prod + nightly, 3221 each verified; commits `db7ae88` / `ce15574`). CO can re-run its
   container probe to confirm end-to-end. ~~**Open question:** why did johnson land
   metadata-only?~~ **ROOT-CAUSED 2026-06-04 (no code change needed):** NOT an ingest path
   skipping `backend.put` — both clients used `import_declaration_archive.py` which always
   puts. The cause was the `DATA_HUB_FILES_DIR`/`DATA_HUB_FILES_ROOT` env-name mismatch
   (fixed `b19c88e` 2026-05-28): blobs landed on the ephemeral container layer
   `/app/data/files`, not the `appfiles` volume. Johnson (uploaded 2026-05-11) was wiped by
   a CI `up -d --build` recreate during the 17-day window before the fix; growatt (uploaded
   2026-05-28, same day as the fix) was rescued via `cp -a` within 8h. Pure timing, same
   ingest path. Bug already fixed; data already restored. **Latent gap left open (not what
   hit johnson, same failure class):** `app/data_promotion.py` export/import has no
   referential-integrity check between SQL rows and the blob set — a rows-only bundle
   imported onto a healthy target would `_purge_client_files` then move nothing → silent
   metadata-only. User deferred fixing it for now.
2. ~~Commit + deploy the BOM search change~~ **DONE 2026-06-01** (commits `57564a5` /
   `388c17f`, live on `:8754` + `:8764`). Back-compatible: `q` on `/v1/hub/products` is
   optional; CO could adopt it for component reverse-lookup but needs no change.
2. Decide whether to commit the older uncommitted `AGENTS.md` worker-note change (from
   the prior session — may already be in `e467a66`; verify).
3. **C.2 strict cutover (prod)** — still open from 2026-05-30: mint CO prod service token,
   fix CO `DATA_HUB_API_TOKEN`→`DATA_HUB_SERVICE_TOKEN` env-key bug, flip
   `api_auth_strict=true`. Brief: `.ai/features/2026-05-29-api-auth-strict-cutover/brief.md`.
4. Backlog (C.1 sister-app cutover, D.1 aggregate-data history, A.3/A.4.2, B.1, B.5) —
   `.ai/BACKLOG.md`. Possible follow-on: fuzzy/material-name BOM search (needs pg_trgm GIN
   on BOM tables — deferred this session).

## Notes for Next AI Session
- **BOM search internals:** the `where_q` string is duplicated in both `list_` and
  `count_products_with_bom` in `app/stores/bom.py` — keep them in sync or pagination
  breaks. Component codes live in `hub.bom_artifact_rows.material_code` (flat shapes) and
  `hub.bom_edges.child_code` (raw graph); both already indexed.
- **`bom_artifacts` insert constraint:** `flatten_strategy` ∈ {`manual_flat_as_provided`,
  `technical_exploded`, `purchased_btp_as_leaf`, `self_produced_btp_exploded`,
  `mixed_confirmed`, `no_strategy`}; `flatten_status` ∈ {`flattened`, `non_flattened`,
  `not_applicable`}. Useful when hand-building test fixtures.
- **BCCT mapping flow:** `try_auto_map` (`_mapping_flow.py`) skips the mapping page when
  rigid match resolves all required fields with no ambiguity. No-header = picker value `0`
  → `positional_override` in `parse_bcct_workbook`. Anomaly check (`bcct_validate.py`) is
  **ADVISORY** (not a gate); covers ONLY VND↔nguyên-tệ price/value inversion;
  `has_blocking_anomaly()` still exists but is no longer used for gating.
- **Admin user_id is `u_31151f0497094109`** (admin@data-hub.local) on BOTH dev and prod —
  `scripts/smoke_bcct_flows.py` hardcodes it. Run smoke in prod container with
  `docker exec -e PYTHONPATH=/app data-hub-app-1 python scripts/smoke_bcct_flows.py`.
- **Remote `psql` over ssh:** bash eats `$$` (→ PID); pipe SQL via a quoted heredoc to
  `psql` stdin, not `-c "...$$..."`.
- **Screenshot creds:** `admin@data-hub.local` / `admin123` (per `scripts/screenshot.py`).
  `scripts/screenshot_bcct_mapping_flow.py` uses a session cookie instead + real johnson-vn
  rows; uploads via httpx then `goto` (browser form-submit didn't navigate reliably).
- **Use Windows `ssh.exe`** (`/mnt/c/Windows/System32/OpenSSH/ssh.exe`) for the box.
- Untracked pre-existing files (NOT this session, repo-hygiene later): `.ai/sessions/
  2026-05-15*`/`-25*`/`-28*`/`-29*`, `scripts/generate_training_input_scenarios.py`,
  `scripts/uom_drift_report.py`, `docs/training/`.
