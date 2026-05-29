# Project Status

## Current State
- Branch `main` at `922d6bb`, **8 commits ahead** of prior STATUS snapshot
  (`ad25ffb`). All pushed to `tinsu/main`; demo deployed at
  `https://barry-co.tinsu.ai` (pull + `docker compose up -d --build app`).
- Local CO dev at `http://127.0.0.1:8001` (`npm run co:serve` `--reload`);
  Data Hub at `:8754`. Both `/healthz` OK.
- Local suite **374 passed + 7 skipped**.
- Johnson `tru lui CO Johnson.28.05.26.xlsm` ingested both local and prod
  (25,717 unique stock-adjustment rows; batch hash `batch_0ba5ff092ef3bc99`).

## Recent Changes (this session — 8 commits, oldest → newest)

| Group | Commit | Topic |
|---|---|---|
| Housekeeping | `1b034a8` | Commit Phase-3 audits + handoff session logs |
|  | `f161f7e` | Track 4 perf/verify scripts; drop 5 superseded one-offs |
|  | `38cb100` | Drop unused acquire/release_client_lock helpers |
| Bảng kê fix | `acb201e` | Fix EUR.1 always picking PSR template — operator's `criteria_override` (LVC/CTH/…) now wins for any form |
| Export gate | `897c9a5` | `/export-dossier-zip` requires case `completed`; UI swaps primary/secondary on Review tab |
| Propose-BOM fix | `a52f3c6` | Rename `norm_per_unit` → `qty_per_unit` at the Data Hub boundary (DH was auto-rejecting every proposal with `qty_delta_exceeds_tolerance`) |
| Source-view strip | `2508ae7` | Catalog (NVL+TP), BOM, BCCT pages render summary + "Mở trên Data Hub" link in DH mode; skip `source_workspace` full pagination |
|  | `922d6bb` | Same lean context for `/config` — Johnson `/config` page no longer paginates 65k BCCT rows |

### Data ingest (CO tồn CO snapshot)
- File: `/mnt/p/Downloads/tru lui CO Johnson.28.05.26.xlsm` (29/05, 41M).
- `scripts/convert_co_stock.py` (sheet NK2): 62,531 rows → 25,717 unique;
  0 dropped, 36,814 skipped (Đã_xuất = 0).
- Local POST `/clients/johnson-vn/co-stock/import`: 25,717 parsed,
  2,662 inserted + 23,055 updated, 3,027 events.
- Prod POST `https://barry-co.tinsu.ai/clients/johnson-vn/co-stock/import`:
  25,717 parsed, 25,717 inserted (fresh slate), 25,717 events.
- Same `batch_id` both sides → idempotent re-run is a no-op.

### Auth audit (informational, no code change)
- Browser SSO is prod-grade: CO `CO_AUTH_REQUIRED=1`, JWT issued by DH and
  verified via JWKS, `DATA_HUB_SSO_ALLOWED_REDIRECT_ORIGINS` whitelist set.
- Backend CO→DH API channel **is still dev-mode**:
  - DH env `DATA_HUB_API_AUTH_DISABLED=1` + `hub.app_settings.api_auth_strict=false`.
  - CO env `DATA_HUB_API_TOKEN=` (empty).
  - Effect: anyone reachable to `ttdatahub.tinsu.ai/v1/hub/*` can call API
    without any bearer.
- User chose to defer fix (only one company using; low risk for now).
  Cutover steps captured for later:
  1. DH: `update hub.app_settings set value='true' where key='api_auth_strict';`
     (precedence wins over env flag; no need to unset DEV env).
  2. DH: mint service token scope `hub:read` (+ `bom:propose`, `hub:write` as
     needed).
  3. CO: set `DATA_HUB_API_TOKEN=<token>` in container env + restart.
  4. Verify: `curl /v1/hub/...` without bearer → 401; with bearer → 200.

## Next Steps

