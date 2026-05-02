# Feature: Data Hub Link Settings UI

## Scope

Add an operator-facing settings screen in CO for the CO <-> Data Hub link.

This change does:
- Adds a top-level settings route for viewing current Data Hub link configuration.
- Allows local/runtime override of link settings from the UI for demo/local operations.
- Keeps secrets masked in the UI; the token field only writes a new token when supplied.
- Adds a connection check that verifies JWKS reachability and, when Data Hub source mode is enabled, calls the existing Data Hub client adapter.
- Keeps all Data Hub API endpoint usage behind `app/data_hub_client.py`.

This change does not:
- Add or change any Data Hub API contract.
- Store environment-specific config in committed files.
- Build a full admin user/role management system.
- Make browser-based secret editing the production recommendation. Production should still use env/secret store.

## Decisions

- Use `/settings` as the top-level settings entry and `/settings/technical` for the Data Hub technical settings UI.
- Persist UI overrides to a gitignored local JSON file under `data/local/runtime/` by default.
- Add `DATA_HUB_CONFIG_PATH` so tests or deployments can redirect the local override file.
- Keep environment variables as the baseline and let the local override file replace only keys explicitly saved through the UI.
- Mask `DATA_HUB_API_TOKEN`; do not render the raw value back into HTML.
- Guard `/settings/technical` when `CO_AUTH_REQUIRED=1`, while leaving `/settings/theme` public.
- Make `portfolio_service` resolve dynamically so UI changes to `DATA_HUB_ENABLED` or Data Hub URL take effect without editing code. A process restart may still be needed for deployment-level env changes, but local UI override changes should affect new requests.

## Risks

- Saving service tokens from a browser is acceptable for local/demo workflows only; production should use platform secret management.
- If `DATA_HUB_ENABLED=1` is saved without a usable token, Data Hub-backed client pages will fail until config is corrected.
- Auth settings can lock users behind Data Hub SSO if enabled incorrectly. The settings route is guarded only when auth is required and a valid session exists.
- Dynamic service selection changes long-lived behavior that was previously fixed at import time; tests need to cover env/UI config switching.

## Open Questions

- Should production builds disable token editing entirely?
- Should Data Hub expose a lightweight health endpoint for link checks instead of using JWKS and the existing clients endpoint?
- Should settings changes require an admin role claim instead of any authenticated CO user?
