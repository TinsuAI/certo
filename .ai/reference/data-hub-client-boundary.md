# Data Hub Client Boundary

Durable map of `app/data_hub_client.py` — the single module through which CO talks
to the sister app Data Hub (DH). Every claim below is cited to `file:line` at the
time of writing (commit `520b720`). Line numbers drift; the identifiers do not.

## 1. The boundary contract

CO is a consumer of Data Hub, not a co-owner. All DH traffic goes through one
adapter module so that:

- The DH HTTP contract (endpoints, auth, pagination, normalization) lives in one
  file instead of being scattered across routers and services.
- Adding or changing a DH call is a reviewable event gated by the api-request
  workflow (section 5), not an ad-hoc `httpx` call somewhere in a route.
- Response shapes are normalized once (`normalize_client`, `normalize_material_row`,
  `normalize_bcct_row`, `normalize_bom_artifact`, `normalize_bom_payload`) so
  callers see stable field names regardless of DH's raw column naming.

The rule is enforced by `tests/test_data_hub_policy.py`:

- `test_raw_data_hub_api_calls_stay_in_adapter` (`tests/test_data_hub_policy.py:39`)
  walks every `app/**/*.py` except `app/data_hub_client.py` and fails if the literal
  `/v1/hub` appears anywhere. So no other module may name a DH endpoint.
- `test_data_hub_adapter_only_uses_approved_endpoints` (`:56`) extracts every
  `/v1/hub…` string literal from the adapter and asserts it is a subset of
  `APPROVED_DATA_HUB_ENDPOINTS` (`:9-31`). A new endpoint literal fails the test
  until it is added to that set — which is meant to happen only after an
  api-request artifact and DH-side contract approval.
- `test_data_hub_api_request_template_exists` (`:67`) locks the required section
  headings of the request template.

The same rule is stated for humans in the project `CLAUDE.md` section "Data Hub API
Requests".

Exception worth knowing: a non-`/v1/hub` DH URL is NOT covered by the guardrail.
`app/workbook_io.py:1097` builds a plain manifest link
`{data_hub_base_url}/clients/{client_id}/declarations/download.zip` for the dossier
ZIP fallback; because it lacks the `/v1/hub` prefix, the policy test does not catch
it. The guardrail is a substring check on `/v1/hub`, not a full URL audit.

## 2. Endpoints consumed

Raw `DataHubClient` methods (`app/data_hub_client.py:54`). Column "Cache TTL" is the
caller-side cache that wraps the call, not a DH cache. "—" = no CO-side cache; the
call hits DH every time (subject to the env-keyed portfolio-service instance reuse).

