# Project Status

## Current State
- Active branch: `sprint/postgres-source-indexes-20260430`.
- CO now has a Data Hub consumer mode behind feature flags:
  - `CO_AUTH_REQUIRED=1` enables Data Hub SSO/JWKS route guarding.
  - `DATA_HUB_ENABLED=1` switches `portfolio_service` to the Data Hub adapter.
  - `DATA_HUB_BASE_URL`, `DATA_HUB_ISSUER_URL`, `DATA_HUB_JWKS_URL`, `DATA_HUB_API_TOKEN`, and optional `CO_PUBLIC_BASE_URL` configure the integration.
- Shared source/master data is treated as Data Hub-owned in Data Hub mode. CO blocks local catalog, BCCT, BOM, and source-config writes with HTTP 409.
- CO-owned state remains in CO: C/O cases, shipment fields, supporting files, review state, calculation/export snapshots, and generated outputs.
- `app/data_hub_client.py` is the only place raw `/v1/hub/*` paths may appear. `tests/test_data_hub_policy.py` enforces that guardrail.
- Data Hub provider/API changes are intentionally not owned from this repo anymore. New endpoint needs must be captured as `.ai/api-requests/YYYY-MM-DD-<slug>.md` from `.ai/templates/data-hub-api-request.md`, then implemented/tested in the Data Hub repo by the Data Hub agent.
- Dev servers that were started for manual testing were stopped during handoff.

## Recent Changes
- Added Data Hub auth consumer:
  - `app/co_auth.py` verifies EdDSA Data Hub JWTs via JWKS, stores `co_data_hub_session`, guards `/`, `/clients/*`, and `/portfolio/*`, and checks client ACL claims.
  - `app/main.py` adds `/auth/login` and `/auth/callback`, sets the Data Hub user token into request context, and filters the client list when auth is required.
- Added Data Hub source adapter:
  - `app/data_hub_client.py` wraps approved Data Hub endpoints and prefers the current user JWT over the fallback service token.
  - `DataHubPortfolioService` implements CO's existing portfolio boundary for clients, summaries, source workspace, and invoice matches.
  - `app/portfolio.py` selects `DataHubPortfolioService` when `DATA_HUB_ENABLED` is active.
- Added runtime dependencies `httpx` and `pyjwt[crypto]`.
- Added API governance in this repo:
  - `AGENTS.md` now documents the Data Hub API request workflow.
  - `.ai/templates/data-hub-api-request.md` is the request template.
  - `.ai/api-requests/.gitkeep` keeps the request directory present.
  - `tests/test_data_hub_policy.py` prevents raw Data Hub calls outside `app/data_hub_client.py` and allowlists approved endpoint literals.
- Added discovery brief `.ai/features/2026-05-02-data-hub-sso-and-source-consumer.md`.

## Verification
- `uv run pytest -q` in `barry-CO-main` -> `108 passed`.
- Playwright/curl smoke during the session verified:
  - unauthenticated CO `/clients` redirects to Data Hub SSO
  - login/callback returns to CO
  - Data Hub-backed client pages render
  - local shared-source upload in CO returns HTTP 409 in Data Hub mode

## Next Steps
1. Commit and coordinate with the Data Hub agent so provider-side endpoints and auth/scope behavior remain the source of truth there.
2. For any additional source/master-data requirement, create a `.ai/api-requests/YYYY-MM-DD-<slug>.md` artifact first; do not add unapproved `/v1/hub/*` calls.
3. Harden production config: Data Hub should run strict JWT/service-token scope auth before CO Data Hub mode is used outside dev.
4. Replace heavy table pages with paged Data Hub-backed views if large clients make full workspace materialization too slow.
5. Decide whether Data Hub will expose a first-class C/O stock endpoint or whether CO continues deriving C/O stock from Data Hub BCCT rows.

## Blockers
- Full production cutover depends on Data Hub provider-side ownership of the approved API contracts, strict auth mode, and service-token scopes.

## Notes for Next AI Session
- User explicitly asked not to touch `data-hub` from this CO session. Treat Data Hub changes as provider-owned work for the Data Hub agent.
- If a Data Hub contract is missing, stop at an API request artifact and ask for approval instead of editing the sibling repo.
- Keep source/portfolio access behind `portfolio_service` and Data Hub HTTP calls behind `app/data_hub_client.py`.
- `tests/test_data_hub_policy.py` is the guardrail to run when touching Data Hub integration.
- User prefers Vietnamese replies when writing Vietnamese. Project docs and handoff artifacts should stay in English unless client-facing.
