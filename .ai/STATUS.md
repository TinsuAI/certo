# Project Status

**Date:** 2026-05-05 (handoff after BOM v3 redesign + local re-ingest)

## Current State

**Latest:** BOM v3 architecture (3 shapes + resolution profiles) designed
across 3 critic rounds; **local DB wiped + re-ingested with v3 schema**.
Demo at ttdatahub.tinsu.ai still on OLD schema — redeploy deferred.

- **Demo URL**: https://ttdatahub.tinsu.ai (Cloudflare tunnel →
  Compose on `tinsu` VPS). **Still on old schema/data — needs redeploy.**
- **Login**: `admin@data-hub.local` / `sS3EZgj9lf5b741`.
- **Repo HEAD (uncommitted v3 work)**: migration 030, bom_shape helper,
  6 new scripts, BACKLOG + 3 memory files. **Not committed yet.**
- **Tests local**: 471 passed, 1 fail, 15 skipped. Failure is real-data
  dependent (`tests/test_co_columns.py` references DKE BCCT not
  re-ingested). NOT introduced by code changes.
- **Local DB v3 state**: 5 production clients (growatt-vn, johnson-vn,
  dke, do-thanh, demo-precision); 446 materials (278 nvl + 148 btp_sx
  + 20 tp); 285 manual_flat + 139 technical_raw BOMs across 4 batches
  with distinct `bom_variant_id`s; 47k edges; 3.2k BCCT rows; 3.1k
  BQD mappings; bom_resolution_profiles table empty (Phase 3+4 use).
- **Backups**: `/tmp/data_hub_pre_v3/{local,docker}.sql` + files tarball.

**Earlier this date — v3 design + investigation:**

- Audited Growatt SD/SA: v1 manual_flat = v2 technical_raw rolled to
  BTP boundary (32/41 products match 100%).
- 3 critic rounds redesigned BOM handling: drop variant
  pre-materialization, add resolver-on-demand + profiles, distinct
  `bom_variant_id` per supplier batch. Memory locked: BOMs are
  immutable in DB (append-only + tombstone, never DELETE).
- Phase A cutover (~5 min downtime local): drop+recreate+migrate.
- Phase B re-ingest: 4 raw batches via batch script, curated XLSX
  via direct ingest (smoke_real_uploads blocked by mapping-flow
  UI gate), bootstrap BTP + catalog-from-BCCT scripts.

**Still in scope from prior session — `data_promotion` feature**
(commit `ea34c9d`):

- `app/data_promotion.py` — per-client export/import library
- `scripts/export_client.py`, `scripts/onboard_client.py --from-export`,
  `scripts/smoke_roundtrip_client.py`
- `app/seed_master_data.py` — `DATA_HUB_REFERENCE_DATA_MODE` env flag
- 22 unit tests + 1 real-data round-trip on growatt-vn passed

**New this session — `data_promotion` feature** (commit `ea34c9d`):

- `app/data_promotion.py` — per-client export/import library
- `scripts/export_client.py` — CLI to bundle one client → tar.gz
- `scripts/onboard_client.py --from-export` — replace-mode import
- `scripts/smoke_roundtrip_client.py` — real-data smoke (mandatory
  before releases that touch data_promotion)
- `app/seed_master_data.py` — `DATA_HUB_REFERENCE_DATA_MODE` env
  flag (`oneshot` / `upsert` / `migration_only`)
- 22 unit tests + 1 real-data round-trip on growatt-vn passed

**`--from-excel` is stubbed** (NotImplementedError); deferred to a
follow-up session — needs to drive `app/parsers/{bcct,materials,bom}.py`
through the same flow as the UI upload route.

## Next Steps

In priority order:

0. **Demo redeploy to tinsu (CRITICAL).** Local v3 verified; demo on
   OLD schema. Steps: ssh.exe to tinsu, git pull (after committing v3
   work), docker compose down + build, run migrations or wipe+migrate,
   run setup_clients_for_reingest.py + ingest_technical_raw_batch.py
   for 4 batches + ingest_curated_xlsx_direct.py + bootstrap scripts.
   Estimated 60-90 min downtime per critic R3 finding 5. Pre-announce.
   Source files for batch ingest: `~/workspace/client/barry-CO-data/`
   needs to be present on tinsu, OR symlink/scp into place first.
0a. **Commit the v3 work first** before deploying. Current uncommitted:
   migration 030, bom_shape helper, data_promotion.py update, 6 new
   scripts, .ai/BACKLOG.md "aggregate-data git-history" item, .ai/
   sessions/2026-05-05-bom-v3-redesign-and-reingest.md.