| DH endpoint | HTTP | Adapter method (`:line`) | CO caller(s) | Data | Cache TTL |
|---|---|---|---|---|---|
| `/v1/hub/dncxs` | GET | `list_clients` (`:73`) | `DataHubPortfolioService.clients`; settings health check `settings.py:149` | client list | — |
| `/v1/hub/dncxs/{client_id}` | GET | `get_client` (`:76`) | `DataHubPortfolioService.client` / `client_summary` | one client | — |
| `/v1/hub/dncxs/{client_id}/client-config` | GET | `get_client_config` (`:443`) | `DataHubPortfolioService.get_client_config` / `save_client_config` | DH-owned `bcct` preset (partition-merged with CO-owned `allocation_code` + `co_stock.lot_policy`) | — |
| `/v1/hub/dncxs/{client_id}/source-summary` | GET | `source_summary` (`:446`) | `DataHubPortfolioService.source_summary`; client dashboard, co-stock, pages | catalog row counts + versions + client_config | — (downstream `_CO_CASE_SOURCE_CACHE` 90s) |
| `/v1/hub/materials` | GET | `list_materials` (`:79`) | heavy `co_case_source_context` (`:919`); `material_catalog` (`:858`); `search_materials` (`:842`); `_source_states` (`:1054`); `co_case.py:552`; `_material_catalog_rows` (`co_case.py:530`) | NVL (material) catalog | `_CO_MATERIAL_CATALOG_CACHE` 300s (substitute modal); `_MATERIAL_CATALOG_CACHE` 90s (bảng kê fast path); `_CO_CASE_SOURCE_CACHE` 90s (heavy) |
| `/v1/hub/bcct` | GET | `list_bcct` (`:82`), `list_bcct_with_envelope` (`:85`), `bcct_server_time` (`:107`) | heavy `co_case_source_context` (`:927`); narrow `origin_invoice_matches` (`:980`, `declaration_no=`); co-stock delta refresh (`co_case_context.py:3740,3825`); `co_case.py:422,486` | customs declaration (tờ khai) rows | heavy via `_CO_CASE_SOURCE_CACHE` 90s; co-stock materializer cache |
| `/v1/hub/bcct/invoice-matches` | GET | `invoice_matches` (`:490`) | `origin_invoice_matches` invoice branch (`:990`); heavy path (`:939`); typeahead `co_case.py:276,415,479` | indexed invoice→export match rows | — |
| `/v1/hub/products` | GET | `list_products` (`:283`), `list_bom_products` (`:286`) | `_source_states` fallback (`:1058`); `bom_service.py:120,140` | product (TP) catalog | bom workspace 60s |
| `/v1/hub/products/{product_code}/bom` | GET | `get_bom_artifact` (`:409`) | `bom_service.py:441` | one BOM artifact's rows | bom workspace 60s |
| `/v1/hub/products/{product_code}/bom/latest` | GET | `get_bom_latest` (`:399`) | `bom_service.py:354` | latest BOM (409→`DataHubBomVariantConflict`) | bom workspace 60s |
| `/v1/hub/products/{product_code}/bom/proposals` | POST | `submit_bom_proposal` (`:417`) | `co_case.py:2869` (modified-for-case BOM) | mutating; returns proposal | — |
| `/v1/hub/products/{product_code}/bom/artifacts` | GET | `list_bom_artifacts` (`:289`), `list_bom_artifacts_filtered` (`:298`) | `bom_service.py:415,428` (picker) | BOM artifact summaries | bom workspace 60s |
| `/v1/hub/products/bom/artifacts:batch` | POST | `list_bom_artifacts_batch` (`:339`) | `bom_service.py:245` (multi-product fan-in) | BOM artifacts + rows for many products | bom workspace 60s |
| `/v1/hub/proposals/{proposal_id}` | GET | `get_bom_proposal` (`:440`) | defined; no active app caller (proposal-status poll) | one proposal | — |
| `/v1/hub/materials/{material_code}` | GET | `get_material` (`:480`) | `co_case.py:2696` (seed material for substitute heuristic) | one material row | — |
| `/v1/hub/clients/{client_id}/materials/{material_code}/substitutes` | GET | `list_material_substitutes` (`:449`) | `co_case.py:2355` (substitute modal) | ranked substitute candidates; Bearer scope `hub:read` | — |
| `/v1/hub/clients/{client_id}/bcct/by-codes` | GET | `list_bcct_by_codes` (`:116`) | `origin_invoice_matches` enrich (`:996`); `co_case.py:604` (import narrow) | BCCT rows filtered by item code | — |
| `/v1/hub/clients/{client_id}/declarations` | GET | `list_declarations` (`:135`) | `declaration_file_counts` (`:1023,1028`); `co_case.py:805` | file-count / declaration metadata | — |
| `/v1/hub/clients/{client_id}/declarations/download.zip` | GET | `download_declarations_zip` (`:152`) | defined; dossier falls back to manifest link (`workbook_io.py:1097`) when 404 | raw declaration-file ZIP bytes | — |
| `/v1/hub/clients/{client_id}/declarations/download.pdf` | GET | `download_declarations_pdf` (`:184`) | `co_case.py:1512` (tờ khai ghép) | merged TKX/TKN PDF (or split ZIP) | — (180s read budget) |

Shared HTTP mechanics inside the adapter:

