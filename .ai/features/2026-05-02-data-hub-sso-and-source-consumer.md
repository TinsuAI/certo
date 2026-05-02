# Feature: Data Hub SSO And Source Consumer

## Scope
Move CO toward the 3-app architecture where Data Hub owns shared HQ data and identity, while CO owns only origin-certificate workflow state.

This change should:
- use Data Hub as the identity issuer for CO users
- make CO read clients, catalog/materials, BCCT, BQD/code mappings, and BOM from Data Hub APIs
- stop treating CO's catalog/BCCT/BOM upload routes and Postgres source tables as the long-term source of truth
- keep CO cases, shipment fields, origin calculations, exports, and supporting-file workflow state inside the CO app

This does not require moving CO case records or generated C/O dossiers into Data Hub. File snapshot storage in Data Hub is still phase 2, so CO supporting files can stay app-owned for now.

## Current State
CO:
- No real auth exists. `app/main.py` and mounted `app/portfolio.py` are open FastAPI apps; only `co_theme` is stored in a cookie.
- Shared source access is already mostly behind `PortfolioService` in `app/portfolio.py`.
- `app/main.py` reads source workspace and C/O invoice matches through `portfolio_service`, but still handles BOM and CO workflow state directly.
- Catalog and BCCT upload routes call `portfolio_service.process_catalog_upload()` and `process_bcct_upload()`, which currently write to local/Postgres source stores.

Data Hub:
- Working FastAPI/Jinja/Postgres app in the sibling Data Hub repo.
- Has users, `data_hub_session`, 4-role RBAC, and per-client ACL.
- Has JWT SSO endpoints:
  - `POST /v1/auth/token`
  - `GET /v1/auth/jwks`
  - `GET /v1/auth/validate`
- JWTs are Ed25519 and include `iss`, `sub`, `iat`, `exp`, `email`, `role`, and `name`.
- `/v1/hub/*` read API verifies bearer JWTs, but permissive fallback still accepts any non-empty bearer unless `api_auth_strict=true`.
- Data APIs exist for DNCXs/clients, materials, BCCT, code mappings, BOM products/versions, and proposal lookup.

## Decisions
1. **Use Data Hub as identity provider; CO is a JWT consumer.**
   CO should not own passwords or duplicate users. It should verify Data Hub JWTs using JWKS and create its own lightweight app session for server-rendered pages.

2. **Do not use Data Hub `/v1/auth/token` as the browser SSO UX by itself.**
   That endpoint exchanges email/password for a token; using it directly from CO would centralize auth but would not be real SSO. Add a Data Hub browser SSO handoff endpoint or session-token endpoint so users log in once at Data Hub and return to CO with a short-lived JWT/code.

3. **Add claim/ACL enforcement before trusting Data Hub read API in CO.**
   Current Data Hub read routes verify token shape but do not filter by caller claims or per-client ACL. Before CO relies on it, Data Hub should either:
   - filter `/v1/hub/dncxs` and all `client_id` reads by the JWT `sub`, or
   - expose `/v1/auth/me/clients` and require CO to enforce access locally.

4. **Replace `PortfolioService` implementation, not every CO route.**
   Add a `DataHubClient` and a `DataHubPortfolioService` that returns the current CO workspace shape. Keep `app/main.py` consuming `portfolio_service` so source ownership changes are contained.

5. **Make CO shared-source screens read-only.**
   Catalog/BCCT/BOM upload and template routes should be hidden, disabled, or redirected to Data Hub. If upload from CO is later needed, it should call Data Hub upload APIs, not parse and store files in CO.

6. **CO owns derived workflow state, not shared source data.**
   CO case records, shipment form data, invoice matching results, supporting-file metadata, export workbooks, and origin calculation snapshots remain in CO. Data Hub owns raw/shared BCCT, catalog, BQD, BOM versions, and source upload audit.

## Integration Shape
Add CO config:
- `DATA_HUB_BASE_URL`
- `DATA_HUB_ISSUER_URL`
- `DATA_HUB_JWKS_URL`
- `DATA_HUB_API_TOKEN` or a service-token flow for backend reads
- `CO_AUTH_REQUIRED=true|false` for local demo fallback during migration