1. **Set `DATA_HUB_REFERENCE_DATA_MODE=upsert` on tinsu Compose**
   so YAML edits in `data/seeds/*.yaml` propagate to demo on the
   next deploy. Add to `docker-compose.yml` env passthrough +
   `.env.example`. Currently unset → defaults to `oneshot` (the
   feature exists but isn't wired into the demo deploy yet).
2. **Sister-repo adoption of standards** (carry-over from prior
   handoff; still not done). CO and BCQT need
   `docs/release-engineering.md`, `.standards-version v2026.05.05`,
   AGENTS.md "Standards" section.
3. **`--from-excel` onboarding** (`scripts/onboard_client.py`).
   Highest-risk slice in the data-promotion feature; the unit-test
   strategy needs real-data fixtures from
   `.ai/features/2026-05-03-source-data-inventory/`.
4. **`docs/release-engineering.md`** — update §4 (mode-aware C2)
   and add new §8 (promotion runbook). Brief commits to this; not
   done.
5. **Mark `scripts/feed_demo_company.py` deprecated** in its
   docstring (Playwright UI driver is superseded by the future
   `--from-excel` CLI). Keep the file for archive references.
6. **Open product items** from prior handoff:
   - **P1**: `GET /version` + `VERSION`/`GIT_SHA` build args.
   - **P2**: bump `pyproject.toml` 0.1.0 → 0.2.0; cut first tag.
   - **P3**: GHCR push when 2nd deploy host appears.
   - **P5/P6**: Tier-2 backup uplift before first paying customer.
   - **P7**: branch protection on `main` (needs Pro plan).

## Notes for Next AI Session

- **Real-data smoke is the release ritual for `data_promotion`.**
  Run `uv run python scripts/smoke_roundtrip_client.py growatt-vn`
  before tagging any release that touches the feature. The 5-round
  review history (in `.ai/features/2026-05-04-data-promotion/brief.md`)
  shows that 2 critical bugs (`file_uploads` SET-NULL FK,
  `bcct_row_history` trigger accumulation) were caught ONLY by
  real-data --commit, not by 4 prior code-review rounds.
- **Lesson:** for any feature that touches schema with triggers /
  asymmetric FKs, real-data smoke catches what unit tests miss.
  Don't trust review rounds alone — run the actual commit.
- **Don't remove** these `data_promotion.py` features — each catches
  a specific real bug:
  - `pre_delete=True` on `file_uploads` (catches SET-NULL leftover)
  - `null_columns` on parser_mappings/client_config/bom_flatten_decisions
    (catches user-FK leak)
  - `AUDIT_TABLES_TO_PURGE_ON_IMPORT` (catches trigger accumulation)
  - generated-column filter in `_column_info` (catches `bcct_rows.year`)
  - `_CLIENT_ID_RE` validator (catches `client_id=".."` traversal)
  - `_audit_allow_list` warning (alerts when schema evolves)
  - `pre_delete` and audit-purge BOTH need to stay; they cover
    different cascade behaviors.
- **Local docker stack** is still running on port 8754 on the dev
  box (user keeps it up). If next session needs `uvicorn` for dev:
  `cd ~/workspace/client/data-hub && docker compose down` first.
- **Demo on tinsu was NOT touched this session** — all work was
  local dev side. Demo's pgdata + appfiles untouched.
- **Carry-over loose end**: `deploy/runbook.md` references memory
  `feedback_use_python_heredoc.md` that doesn't exist. Either
  create or remove the reference.
- **SSH transport**: WSL native ssh is broken; use
  `/mnt/c/Windows/System32/OpenSSH/ssh.exe` and `scp.exe`. Memory:
  `feedback_use_windows_ssh.md`.
- **Drive remote ops, don't hand off**: user wants AI to execute
  deploy / scp / push end-to-end. Memory:
  `feedback_drive_ops_dont_handoff.md`.
- **Server access**: `tinsu@100.84.189.87` (Tailscale). No
  passwordless sudo. Repo at `/home/tinsu/data-hub`.
- **Backup baseline**: daily 02:30 user-cron pg_dump on tinsu →
  `/home/tinsu/backups/data-hub/*.dump`. Last verified ok.
- **`appfiles` volume on tinsu still NOT backed up** — flagged in
  data-promotion brief Risks. Tier-1.5 uplift candidate before
  first paying customer.
