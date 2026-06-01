# Project Status

**Date:** 2026-06-01 — Extended **BOM product search** to match NVL/component codes,
not just the finished-product code. Single `q` box now does reverse lookup ("which TPs
use this NVL"). TDD, full suite green, UI screenshot captured. **Uncommitted — awaiting
review.** See `.ai/sessions/2026-06-01-bom-search-nvl.md`.

## Current State

**Branch:** `main`, last commit `5beab13` (handoff doc). **Tests:** 1303 passed, 15
skipped (`uv run pytest -q`). **Migrations:** 074 — no new migration this session
(query/route/template only).

**Uncommitted (this session — BOM search):**
- `app/stores/bom.py` — `list_products_with_bom` + `count_products_with_bom` `where_q`
  now matches product code OR component code (rows.material_code / edges.child_code).
- `app/routes/api.py` — `GET /v1/hub/products` accepts + forwards `q`.
- `app/templates/clients/bom.html` — search placeholder updated.
- `tests/test_bom_search_components.py` — 7 new tests (NEW, untracked).
- `.ai/features/2026-06-01-bom-search-nvl/` — `ui_smoke.py` + committed screenshot (NEW).

**Dev server:** running `uvicorn ... --workers 4` (no `--reload`) on `:8754` with the new
code. Restart gotcha: workers show as `python3`, so kill by port
(`lsof -ti:8754 | xargs kill -9`) not `pkill -f uvicorn`.

**Box (`100.84.189.87` = `tinsu-online-server`):** prod DH `:8754` + CO `:8755` run as
**Docker** (`data-hub-app-1` / `co-app-1`), NOT systemd (repo's `deploy/systemd/*` is
stale). Nightly/demo stack is a separate compose project (`nightly-*`, `:8764`/`:8765`,
repo `tinsu-deploy`); CI auto-refreshes on merge to main. CO↔DH now talk over external
docker net `tinsu-shared` (DH alias `data-hub-app:8754`) for both data + JWKS; issuer +
browser SSO redirect stay public `https://ttdatahub.tinsu.ai`. **That networking feature
is fully closed (verified both sides 2026-06-01).**

## Recent Changes (this session)
- BOM search component matching (see Current State + session log).

## Next Steps
1. **Commit the BOM search change** (3 source files + new test + feature folder) once
   reviewed. Back-compatible: `q` on `/v1/hub/products` is optional, no CO-side change
   needed.
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