- `_get` (`:509`) / `_post` (`:523`) attach the Bearer header via `_auth_headers`
  and raise on non-2xx. `_get` also runs the client-id suffix fallback (below).
- `_get_all` (`:553`) paginates on `next_cursor` (`:1085`, accepts `next_cursor`,
  `nextCursor`, or `pagination.next_cursor`) with a default `limit=1000`, guarding
  against cursor loops. `_get_all_envelope` (`:568`) and `_get_filter_envelope`
  (`:599`) are the same loop but also capture first-page `tombstones`/`server_time`
  (delta refresh) or `filter_applied` (BOM picker contract).
- Client-id suffix fallback: DH stores IDs with a country suffix (`growatt-vn`)
  while CO URLs use the short form (`growatt`). `_client_id_attempts` (`:528`,
  `_CLIENT_ID_FALLBACK_SUFFIXES = ("-vn",)` `:507`) retries a 404 once with the
  suffix appended to both the path segment and the `client_id` query param.

### Narrow vs heavy pull (the 524 distinction)

The same catalog data can be fetched two ways. The distinction is the direct cause
of the Cloudflare 524 incidents (`>100s` origin timeout); see
`.ai/sessions/2026-07-27-co-524-shipment-substitute-narrow-fetch.md`.

- Heavy pull: `DataHubPortfolioService.co_case_source_context` (`:872`) without
  `skip_heavy_context` paginates the FULL `list_materials` (~12k rows) AND the full
  `list_bcct` (~65-73k rows for Johnson) synchronously. Measured ~104-125s cold.
  Past the 100s Cloudflare limit → 524. Only the origin tab needs this full context.
- Narrow pull: for non-origin tabs (shipment / documents / exports / review) the
  `skip_heavy_context` branch (`:903`) fetches only what those tabs render:
  - export-declaration case → `origin_invoice_matches` (`:956`): per-declaration
    `list_bcct(declaration_no=…, direction="export")` then `match_case_bcct_exports`
    — proven byte-identical to the full pull (43/43 on Johnson). `material_rows` and
    `stock_rows` stay empty.
  - invoice-only case → the indexed `invoice_matches` endpoint, then a `by-codes`
    export fetch scoped to the matched item codes.
  Measured on prod (case `co-case-1919b9cf8fbf`): 124.88s → 0.31s, 90 HTTP calls → 3
  (`544840e`).
- Substitute modal: reads only `material_rows`, so it goes through
  `material_catalog` (`:858`, materials-only, drops `category == "tp"`) via
  `co_case_material_catalog_cached` — never `co_case_source_context`. Measured
  ~125s → 15.69s, 0 BCCT calls (`c104615`). Parity locked by
  `test_material_catalog_equals_heavy_path_material_rows` (`8556ee1`).

## 3. The two backends

`get_portfolio_service` (`app/portfolio.py:247`) returns one of two objects behind a
common interface (`clients`, `client`, `source_summary`, `get_client_config`,
`co_case_source_context`, `list_material_substitutes`, …). Callers use them through
`portfolio_service` (a `PortfolioServiceProxy`, `portfolio.py:284-289`), so most code
does not know which backend is live.

Mode selection (`portfolio.py:247-261`):

1. `data_hub_client_from_env` (`data_hub_client.py:1067`) reads
   `data_hub_link_settings()`. If `source_enabled` is true (env `DATA_HUB_ENABLED`,
   `data_hub_settings.py`) it builds a `DataHubClient` and returns
   `DataHubPortfolioService`.
2. If DH is off and `CO_ALLOW_LOCAL_SOURCE` is set (`allow_local_source`), returns
   the local `PortfolioService`. This is the tests / offline-dev path.
3. Otherwise raises `SourceBackendUnavailable` (→ 503) so a real deployment fails
   loudly instead of silently serving stale local backup data.

The chosen service is memoized by `current_portfolio_service`
(`portfolio.py:267-281`) keyed on `(source_enabled, allow_local_source,
data_hub_api_base_url, api_token, request_timeout_seconds)`.