Add CO auth module:
- verify Data Hub JWT with JWKS and issuer
- store current user in `request.state.user`
- enforce login on all `/clients/*` and `/portfolio/*` pages
- enforce per-client access before serving `/clients/{client_id}/*`
- inject user/logout/login state into templates

Add Data Hub adapter:
- `clients()` -> `GET /v1/hub/dncxs`
- `client(client_id)` -> `GET /v1/hub/dncxs/{client_id}`
- `source_summary(client)` -> either a new Data Hub summary endpoint or aggregate counts from materials/BCCT/products
- `source_workspace(client)` -> material catalog, product catalog, BCCT rows, code mappings, BOM metadata, and derived C/O stock in CO-compatible shape
- `co_case_source_context(client, case)` -> source summary plus invoice-matched export BCCT rows
- `get_client_config()` -> Data Hub client config or a new endpoint if CO-specific config remains separate

## Data Hub API Gaps To Close
Required before full cutover:
- Strict JWT mode should be enabled in production via `api_auth_strict=true`.
- Read API must enforce user/client ACL or provide an explicit ACL endpoint for CO.
- Add browser SSO handoff: login-at-Data-Hub -> return to CO with short-lived JWT/code.
- Add BCCT invoice lookup endpoint, e.g. `GET /v1/hub/bcct/by-invoice/{invoice_ref}?client_id=X`, because CO case matching currently depends on invoice token lookup.
- Add product catalog semantics. CO has `material_catalog` and `product_catalog`; Data Hub currently exposes `materials` by category and `products` mainly through BOM. The adapter needs a stable way to list registered finished products.
- Add a source-summary endpoint, or accept extra round trips in the first adapter.
- Normalize BOM proposal endpoint to `/v1/hub/products/{product_code}/bom/proposals` with bearer/service-token auth. Current implementation is `/api/v1/hub/...` and requires a Data Hub web session.
- Implement real pagination/cursors before CO large table pages stop using local indexed tables.

Deferred:
- Data Hub file snapshot/supporting-file API. CO can keep supporting files locally until Data Hub phase 2 file snapshots exist.
- CO writing BCCT to Data Hub. The current architecture amendment says BCCT is single-writer from Data Hub uploads in MVP.

## Migration Plan
1. Add Data Hub auth consumer to CO with tests for unauthenticated redirect, valid JWT/session, expired JWT, and forbidden client access.
2. Add `DataHubClient` with fixture-backed tests for each Data Hub endpoint shape.
3. Add `DataHubPortfolioService` behind `portfolio_service`, returning the existing CO workspace shape.
4. Switch source reads to Data Hub under a feature flag while keeping local/Postgres source stores as fallback.
5. Make catalog/BCCT/BOM upload pages read-only or redirect to Data Hub when Data Hub mode is enabled.
6. Remove local source ingestion as default once parity tests pass against Data Hub.

## Risks
- **Not true SSO yet:** `/v1/auth/token` is an API credential exchange, not a browser SSO redirect flow.
- **Authorization leak risk:** Data Hub read API currently does not scope `client_id` reads by JWT claims.
- **Shape mismatch:** CO expects `material_catalog`, `product_catalog`, `bcct`, `co_stock_rows`, `client_config`; Data Hub exposes related but not identical concepts.
- **Performance:** CO table pages currently materialize full workspace rows. Data Hub list APIs need real pagination for large BCCT data.
- **BOM write ambiguity:** CO should submit BOM changes as proposals, not direct writes. The existing endpoint is close but not ready for service-to-service use.

## Open Questions
- Should CO use a user JWT for Data Hub reads, or a service token plus separate per-user authorization in CO? For browser pages, user JWT is cleaner. For backend background jobs, service token is cleaner.
- Where should CO-specific source interpretation config live: Data Hub client config, CO schema, or split by concern?
- Should C/O stock be a CO-derived view over Data Hub BCCT, or should Data Hub expose a reusable C/O stock endpoint?
- What exact product categories in Data Hub map to CO `product_catalog`: `sp`, `btp`, both, or a dedicated product registry endpoint?

## Suggested Next Step
Do a small implementation slice:
- Add CO auth/JWKS verification and route guards.
- Add a fake `DataHubClient` test double.
- Replace only `PortfolioService.clients()`, `client()`, and `source_summary()` behind a feature flag.

This validates SSO and the adapter shape before touching BCCT/BOM heavy paths.