1. **`/co-case/{id}/origin` perf** (HIGH-ish, cold ~2.7s vs warm 1s):
   `preload_co_case_origin_context` warms `source_context` only, not
   `bom_service.workspace`. Add bom-workspace eager warm in preload so the
   first /origin click is sub-second after detail open. Cache infra already
   exists (`_DATA_HUB_BOM_WORKSPACE_CACHE`, 60s TTL).
2. **Backfill `data_hub_target_url=""`** for `/config` template safety —
   currently the template doesn't reference it, but if any future config-tab
   template adds a "Mở DH" button it would render an empty href. Either
   add a guard in the template or stop emitting the field for `dh_path=""`.
3. **Lock cleanup** of stale carry-over items (no progress this session):
   - **Claim ID stability** (HIGH carry-over) — `claim_id` derives from
     `material_index`, breaks on BOM reorder.
   - Customs FX historical backfill.
   - Origin calculation lock TTL (60 min).
   - Seed missing CO forms (D / E / AK / AANZ / AJ / RCEP / UKVFTA / VK /
     VC / VJ).
   - `can_view_client` short→long client_id URL fallback.
   - HS↔form coherence + criteria token validation (MED).
4. **Prod CO↔DH backend auth cutover** when ready (steps above).
5. **`prepare_case_origin_products`** kept on purpose (live test coverage of
   4 invariants — see prior STATUS comment). Revisit if those invariants get
   covered by other tests.

## Notes for Next AI Session

- **Memory** at `/home/vp/.claude/projects/-home-vp-workspace-client-barry-CO/memory/`
  has 5 entries. Read `MEMORY.md` first.
- **Test on local by default.** Only touch prod when explicitly told.
- **Demo URLs** (in memory, not in repo): `barry-co.tinsu.ai`,
  `ttdatahub.tinsu.ai`.
- **Prod test account**: `claude-check@local` / `claude-temp-2026`. URLs MUST
  use `-vn` long form on prod until `can_view_client` is fixed.
- **Data Hub local restart**: DH worker at `:8754` runs with `--workers 4` and
  no `--reload`. If DH schema or code changes, user must restart it before
  CO sees the change.
- **CO local dev** writes profile to `/tmp/barry-co-8001.log`.
- **Prod deploy path**: SSH `tinsu`, `cd /home/tinsu/co && git pull && docker
  compose up -d --build app`. Image rebuilds from local sources (no
  container registry). Healthcheck on `/healthz`.
- **Lean-context pattern** (introduced this session for catalog/bom/bcct/
  config): when CO doesn't need the heavy `source_workspace` pagination,
  use `_data_hub_overview_context(client_id, active, dh_path=...)` which
  pulls only `source_summary` (counts + version metadata + client_config)
  and the data_hub_base_url. Falls through to `client_context` when not
  in DH mode OR when test shims don't expose `source_summary`. Templates
  branch on `source_backend == "data-hub"` to render summary + DH link
  instead of full tables.
- **EUR.1 bảng kê** quirk: form code EUR.1 used to short-circuit to
  `{"EUR1"}` (rewritten to PSR template). Now `criteria_override`
  (LVC/CTH/RVC/CTSH/PSR) wins; EUR1/PSR fallback only fires when no
  criterion matches. Tests in `tests/test_hq_sheet_codes.py`.
- **Dossier ZIP gate**: `/export-dossier-zip` now hard-requires
  `co_case_is_completed(case)`. Per-product `/export-bang-ke` (WIP Excel)
  still works on open cases. The Review-tab UX:
  - case open → PRIMARY = "Đóng hồ sơ", SECONDARY disabled "Xuất .zip"
    with per-state hint.
  - case closed → PRIMARY = "Xuất .zip", SECONDARY = "Mở lại hồ sơ".
- **DH BOM proposal row contract**: CO internally stores operator overrides
  as `norm_per_unit` ("định mức"); `build_bom_proposal_rows` translates to
  `qty_per_unit` at the DH boundary. Don't undo this rename — DH's
  `_auto_evaluate` and `create_artifact` both key on `qty_per_unit`.