`DataHubPortfolioService` (`data_hub_client.py:660`) — real DH:
- Reads: `clients`, `client`, `client_summary`, `source_summary`, `source_workspace`,
  `co_case_source_context`, `origin_invoice_matches`, `material_catalog`,
  `search_materials`, `get_material`, `list_material_substitutes`,
  `list_bcct_by_codes`, `list_declarations`, `declaration_file_counts`.
- Config: `get_client_config` / `save_client_config` partition-merge (`#14`,
  `_partition_merge_config` `:647`) — DH owns `bcct`, CO owns `allocation_code` +
  `co_stock.lot_policy` (persisted through `_local_config_store` `:636`, which is the
  Postgres app-state store when `BARRY_DATABASE_URL` is set, else the local file
  config store). Saving a `bcct` change is rejected (`:710`).
- Writes: `submit_bom_proposal` (`:765`).
- Refuses catalog/BCCT uploads and templates (`:1036-1049`) — those belong in DH.

`PortfolioService` (`app/portfolio.py:56`) — local/file (and Postgres index):
- Same read interface, served from `get_app_state_store()` / seed demo data /
  `get_source_index_store()` (Postgres) / file module states. `source_backend` is
  `"postgres"` or `"files"` here, versus `"data-hub"` for the DH backend.
- `co_case_source_context` treats `skip_heavy_context` as a no-op — the local
  context is in-memory and cheap (`portfolio.py:131`).
- Stubs the DH-only methods: `list_material_substitutes` → `([], "no_data_hub")`,
  `list_bcct_by_codes` → `[]`, `get_material` → `{}`, `submit_bom_proposal` → 503.
- Owns catalog/BCCT uploads and template generation (the inverse of the DH backend).

Note: some hot paths bypass the portfolio interface and reach the raw client via
`getattr(portfolio_service, "data_hub", None)` (e.g. `co_case.py:257,412,469,546,801,1487`,
`co_case_context.py:3689,3814`). Present only on the DH backend; `None` on the local
backend, which those call sites check before using.

## 4. Auth & session

CO authenticates operators against DH via SSO and forwards each operator's own
access token to DH on read calls (so DH row scoping applies per user). Two token
kinds exist: the per-operator access token (short-lived, forwarded) and the service
token (`DATA_HUB_SERVICE_TOKEN`, the adapter's fallback for unauthenticated /
background calls).

Token forwarding into the adapter:

- `CURRENT_DATA_HUB_TOKEN` is a `ContextVar` (`data_hub_client.py:18`).
  `DataHubClient` is constructed with `token_provider=current_data_hub_token`
  (`portfolio.py:248`, `bom_service.py:468`), and `_auth_headers` (`:627`) prefers
  the provider's token, falling back to the static service `token`.
- The HTTP middleware `require_data_hub_auth` (`app/main.py:217-231`) verifies the
  session, then `set_current_data_hub_token(user.access_token)` for the request and
  resets it in `finally`. So each request's DH calls carry that operator's token.

SSO exchange and cookies (`app/co_auth.py`, `app/routers/auth.py`):

- Cookies: `co_data_hub_session` (access token, `CO_SESSION_COOKIE` `co_auth.py:16`,
  short max-age default 600s) and `co_data_hub_refresh` (rotating refresh token,
  `CO_REFRESH_COOKIE` `:17`, 7-day ceiling). Both `httponly`, `samesite=lax`,
  `secure` gated on `CO_FORCE_HTTPS_COOKIE`.
- Login: `/auth/login` → DH `/v1/auth/authorize` → `/auth/callback`
  (`routers/auth.py:46`) calls `exchange_data_hub_sso_code` (`co_auth.py:356`, POST
  `/v1/auth/exchange`), verifies the JWT (`DataHubTokenVerifier`, EdDSA, JWKS cached
  300s `:21`), then sets both cookies.
- Silent refresh: `/auth/refresh` (`routers/auth.py:75`) trades the refresh cookie
  via `refresh_data_hub_session` (`co_auth.py:372`, POST `/v1/auth/refresh`),
  rotates both cookies. On any DH rejection it clears cookies and returns
  `session_expired`.

