# Project Status

**Date:** 2026-06-04 — Fixed the declarations **download.zip "manifest-only" defect**
(reported as a CO Bearer-route bug). Real root cause was NOT route divergence: johnson-vn
landed in prod **metadata-only** — 3221 `customs_declaration_files` rows with no blob on
disk — and the shared builder silently swallowed the FileNotFoundError. Restored all 3221
blobs (sha256-matched) on **prod + nightly**, and hardened the builder to surface missing
blobs instead of dropping them. See `.ai/sessions/2026-06-04-declaration-blob-backfill.md`.
Prior 2026-06-01 work: **BOM product search by NVL/component code** (deployed, see
`.ai/sessions/2026-06-01-bom-search-nvl.md`).

## Current State

**Branch:** `main`, last commit `ce15574`. **Tests:** 1306 passed, 15 skipped
(`uv run pytest -q`). **Migrations:** 074 — no new migration (query/route/data only).

**Recent commits (pushed to `main`):**
- `ce15574` — chore(scripts): `backfill_declaration_blobs.py` (sha256-matched, dry-run
  default, idempotent ops tool).
- `db7ae88` — fix(declarations): surface registered-but-missing blobs (manifest count +
  `[THIẾU NỘI DUNG]` annotation + `FILE_THIEU_NOI_DUNG.txt` marker; shared builder so
  cookie≡Bearer). `tests/test_declarations_zip_missing_blob.py` (3 tests).
- `fd7a742` / `388c17f` / `57564a5` — BOM search by NVL/component (2026-06-01).

**Declaration blob backfill (2026-06-04, both environments):**
- Cause: johnson-vn was metadata-only; `backend.get(backend_key)` raised FileNotFoundError
  for all 3221 rows; growatt-vn was fine (4038/4038 present). Cookie route had the SAME
  symptom — not Bearer-specific (the report's premise was wrong).
- Prod `:8754`: ran `backfill_declaration_blobs.py --apply` in container, source = repo
  `data/source_inventory/johnson-vn/.../TKN|TKX/` (scp'd in). 3221 put, 0 failed.
- Nightly `:8764`: backend_keys identical to prod (DB snapshot), so stream-copied the blob
  dir container→container (`docker cp prod:- | docker cp - nightly:`). 3221 files.
- Verified both: resolve_ok=3221, missing=0, sha_mismatch=0; download.zip for
  107271918940 (import, 1.18MB .xls) + 308189816340 (export, 138KB .xls) now embed files.
- Blobs live in volume `data-hub_appfiles` — survive container recreate/redeploy.
- Deploy of the code fix: CI run `26932326139` green; (B) live on prod + nightly.

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
- 2026-06-04: declaration-blob backfill (prod + nightly) + download.zip missing-blob
  hardening (see Current State + session log).
- 2026-06-01: BOM search component matching.

## Next Steps
1. ~~Backfill johnson-vn declaration blobs + harden download.zip~~ **DONE 2026-06-04**
   (prod + nightly, 3221 each verified; commits `db7ae88` / `ce15574`). CO can re-run its
   container probe to confirm end-to-end. **Open question for next session:** why did
   johnson land metadata-only? (which ingest path registered rows but skipped `backend.put`
   — fix it so future ingests don't repeat the gap). growatt-vn was unaffected.
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
- **Screenshot creds:** `admin@data-hub.local` / `admin123` (per `scripts/screenshot.py`).
  growatt-vn is auto-seeded with full data; real shared NVL `005.0001100` is in 479 BOMs,
  `001.0033100` in 8 (good for a readable demo).
- **Use Windows `ssh.exe`** (`/mnt/c/Windows/System32/OpenSSH/ssh.exe`) for the box.
- Untracked pre-existing files (NOT this session, repo-hygiene later): `.ai/sessions/
  2026-05-15*`/`-25*`/`-28*`/`-29*`, `scripts/generate_training_input_scenarios.py`,
  `scripts/uom_drift_report.py`, `docs/training/`.
