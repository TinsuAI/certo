# Project Status

**Date:** 2026-05-27 (PM) — BOM flat-view UX additions shipped + demo synced. Local + demo both at `5fefa4a`.

## Current State

**Branch:** `main` at `5fefa4a`. **In sync with `origin/main` and demo box.**

Recent commits (this session):
- `5fefa4a` — chore(bom): move Nguồn column to last position
- `9affecb` — feat(bom): NK/BOM-only column + Excel export on flat artifact page

Prior unshipped → now shipped to demo:
- `869e0ea` — docs(handoff): BOM stale-UX rebuild session
- `5cdf7fe` — feat(bom): cluster needs-action page replaces /bom/stale
- `99abbec` — feat(catalog): fill placeholder name from BCCT on conflict
- `637046e` — feat(bom): conditional staleness model + state column (migs 067-071)
- `a331c74` — chore(ui): hide notification bell from navbar

**Tests:** 254 BOM-related tests pass (full suite untouched this session, no regressions expected — diffs are 2 files only).

**Migrations:** at mig **071** (demo also at 071 after deploy + on-startup migrator).

**Working tree:** clean of code drift relative to HEAD. Untracked items unchanged from prior sessions (training scripts, demo-company-feed PNGs).

**Dev server:** `:8754` running (`nohup … --workers 4`); healthz HTTP 200.

**Demo box (`100.84.189.87:8754`):** at `5fefa4a`, healthz 200, johnson + growatt verified post-deploy. Migrations 067–071 ran on demo and backfilled `state` column.

**Demo DB state distribution (post-deploy):**
```
johnson-vn  full_flat  3400 clean / 52 needs_input  (98.5%)
johnson-vn  shallow    3128 clean / 41 needs_input
johnson-vn  raw_graph  3051 clean / 86 uom_drift
johnson-vn  manual_flat 517 clean / 0 needs_input
growatt-vn  full_flat  197 clean / 0 needs_input  (100%)
growatt-vn  shallow    197 clean / 0 needs_input
growatt-vn  raw_graph  198 clean / 0 uom_drift
growatt-vn  manual_flat 14 clean / 1 needs_input  (TEST_TP_DRIFT fixture)
```

Note: demo `needs_input` counts (52+41+86 johnson) > local `(11 derived + 9 raw)` reported in last STATUS — same data, fresh backfill on demo without iterative override-cleanup that happened locally. Material codes flagged on demo: top `1000202688` (42 ff), known `1000469803` (10 ff, mixed EA/KG, open item), 12 others.

## Recent Changes (this session)

### 1. NK / BOM-only column on flat BOM (commit `9affecb`)

In the artifact detail page (`/clients/{cid}/bom/artifact/{aid}`), when
the artifact stores rows (manual_flat / shallow / full_flat — not raw_graph),
the rows table now shows a **Nguồn** column with a badge:
- `NK` — material_code has at least one BCCT row with `direction='import'` for this client.
- `BOM-only` — code does not appear in any import declaration.

Lookup batched once per request via existing `make_bcct_import_lookup(client_id)`
(distinct customs_code preload, O(1) per row).

### 2. Excel export button (same commit, plus `5fefa4a`)

New route `GET /clients/{cid}/bom/artifact/{aid}/export.xlsx`:
- 200 → openpyxl workbook, sheet `BOM_<product_code>` (capped 31 chars),
  filename `BOM_<product>_v<artifact_no>.xlsx`.
- 400 → if artifact is raw_graph (edges-only, no flat rows).
- Columns: STT, Mã NVL, Định mức / đơn vị, ĐVT, Mã BOM, Đợt, Nguồn
  (Nguồn at far right — repositioned per user feedback in `5fefa4a`).
- Button "⬇ Xuất Excel" rendered next to "← artifacts" link, only when rows exist.

### 3. Deploy to demo

- Pushed `a331c74..5fefa4a` to `origin/main`.
- ssh.exe → `git pull --ff-only && docker compose up -d --build`.
- App auto-ran migrations 067–071. Backfill round 1 + 2 completed.
- Verified post-deploy via curl with session cookie (cookie is `Secure` so
  curl `-c/-b` won't auto-store over HTTP; copied set-cookie value manually).

### 4. Demo data audit (no code changes)

- **Johnson full_flat:** 3137 raw products → 3452 ff artifacts, 100% coverage.
  3400/3452 clean (98.5%). 52 needs_input all from UoM drift on ~14 material
  codes (top: 1000202688 / 1000469803). 0 duplicate rows (dedup fix `7552c64` holding).
- **Growatt full_flat:** 197/197 active, all clean. 1 raw missing ff: `B710.0071401`
  (raw uploaded 2026-05-05 with 83 edges, never flattened — gap to address).
- **Growatt UoM:** 1 real drift only — `033.0024500` (catalog PIECES vs BCCT 15 SETS / 1 PIECES,
  no override, code not in BOM so no artifact flag). 5 alias-resolved (ST/PCS↔PIECES, OK).
  6 materials with NULL uom (3 fixtures + 3 real: PV00.0048500, PV01.0117600 TPs, 001.0031100).

## Next Steps

1. **Flatten Growatt `B710.0071401`** — the one raw artifact missing a ff. Run
   the flatten endpoint or rerun the technical_flatten upload for this product.
2. **`033.0024500` override** — agency to confirm `1 SET = ? PIECES`; add row to
   `hub.client_uom_overrides` for growatt-vn. Mirrors Johnson `1000469803` workflow.
3. **Johnson UoM drift cleanup** — confirm/add overrides for the 14 codes still
   flagged on demo (top: 1000202688 with 42 artifacts; rest ≤5 each). Once
   override added, `reconcile_for_material()` clears flag in-band.
4. **Fill missing uom in Growatt catalog** for the 3 real codes (PV00.0048500,
   PV01.0117600, 001.0031100) — fixtures (DEMO-*, VAI) can stay null.
5. **(Stretch)** Extend drift gate to flag standalone NVL not yet in BOM —
   `033.0024500` slipped through because it has no BOM artifact. Currently the
   flag is artifact-level only; consider material-level surface for catalog-page UI.

## Notes for Next AI Session

- **Demo verification recipe** (the cookie is `Secure` over plain HTTP — curl needs the workaround):
  ```bash
  SESS=$(curl -sv -d "email=admin@data-hub.local" -d "password=$DEMO_PASS" http://100.84.189.87:8754/login 2>&1 | grep "set-cookie" | sed -n 's/.*data_hub_session=\([^;]*\).*/\1/p')
  curl -s -H "Cookie: data_hub_session=$SESS" http://100.84.189.87:8754/...
  ```
  Demo seed password lives in `~/data-hub/.env` on the server (chmod 600, do
  not paste in chat). Read via `ssh.exe tinsu@100.84.189.87 "grep DATA_HUB_SEED_PASSWORD ~/data-hub/.env"`.
- **Demo logins from Playwright/python work fine** — `urllib` + cookie jar handles redirects.
- The Secure-cookie-over-plain-HTTP looks wrong but is existing behaviour — flagged
  but not fixing this session.
- Earlier-session `2026-05-27-bom-stale-rebuild.md` describes the migs 067-071
  staleness model in depth — read first if touching `state` / `is_stale` /
  `has_uom_drift` triggers.
- Per `feedback_use_windows_ssh.md`, always use `/mnt/c/Windows/System32/OpenSSH/ssh.exe`
  for remote ops (WSL ssh broken).