The 401 `session_expired` XHR path:

- When auth fails on a request, `auth_challenge` (`co_auth.py:311`) branches on
  `is_xhr_request` (`:~289`, tests `sec-fetch-dest != document`, `x-requested-with`,
  or a JSON-only `Accept`). Browser navigations get a 303 redirect to login; XHR/
  fetch requests get `session_expired_json` (`:300`): HTTP 401 with
  `{"code": "session_expired", "login_url": …}`.
- The client keep-alive / retry logic in `app/templates/base.html:47,113` watches for
  `code === "session_expired"`, calls `/auth/refresh`, and only surfaces the
  interactive login when refresh also fails — so an active operator is not bounced
  mid-work. Contract: `.ai/api-requests/2026-07-10-session-token-refresh.md`.

## 5. Adding or changing DH behavior

Do not add a raw `/v1/hub` call, and do not add an endpoint literal to the adapter,
without going through the request-and-approve workflow. The policy test will block
both.

Workflow (project `CLAUDE.md`, "Data Hub API Requests"):

1. Check `app/data_hub_client.py` and the current DH contract first — the gap may
   already be covered by an existing adapter method.
2. If not, write `.ai/api-requests/YYYY-MM-DD-<slug>.md` from
   `.ai/templates/data-hub-api-request.md`. Required sections (locked by
   `test_data_hub_api_request_template_exists`): Use Case, Existing Endpoint Gap,
   Proposed Contract, Auth, Data Semantics, Tests Required In Data Hub, CO Consumer
   Plan, Approval. Fill in request/response JSON, auth scope, client-scoping rule,
   pagination, precision, idempotency, error cases.
3. Stop and get DH-side contract approval. Do not implement CO behavior against an
   unapproved endpoint.
4. DH implements it and passes provider tests.
5. Consume it only through `app/data_hub_client.py` (a new adapter method), and add
   the endpoint literal to `APPROVED_DATA_HUB_ENDPOINTS` in
   `tests/test_data_hub_policy.py`. Do not scatter raw calls.
6. A mutating call needs an explicit service-token scope (e.g. `hub:propose:bom`).
   Do not rely on permissive bearer auth.

Checklist for one new/changed DH call:
- [ ] Existing adapter method insufficient (state why).
- [ ] api-request artifact written from the template, all 8 sections filled.
- [ ] DH contract owner approved; approval date + DH commit recorded.
- [ ] DH provider + negative + edge tests pass.
- [ ] Adapter method added in `data_hub_client.py`; response normalized.
- [ ] Endpoint literal added to `APPROVED_DATA_HUB_ENDPOINTS`.
- [ ] Consumer test added; `tests/test_data_hub_policy.py` green.
- [ ] Mutating call carries an explicit scope.

### api-request artifacts to date

The `.ai/api-requests/` folder is the log of this workflow in practice. `-dh-prompt`
files are the paste-to-DH build/fix prompts; the sibling file is CO's request/contract.

