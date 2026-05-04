# Project Status

## Current State
- Active branch: `main`; local branch is in sync with `tinsu/main` at `c5cf9d4`.
- CO demo is deployed on the server through Docker Compose on app port `8755`; `co-app-1` and `co-db-1` are healthy.
- CO has CI/CD in GitHub Actions at `.github/workflows/ci.yml`.
  - Pushes to `main` and manual `workflow_dispatch` run CI, then deploy.
  - Pull requests run CI only.
  - Latest run `25303890362` passed: Python tests, Docker config/build, and deploy smoke checks.
- A self-hosted GitHub Actions runner is registered for this repo with label `co-demo`; service is active on the demo server.
- CO remains a Data Hub consumer. Keep raw `/v1/hub/*` endpoint strings inside `app/data_hub_client.py`; `tests/test_data_hub_policy.py` enforces this.
- Data Hub demo data is now considered ready for live CO demo use. CO reads Data Hub clients/materials/BOM/BCCT directly when `DATA_HUB_ENABLED=1`; CO DB schema `co` stores only CO-owned state.
- Local CO dev server is still running at `http://127.0.0.1:8001`; unauthenticated requests redirect to `/auth/login`.
- Pre-existing untracked artifacts remain separate and should not be committed unless explicitly requested:
  - `.ai/features/2026-05-02-co-bom-data-hub-migration.md`
  - `.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md`
  - `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md`
  - `.ai/sessions/2026-05-04-origin-web-snapshot.md`

## Recent Changes
- Added Docker deployment stack for CO:
  - `Dockerfile`
  - `docker-compose.yml`
  - `.dockerignore`
  - `.env.example`
  - `deploy/docker-deploy.md`
- Updated runtime behavior for demo deploy:
  - CO DB defaults to schema `co`.
  - migrations run at FastAPI lifespan startup with a Postgres advisory transaction lock.
  - Data Hub bearer token is optional, so CO can consume an auth-disabled Data Hub demo.
  - `/healthz` endpoint added for Docker and CI/CD checks.
  - Data Hub BOM workspace cache no longer caches fake/no-identity clients, fixing a test-order cache bug.
- Preserved and committed prior origin-web snapshot application work that was already in the worktree, including origin evidence/readiness fields and related tests.
- Created GitHub repo `TinsuAI/co` and pushed CO `main`.
- Deployed CO to the demo server and configured CO server env to point at the Data Hub demo root URL and LLM endpoint values supplied by the user.
- Updated Data Hub server-side runtime config, not code, so Data Hub SSO accepts the CO callback origin and issues tokens with the public Data Hub issuer.
- Added CI/CD workflow:
  - `Python tests`: `uv sync --frozen --dev`, `uv run pytest`.
  - `Docker config and build`: `docker compose config`, `docker build`.
  - `Deploy demo`: self-hosted runner fetches `origin/main`, resets the server checkout, rebuilds Compose, waits for CO health, and smokes CO-to-Data-Hub connectivity.
- Verification completed:
  - Local `uv run pytest`: `162 passed`.
  - Local `docker compose config` and Docker build passed.
  - Server CO `/healthz` passed.
  - Server CO container reached Data Hub `/v1/hub/dncxs`.
  - Server CO container reached the configured OpenAI-compatible LLM `/models`.
  - Browser SSO smoke flow through Data Hub login returned to the CO clients page and showed Data Hub clients.
  - Latest GitHub Actions CI/CD run passed all jobs.

## Next Steps
1. Set up equivalent CI/CD in the Data Hub repo using a separate self-hosted runner label, as discussed with the user.
2. Keep `.env`, server paths, credentials, and deploy target details out of committed files; use placeholders in docs and server-side `.env` for real values.
3. Consider adding branch protection on `main` after Data Hub CI/CD is in place, requiring CI checks before merge.
4. Revisit rollback strategy later if demo deploys become riskier; current CD rebuilds/restarts but does not perform automatic rollback.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User wants concise but non-black-box explanations: say what was inspected, what failed, and what resolved it.
- For server operations in this environment, follow the Windows OpenSSH workaround from the session instructions instead of WSL native SSH.
- GitHub `gh` auth now has `workflow` scope because pushing workflow files initially failed without it.
- Data Hub code was not changed in this repo. Data Hub server runtime config was changed separately to make SSO work with CO public-domain callbacks.
- GitHub Actions currently shows Node.js 20 deprecation annotations for standard actions. These are warnings only and did not fail the workflow.
