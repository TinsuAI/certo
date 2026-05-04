# Session: CO Demo Docker Deploy and CI/CD

## What Was Done
- Refreshed project context from `AGENTS.md`, `.ai/STATUS.md`, `.ai/DECISIONS.md`, and recent session summaries.
- Started/reused the local CO dev server at `http://127.0.0.1:8001`.
- Added a Docker Compose deployment stack for CO:
  - `Dockerfile` using `python:3.12-slim` and `uv`
  - `docker-compose.yml` with `app` and separate Postgres `db`
  - `.dockerignore`
  - `.env.example`
  - `deploy/docker-deploy.md`
- Chose server app port `8755` for CO because Data Hub already uses `8754`.
- Updated CO runtime code for demo deployment:
  - `BARRY_DATABASE_SCHEMA` defaults to `co`, so CO tables live in schema `co`.
  - migrations run during FastAPI lifespan startup.
  - migration execution uses a Postgres advisory transaction lock.
  - `/healthz` returns `{"status":"ok"}`.
  - Data Hub API bearer token is optional when `DATA_HUB_ENABLED=1`.
  - Data Hub auth headers are omitted when no token is configured.
  - Data Hub BOM workspace cache skips cache for fake/no-identity clients, fixing a test-order cache bug.
- Committed Docker/runtime work as `77f193e Add CO demo Docker deployment`.
- Created GitHub repo `TinsuAI/co`, pushed `main`, cloned/pulled it on the demo server, and deployed CO through Docker Compose.
- Generated a local CO seed dump under `data/seed/co-demo.dump`; it remains ignored and was copied to the server for restore/use, not committed.
- Configured CO server env to use the user-provided public CO/Data Hub domains and the same demo LLM settings as Data Hub.
- Confirmed CO reads Data Hub master data directly and only uses its own Postgres DB for CO-owned state.
- Adjusted Data Hub server-side runtime configuration, not Data Hub code:
  - allowed the CO callback origin for Data Hub SSO.
  - changed Data Hub token issuer to the public Data Hub domain.
  - enabled secure Data Hub session cookie for HTTPS.
- Verified server behavior:
  - CO `/healthz` returned OK.
  - CO container could call Data Hub `/v1/hub/dncxs`.
  - CO container could call the configured OpenAI-compatible LLM `/models`.
  - Data Hub SSO login redirected back into CO and rendered the CO clients page with Data Hub clients.
- Added CI/CD in `.github/workflows/ci.yml`.
- Installed a repo-scoped self-hosted GitHub Actions runner for CO on the demo server:
  - runner name `tinsu-co`
  - label `co-demo`
  - user systemd service active
- CI/CD workflow now:
  - runs on `push` to `main`, `pull_request`, and `workflow_dispatch`.
  - runs Python tests on GitHub-hosted Ubuntu.
  - validates Compose config and builds the Docker image on GitHub-hosted Ubuntu.
  - deploys only on `main` push/manual dispatch, after CI passes, using the self-hosted `co-demo` runner.
  - deploy job fetches `origin/main`, resets the server checkout, rebuilds Compose, waits for CO health, and smokes CO-to-Data-Hub connectivity.
- Committed CI/CD as:
  - `c8e269d Add CI/CD workflow`
  - `c5cf9d4 Wait for CO health during deploy`
- Verified latest GitHub Actions run `25303890362` passed all jobs.
- Updated `.ai/STATUS.md` and wrote this handoff.

## Decisions Made
- Use Docker Compose for CO exactly like Data Hub, but bind CO to port `8755`.
- Keep CO and Data Hub databases separate. CO uses schema `co`; Hub remains owner of Hub schemas and master data.
- Treat Data Hub API token as optional for CO reads because the demo Data Hub has API auth disabled.
- Do not add LLM behavior to CO code because CO currently has no LLM settings/usage path. Keep LLM env placeholders for future compatibility and smoke only the configured endpoint from the container.
- Use public HTTPS domains for browser-facing CO/Data Hub SSO settings. Keep real domain/IP/server path details in server `.env` and runtime config, not committed docs.
- Use a self-hosted runner for CD because GitHub-hosted runners cannot directly deploy to the private demo server/Tailscale environment.
- Use a dedicated runner label `co-demo` so only CO deploy jobs land on the CO runner.
- Keep CD minimal: rebuild/restart with Docker Compose and smoke health/Data Hub connectivity; no rollback automation yet.

## What Didn't Work
- Initial `gh repo create --source=. --push` failed because this repo uses a gitfile worktree layout; creating the repo first and adding a remote manually worked.
- Windows `scp.exe` did not understand the relative WSL path for the dump; converting the local path with `wslpath -w` fixed the copy.
- Initial Postgres restore commands expanded `$POSTGRES_USER` on the host instead of inside the container, causing `role "root" does not exist`. Running `psql`/`pg_restore` through container `sh -c` fixed it.
- Restoring after manually creating schema `co` produced `schema "co" already exists`; dropping the schema and letting `pg_restore` recreate it avoided the warning.
- A Data Hub SSO authorize request initially returned `redirect_uri origin is not allowed`; adding the CO public origin to Data Hub server runtime config fixed it.
- Updating Data Hub `hub.app_settings` through quoted shell SQL was error-prone; running a short Python script inside the app container avoided shell quoting issues.
- Pushing `.github/workflows/ci.yml` initially failed because the GitHub token lacked `workflow` scope. `gh auth refresh -s workflow` resolved it.
- First CD run failed because the deploy job hit `/healthz` immediately after container recreate while the app was still starting. A retry loop fixed it.

## Open Items
- Set up equivalent CI/CD for the Data Hub repo with its own self-hosted runner label.
- Consider branch protection once both CO and Data Hub CI/CD are stable.
- Add rollback or blue/green deployment only if demo deploy risk increases.
- Watch GitHub Actions Node.js 20 deprecation annotations; they are warnings for now but may require action version updates later.
- Keep pre-existing untracked `.ai/*` artifacts separate unless the user explicitly asks to commit them.
