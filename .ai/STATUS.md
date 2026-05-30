# Project Status

**Date:** 2026-05-30 — Service-account admin UI shipped + a new **nightly/demo
stack** (Data Hub + CO) stood up on the demo box behind public HTTPS. See session
log `.ai/sessions/2026-05-30-service-tokens-and-nightly-demo-stack.md`.

## Current State

**Branch:** `main` at `b3f8104`, pushed. **Tests:** 1276 passed, 15 skipped
(re-verify with `uv run pytest -q`). **Migrations:** at **074**.

Recent commits (newest first):
- `b3f8104` / `a2db96f` — ci: on-merge nightly refresh (DH)
- `7d576ed` — docs: sister-app note + DECISIONS, 1y static service tokens
- `47e51ab` — simplify(admin): static 1-year service tokens (drop sliding)
- `27368c9` / `a7d3422` — feat(admin): service-account token UI + expiry

**Dev server:** local `:8754` — bring up with `--workers 4` (no `--reload`) if
needed; note `--workers` would not stay up under the agent tool runner this
session, single-process was used for screenshots.

**Demo box (`100.84.189.87`):** prod DH `:8754` / CO `:8755` unchanged.
**New nightly stack** live: https://demo-datahub.tinsu.ai + https://demo-co.tinsu.ai
(also `:8764`/`:8765`). Repo `TinsuAI/tinsu-deploy` — see its `docs/RUNBOOK.md`.

## Recent Changes (this session)
- **Service-account admin UI** `/admin/service-accounts` (dev-only): mint/list/
  delete/revoke-jti, one-time token reveal, per-mint expiry (mig 073), default
  TTL 1 year (mig 074). Merged + deployed.
- **Nightly/demo stack**: new `tinsu-deploy` repo; both apps dockerized + isolated
  on the box; public HTTPS via the dashboard-managed Cloudflare tunnel; SSO
  cross-domain verified; on-merge triggers wired into DH + CO CI; stable demo
  user `demo@tinsu.ai`; nightly cron + `refresh-now.sh`.

## Next Steps
1. **C.2 strict cutover (prod)** — still open. Mint CO prod service token, fix
   CO's `DATA_HUB_API_TOKEN`→`DATA_HUB_SERVICE_TOKEN` env-key bug, then flip
   `api_auth_strict=true`. Brief: `.ai/features/2026-05-29-api-auth-strict-cutover/brief.md`.
2. **Backlog** still has open items (C.1 sister-app cutover, D.1 aggregate-data
   history, A.3/A.4.2, B.1, B.5) — see `.ai/BACKLOG.md`.
3. Nightly stack: watch box RAM; future tunnel domains via CF dashboard.

## Notes for Next AI Session
- **Nightly stack docs:** `TinsuAI/tinsu-deploy/docs/RUNBOOK.md` is the source of
  truth (architecture, refresh paths, wiring gotchas, troubleshooting). Memory
  `reference_nightly_demo_stack` has the quick pointer.
- **Demo creds:** `demo@tinsu.ai` (admin), password in box `~/tinsu-deploy/.env.nightly`.
- **Gotchas that cost time this session** (don't repeat): cloudflared tunnel is
  dashboard-managed (not config.yml); sudo-rs 0.2.8 ignores scoped NOPASSWD;
  snapshot must drop+recreate DB (not `pg_dump --clean`); CO's env-key bug.
- **Use Windows `ssh.exe`** for the box (WSL ssh broken). Drove all box ops via
  `/mnt/c/Windows/System32/OpenSSH/ssh.exe`.
- Untracked in repo (pre-existing, NOT this session): `.ai/sessions/2026-05-15*`,
  `2026-05-25*`, `2026-05-28*`, `scripts/generate_training_input_scenarios.py`,
  `scripts/uom_drift_report.py`, `docs/training/`. Repo-hygiene triage later.