- `2026-05-03-bcct-invoice-market-fields` — BCCT invoice + market fields.
- `2026-05-04-customs-exchange-rates` — customs exchange rates.
- `2026-05-07-bcct-bom-product-resolution` — BCCT→BOM product resolution.
- `2026-05-11-bearer-aware-substitutes` — Bearer-aware substitutes endpoint.
- `2026-05-13-bcct-by-codes-lookup` — BCCT lookup by material codes.
- `2026-05-15-declaration-file-status` — declaration file status/counts.
- `2026-05-28-bcct-declarations-download-bearer` — Bearer-aware declarations download.
- `2026-05-28-bcct-incremental-since-filter` — BCCT `since` filter + tombstones (delta).
- `2026-05-28-bom-artifacts-active-flat-filter` — `/bom/artifacts` active+flat picker filter.
- `2026-05-31-bom-artifacts-batch-fetch` (+ `-dh-prompt`) — batch multi-product BOM artifacts.
- `2026-06-04-declarations-download-zip-missing-file-bytes` (+ `-dh-prompt`) — defect: ZIP returned manifest only, no file bytes.
- `2026-06-05-bom-picker-shallow-profile-filter` (+ `-dh-prompt`) — `depth=full` (exclude shallow flattens).
- `2026-06-05-declarations-merged-pdf` (+ `-dh-prompt`) — merged TKX/TKN PDF (tờ khai ghép).
- `2026-06-06-declarations-download-unauthenticated-leak` (+ `-dh-prompt`) — CRITICAL: download endpoints served files with no auth.
- `2026-06-06-declarations-auth-regression-tests-dh-prompt` — regression tests to lock declarations auth.
- `2026-06-07-products-total-count` — reliable `total` + real pagination for `/v1/hub/products`.
- `2026-06-09-johnson-bom-material-group-gap` — classify Johnson BOM-only codes (material_group gap).
- `2026-06-18-declarations-pdf-efficiency-dh-prompt` — merged PDF speed + file-size efficiency.
- `2026-06-20-bom-artifact-coverage-readiness` — coverage/readiness signal per product.
- `2026-06-20-bom-observed-customs-relevance-coverage` — `customs_relevance` coverage for `bom_observed` (DC1).
- `2026-06-20-bom-observed-material-names` — stable material names for `bom_observed` codes (DC2).
- `2026-07-10-session-token-refresh` (+ `-dh-prompt`) — renewable session so operators aren't forced to re-login.

## 6. Known perf edges

- Narrow-fetch history: the origin tab has used the narrow per-declaration /
  by-codes fetch since 2026-05-31
  (`.ai/features/2026-05-31-origin-narrow-bcct-fetch/brief.md`). The 2026-07-27
  session extended the same narrow paths to the shipment landing tab (`544840e`) and
  the substitute modal (`c104615`, `8556ee1`) after both re-triggered 524s as Johnson
  grew to ~73k BCCT rows. Root cause each time: a path pulled the full DH catalog
  synchronously on the async event loop and only used a slice of it.
- Residual A — `include_material_identity` (UNVERIFIED as still open): the shipment /
  substitute narrow fetch omits `include_material_identity="true"`, so on non-origin
  cold windows `item_code` / `material_identity` may show the raw customs code rather
  than the resolved display code. Recorded as display-only, no calc impact. Fixing
  means adding the flag in `origin_invoice_matches` (`data_hub_client.py:956`), which
  is shared with the origin tab, so it needs its own test. Ticketed as follow-up A in
  the 2026-07-27 session; not confirmed resolved here.
- Residual B — async-offload (UNVERIFIED as still open): `co_case_detail` /
  `co_case_step` and the substitute endpoint are `async def` calling the sync catalog
  pull, so the residual ~15s first-open materials fetch still blocks the event loop
  (15s < 100s, so no 524, but one slow request can stall others). Ticketed as
  follow-up B / H2; not addressed here.
- Cache layers that absorb repeat calls (all in-process, per-worker):
  - `_CO_MATERIAL_CATALOG_CACHE` 300s, client-wide (`co_case_context.py:371`) —
    substitute modal materials catalog.
  - `_MATERIAL_CATALOG_CACHE` 90s, per client (`co_case.py:526`) — bảng kê fast-path
    materials catalog (prevents blank NVL names in the export).
  - `_CO_CASE_SOURCE_CACHE` 90s, keyed on client + case + shipment fingerprint
    (`co_case_context.py:319`) — heavy source context; ledger/stock re-applied on
    every read so cached stock never goes stale.
  - `_DATA_HUB_BOM_WORKSPACE_CACHE` 60s (`bom_service.py:29`), key includes base_url +
    token (`data_hub_cache_identity` `:497`) so a token/base change does not serve
    another identity's cache.
  - Portfolio-service instance reuse, env-keyed (`portfolio.py:264-281`).
- DH-side note (info): BCCT pagination is ~1.4s per 1000-row page. Fine now that CO
  does not pull the full corpus, but any resurfaced full-pull path pays it linearly.
