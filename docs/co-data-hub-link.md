# CO and Data Hub Link Configuration

CO can run in local file/Postgres mode or in Data Hub consumer mode. In consumer mode, shared source/master data stays Data Hub-owned and CO reads it only through `app/data_hub_client.py`.

## Mode Flags

- `DATA_HUB_ENABLED=1` switches the portfolio/source service to Data Hub.
- `CO_AUTH_REQUIRED=1` guards CO routes with Data Hub SSO/JWKS auth.
- The two flags are independent for local testing, but production Data Hub mode should normally enable both.

Set environment variables before starting CO. Restart the app after changing shell env values; UI/local override changes apply to new requests without editing code.

The local UI at `/settings/technical` can write demo/runtime overrides to a gitignored JSON file. By default that file is `data/local/runtime/data-hub-link.json`; set `DATA_HUB_CONFIG_PATH` to choose another path. Environment variables win over local UI overrides.

## URLs

- `DATA_HUB_BASE_URL` is the browser-facing Data Hub URL used for login and authorize redirects.
- `DATA_HUB_API_BASE_URL` is the server-to-server Data Hub API URL. It defaults to `DATA_HUB_BASE_URL` and is useful when CO reaches Data Hub through an internal network address.
- `DATA_HUB_ISSUER_URL` is the expected JWT issuer. It defaults to `DATA_HUB_BASE_URL`.
- `DATA_HUB_JWKS_URL` is the JWKS endpoint. It defaults to `${DATA_HUB_ISSUER_URL}/v1/auth/jwks`.
- `CO_PUBLIC_BASE_URL` is the browser-facing CO URL used to build the SSO callback URL.

Local Data Hub currently issues JWTs with `iss=http://localhost:8754`. CO accepts the loopback alias pair `localhost` and `127.0.0.1` for local issuer verification, but production issuer URLs must match exactly.

## Auth and Client Mapping

- `DATA_HUB_SERVICE_TOKEN` is the fallback service token for Data Hub reads and is required when `DATA_HUB_ENABLED=1`.
- CO prefers the current Data Hub user JWT over the fallback service token so Data Hub can enforce per-user ACLs.
- `DATA_HUB_CLIENT_CLAIM_KEYS` configures which JWT claims contain visible client IDs. The default keys are `client_ids,clients,allowed_clients,visible_clients,dncx_ids,client_id,dncx_id`.
- `DATA_HUB_ADMIN_ROLES` configures roles that can see all clients. The default roles are `dev,admin`.
- A JWT claim `all_clients=true` also grants all-client visibility.
- `CO_FORCE_HTTPS_COOKIE=1` marks the CO SSO session cookie as secure for HTTPS deployments.

CO caches Data Hub JWKS in memory and falls back to the cached keys if Data Hub is temporarily unreachable. A previously authenticated CO session can keep working until its JWT expires when the CO process already has the needed JWKS cached. After a CO restart, cache miss, or token expiry, login requires Data Hub to be online again.

`DATA_HUB_ENABLED=1` source/master data reads still require Data Hub to be online because CO does not own that shared data.

Use `config/co-data-hub.env.example` as the local checklist. Do not commit real tokens or environment-specific secrets.

## UI Settings

- Open `/settings`, then `Technical Settings`, to view and edit the local CO -> Data Hub link override.
- The UI masks `DATA_HUB_SERVICE_TOKEN`; leaving the token field blank keeps the existing token.
- `Test connection` checks JWKS and, when source mode is enabled, calls the approved clients endpoint through `app/data_hub_client.py`.
- When `CO_AUTH_REQUIRED=1`, Technical Settings requires a Data Hub user with role `dev`.
- Production deployments should prefer env/secret-store config over browser-edited local overrides. Env values take precedence when both are present.

## Contract Guardrail

CO must not add raw Data Hub endpoint calls outside `app/data_hub_client.py`. If CO needs new Data Hub behavior, create `.ai/api-requests/YYYY-MM-DD-<slug>.md` from `.ai/templates/data-hub-api-request.md` and wait for Data Hub-side approval/provider tests.

## Material Identity Contract

Data Hub owns BCCT-to-BOM material identity resolution. For C/O origin calculation, CO should consume item-level `material_identity` from approved Data Hub BCCT and invoice-match responses.

- Use `material_identity.bom_product_code` only when `material_identity.resolution_status` is `resolved` or `resolved_pending_review`.
- Treat `ambiguous`, `missing`, and `unverified` as unresolved in CO and require case-local operator selection or show the missing-BOM state.
- Do not parse client-specific `goods_name` text in CO.
- Do not call Data Hub code-mapping endpoints for BOM identity; mappings are candidate evidence only and are not a C/O source of truth.
- Do not write case-local BOM TP selections back to Data Hub without a separate approved mutating contract.
